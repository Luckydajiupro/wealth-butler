"""Measure authenticated customer SSE performance without storing sensitive data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import requests
from dotenv import load_dotenv


MESSAGE = "你好，请用一句话介绍你能提供的服务。"
EXPECTED_USER_ID = 1640
REPO_ROOT = Path(__file__).resolve().parents[1]


def percentile(values: list[float], percent: float) -> float | None:
    """Return a linearly interpolated percentile for a non-empty sample."""
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = (len(ordered) - 1) * percent / 100
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return round(ordered[lower], 1)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)
    return round(value, 1)


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary = {}
    for kind in ("cold", "hot"):
        group = [sample for sample in samples if sample["kind"] == kind]
        successful = [sample for sample in group if sample["success"]]
        first_frames = [float(sample["first_frame_ms"]) for sample in successful]
        completions = [float(sample["completion_ms"]) for sample in successful]
        summary[kind] = {
            "sample_count": len(group),
            "success_count": len(successful),
            "success_rate_percent": round(len(successful) / len(group) * 100, 1) if group else 0.0,
            "first_frame_ms": {
                "p50": percentile(first_frames, 50),
                "p95": percentile(first_frames, 95),
            },
            "completion_ms": {
                "p50": percentile(completions, 50),
                "p95": percentile(completions, 95),
            },
        }
    return summary


def _load_credentials(expected_model: str) -> tuple[str, str]:
    load_dotenv(dotenv_path=REPO_ROOT / ".env", override=False)
    password = os.environ.get("WEALTH_BUTLER_SEED_PASSWORD")
    model = os.environ.get("DEEPSEEK_DEFAULT_MODEL", "").strip()
    if not password:
        raise RuntimeError("WEALTH_BUTLER_SEED_PASSWORD is required")
    if model != expected_model:
        raise RuntimeError(f"DEEPSEEK_DEFAULT_MODEL must remain {expected_model}")
    return password, model


def _authenticate(
    session: requests.Session,
    base_url: str,
    username: str,
    password: str,
    timeout: float,
) -> str:
    login = session.post(
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password},
        timeout=timeout,
    )
    login.raise_for_status()
    data = login.json()["data"]
    if int(data["id"]) != EXPECTED_USER_ID:
        raise RuntimeError("authenticated seed user id did not match 1640")
    return str(data["access_token"])


def _measure_request(
    session: requests.Session,
    base_url: str,
    token: str,
    timeout: float,
    kind: str,
    cycle: int,
    sequence: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    first_frame_at: float | None = None
    frame_count = 0
    status = None
    content_type = ""
    error_type = None
    try:
        response = session.post(
            f"{base_url}/api/chat/customer",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "message": MESSAGE,
                "session_id": f"deepseek-sse-{uuid4().hex}",
                "is_stream": True,
            },
            stream=True,
            timeout=(min(timeout, 30.0), timeout),
        )
        status = response.status_code
        content_type = response.headers.get("content-type", "")
        try:
            for line in response.iter_lines(decode_unicode=False):
                if line.startswith(b"data:"):
                    frame_count += 1
                    if first_frame_at is None:
                        first_frame_at = time.perf_counter()
        finally:
            response.close()
    except Exception as error:
        error_type = type(error).__name__
    completed_at = time.perf_counter()
    first_frame_ms = round((first_frame_at - started) * 1000, 1) if first_frame_at else None
    completion_ms = round((completed_at - started) * 1000, 1)
    streamed_before_completion = first_frame_at is not None and first_frame_at < completed_at
    success = (
        error_type is None
        and status == 200
        and content_type.lower().startswith("text/event-stream")
        and frame_count >= 2
        and streamed_before_completion
    )
    return {
        "cycle": cycle,
        "sequence": sequence,
        "kind": kind,
        "success": success,
        "http_status": status,
        "content_type": content_type,
        "frame_count": frame_count,
        "first_frame_ms": first_frame_ms,
        "completion_ms": completion_ms,
        "streamed_before_completion": streamed_before_completion,
        "error_type": error_type,
    }


def verify(base_url: str, username: str, timeout: float) -> dict[str, object]:
    password, _model = _load_credentials("deepseek-v4-flash")
    with requests.Session() as session:
        session.trust_env = False
        token = _authenticate(session, base_url, username, password, timeout)
        return _measure_request(session, base_url, token, timeout, "cold", 1, 1)


def _local_address(base_url: str) -> tuple[str, int]:
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("managed cycles require a local http base URL")
    return parsed.hostname, parsed.port or 80


def _wait_until_ready(process: subprocess.Popen, host: str, port: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited before readiness (code={process.returncode})")
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError("server readiness timed out")


def _stop_server(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.terminate()
    else:
        process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _start_server(base_url: str, startup_timeout: float) -> subprocess.Popen:
    host, port = _local_address(base_url)
    try:
        with socket.create_connection((host, port), timeout=0.3):
            raise RuntimeError(f"port {port} is already in use")
    except OSError:
        pass
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.WealthButler.main:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    try:
        _wait_until_ready(process, host, port, startup_timeout)
    except Exception:
        _stop_server(process)
        raise
    return process


def run_managed_samples(
    base_url: str,
    username: str,
    timeout: float,
    startup_timeout: float,
    cycles: int,
    hot_per_cycle: int,
    expected_model: str,
) -> dict[str, Any]:
    password, model = _load_credentials(expected_model)
    samples = []
    for cycle in range(1, cycles + 1):
        process = _start_server(base_url, startup_timeout)
        try:
            with requests.Session() as session:
                session.trust_env = False
                token = _authenticate(session, base_url, username, password, timeout)
                samples.append(_measure_request(session, base_url, token, timeout, "cold", cycle, 1))
                for sequence in range(1, hot_per_cycle + 1):
                    samples.append(
                        _measure_request(
                            session, base_url, token, timeout, "hot", cycle, sequence
                        )
                    )
        finally:
            _stop_server(process)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "endpoint": "/api/chat/customer",
        "configuration": {
            "cycles": cycles,
            "hot_per_cycle": hot_per_cycle,
            "timeout_seconds": timeout,
            "startup_timeout_seconds": startup_timeout,
            "expected_user_id": EXPECTED_USER_ID,
            "response_content_stored": False,
        },
        "samples": samples,
        "summary": summarize_samples(samples),
    }


def _default_output() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / "docs" / "evidence" / f"deepseek-sse-{timestamp}.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--username", default="wb_seed_c1_elderly")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--startup-timeout", type=float, default=90.0)
    parser.add_argument("--cycles", type=int, default=0)
    parser.add_argument("--hot-per-cycle", type=int, default=2)
    parser.add_argument("--expected-model", default="deepseek-v4-flash")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    if args.cycles <= 0:
        print(json.dumps(verify(base_url, args.username, args.timeout), ensure_ascii=False))
        return
    if args.hot_per_cycle <= 0:
        parser.error("--hot-per-cycle must be positive")
    report = run_managed_samples(
        base_url=base_url,
        username=args.username,
        timeout=args.timeout,
        startup_timeout=args.startup_timeout,
        cycles=args.cycles,
        hot_per_cycle=args.hot_per_cycle,
        expected_model=args.expected_model,
    )
    output = (args.output or _default_output()).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": report["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
