"""Snapshot and safely classify historical EventBus dead-letter records.

Dry-run is read-only. Apply writes a local recovery snapshot and ACKs only
original PEL messages whose payload is proven incompatible with the current
schema. DLQ streams are never deleted, trimmed, or overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APPLY_CONFIRMATION = "SNAPSHOT_CLASSIFY_NO_DELETE"
SNAPSHOT_DIR = ROOT / "runtime_artifacts" / "dlq"
GROUP_BY_STREAM = {
    "stream:large_transaction": "risk_monitor_group",
    "stream:suspicious_intent": "risk_monitor_group",
    "stream:risk_alert": "advisor_group",
    "stream:profile_updated": "recommendation_group",
    "stream:work_order": "advisor_group",
}


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def normalize_fields(fields: dict[Any, Any]) -> dict[str, str]:
    return {_text(key): _text(value) for key, value in fields.items()}


def classify(fields: dict[str, str]) -> str:
    """Classify without executing a handler or exposing payload contents."""
    from app.WealthButler.EventBus.schemas import validate_event

    payload_text = fields.get("payload", "")
    event_type = fields.get("event_type", "")
    try:
        payload = json.loads(payload_text)
    except (TypeError, json.JSONDecodeError):
        return "TERMINAL_INVALID_JSON"
    try:
        validate_event(event_type, payload)
    except (ValidationError, ValueError, TypeError):
        return "TERMINAL_SCHEMA_INVALID"
    return "RETAIN_HANDLER_FAILURE"


def read_entries(client: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    keys = sorted(_text(key) for key in client.scan_iter(match="stream:*:dead_letter"))
    for dlq_stream in keys:
        for dlq_message_id, raw_fields in client.xrange(dlq_stream, min="-", max="+"):
            fields = normalize_fields(raw_fields)
            original_stream = fields.get("original_stream") or dlq_stream.removesuffix(":dead_letter")
            original_msg_id = fields.get("original_msg_id", "")
            records.append({
                "dlq_stream": dlq_stream,
                "dlq_message_id": _text(dlq_message_id),
                "original_stream": original_stream,
                "original_msg_id": original_msg_id,
                "trace_id": fields.get("trace_id", ""),
                "classification": classify(fields),
                "fields": fields,
            })
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    classifications = Counter(record["classification"] for record in records)
    identities = Counter(
        (record["original_stream"], record["original_msg_id"], record["trace_id"])
        for record in records
    )
    return {
        "dlq_records": len(records),
        "unique_originals": len(identities),
        "duplicate_records": sum(count - 1 for count in identities.values()),
        "classifications": dict(sorted(classifications.items())),
    }


def write_snapshot(records: list[dict[str, Any]], directory: Path = SNAPSHOT_DIR) -> tuple[Path, str]:
    directory.mkdir(parents=True, exist_ok=True)
    snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    path = directory / f"historical-dlq-{snapshot_id}.json"
    payload = json.dumps(
        {
            "snapshot_id": snapshot_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "policy": "snapshot,classify,ack_terminal_invalid,no_delete,no_replay",
            "summary": summarize(records),
            "records": records,
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ).encode("utf-8")
    with path.open("xb") as file:
        file.write(payload)
    return path, hashlib.sha256(payload).hexdigest()


def _pending_ids(client: Any, stream: str, group: str, message_id: str) -> set[str]:
    if not message_id:
        return set()
    try:
        rows = client.xpending_range(stream, group, min=message_id, max=message_id, count=10)
    except Exception as exc:
        if "NOGROUP" in str(exc):
            return set()
        raise
    return {
        _text(row.get("message_id") if isinstance(row, dict) else row[0])
        for row in (rows or [])
    }


def terminalize_invalid_pending(client: Any, records: list[dict[str, Any]]) -> int:
    """ACK each unique, schema-invalid original only when it is still in PEL."""
    acknowledged = 0
    seen: set[tuple[str, str]] = set()
    for record in records:
        if not record["classification"].startswith("TERMINAL_"):
            continue
        stream = record["original_stream"]
        message_id = record["original_msg_id"]
        identity = (stream, message_id)
        if identity in seen:
            continue
        seen.add(identity)
        group = GROUP_BY_STREAM.get(stream)
        if group and message_id in _pending_ids(client, stream, group, message_id):
            acknowledged += int(client.xack(stream, group, message_id) or 0)
    return acknowledged


def get_client() -> Any:
    from app.Base.Client.redisClient import redis_client

    return redis_client.client


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"apply requires --confirm {APPLY_CONFIRMATION}")

    client = get_client()
    records = read_entries(client)
    summary = summarize(records)
    result: dict[str, Any] = {"mode": "apply" if args.apply else "dry-run", **summary}
    result["safety"] = "no_dlq_delete,no_dlq_trim,no_handler_replay"
    if args.apply:
        path, digest = write_snapshot(records)
        result.update({
            "snapshot_path": str(path.relative_to(ROOT)),
            "snapshot_sha256": digest,
            "terminal_pending_acked": terminalize_invalid_pending(client, records),
        })
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
