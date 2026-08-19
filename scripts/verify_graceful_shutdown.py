"""Verify that the formal WealthButler entry point shuts down gracefully."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def verify(
    startup_timeout: float,
    shutdown_timeout: float,
    port: int,
    disable_operator: bool,
    shutdown_signal: str,
) -> dict[str, object]:
    if os.name != "nt":
        raise RuntimeError("This verifier currently targets the project's Windows runtime")
    if _port_is_open(port):
        raise RuntimeError(f"port {port} is already in use")

    started = time.perf_counter()
    child_env = os.environ.copy()
    if disable_operator:
        child_env["WEALTH_BUTLER_OPERATOR_REAL_ENABLED"] = "false"
    process = subprocess.Popen(
        [sys.executable, "app/WealthButler/main.py"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=child_env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    forced = False
    port_released_before_force = False
    try:
        deadline = time.perf_counter() + startup_timeout
        while time.perf_counter() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"server exited during startup with code {process.returncode}")
            if _port_is_open(port):
                break
            time.sleep(0.2)
        else:
            raise TimeoutError(f"server did not listen on port {port} within {startup_timeout}s")

        ready_at = time.perf_counter()
        selected_signal = (
            signal.CTRL_BREAK_EVENT if shutdown_signal == "break" else signal.CTRL_C_EVENT
        )
        process.send_signal(selected_signal)
        try:
            exit_code = process.wait(timeout=shutdown_timeout)
        except subprocess.TimeoutExpired:
            port_released_before_force = not _port_is_open(port)
            forced = True
            process.kill()
            process.wait(timeout=5)
            exit_code = process.returncode
        stopped_at = time.perf_counter()
    finally:
        if process.poll() is None:
            forced = True
            process.kill()
            process.wait(timeout=5)

    return {
        "startup_ms": round((ready_at - started) * 1000, 1),
        "shutdown_ms": round((stopped_at - ready_at) * 1000, 1),
        "shutdown_timeout_s": shutdown_timeout,
        "forced_termination": forced,
        "exit_code": exit_code,
        "port_released": not _port_is_open(port),
        "operator_enabled": not disable_operator,
        "shutdown_signal": shutdown_signal,
        "port_released_before_force": port_released_before_force,
        "passed": not forced and not _port_is_open(port),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--startup-timeout", type=float, default=45.0)
    parser.add_argument("--shutdown-timeout", type=float, default=10.0)
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--disable-operator", action="store_true")
    parser.add_argument("--signal", choices=("break", "ctrl-c"), default="break")
    args = parser.parse_args()
    result = verify(
        args.startup_timeout,
        args.shutdown_timeout,
        args.port,
        args.disable_operator,
        args.signal,
    )
    print(json.dumps(result))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
