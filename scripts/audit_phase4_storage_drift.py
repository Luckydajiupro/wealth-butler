"""只读审计 Redis DLQ 与客户长期记忆 Milvus schema；不输出 payload。"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


MEMORY_COLLECTION = "fin_customer_memory_collection"
EXPECTED_MEMORY_FIELDS = {
    "id": ("INT64", None),
    "customer_id": ("INT64", None),
    "memory_type": ("VARCHAR", None),
    "content": ("VARCHAR", None),
    "session_id": ("VARCHAR", None),
    "agent_type": ("VARCHAR", None),
    "importance": ("FLOAT", None),
    "created_at": ("INT64", None),
    "last_accessed_at": ("INT64", None),
    "access_count": ("INT64", None),
    "embedding": ("FLOAT_VECTOR", 1024),
}


def _event_type_from_stream(stream: str) -> str:
    return stream.removeprefix("stream:").removesuffix(":dead_letter")


def audit_redis() -> None:
    from app.Base.Client.redisClient import redis_client
    from app.WealthButler.EventBus.schemas import validate_event
    from pydantic import ValidationError

    client = redis_client.client
    keys = sorted(str(key) for key in client.scan_iter(match="stream:*:dead_letter"))
    print(f"redis_dlq_streams={len(keys)}")
    for key in keys:
        reasons: Counter[str] = Counter()
        field_sets: Counter[str] = Counter()
        event_types: Counter[str] = Counter()
        handlers: Counter[str] = Counter()
        entries = client.xrange(key, min="-", max="+")
        for _message_id, fields in entries:
            field_sets[",".join(sorted(str(name) for name in fields))] += 1
            original_stream = str(fields.get("original_stream") or key.removesuffix(":dead_letter"))
            event_type = str(fields.get("event_type") or _event_type_from_stream(original_stream))
            event_types[event_type or "<empty>"] += 1
            handlers[str(fields.get("handler_name") or "<missing>")] += 1
            payload_text = fields.get("payload", "")
            try:
                payload = json.loads(payload_text)
            except (TypeError, json.JSONDecodeError):
                reasons["INVALID_JSON"] += 1
                continue
            try:
                validate_event(event_type, payload)
            except ValidationError as exc:
                for item in exc.errors():
                    loc = ".".join(str(part) for part in item.get("loc", ()))
                    reasons[f"SCHEMA_{item.get('type', 'invalid')}@{loc}"] += 1
            except ValueError:
                reasons["UNKNOWN_EVENT_TYPE"] += 1
            except Exception as exc:
                reasons[f"SCHEMA_{type(exc).__name__}"] += 1
            else:
                reasons["SCHEMA_VALID_HANDLER_REJECTED"] += 1
        reason_text = ";".join(f"{name}:{count}" for name, count in sorted(reasons.items()))
        fields_text = ";".join(f"{names}:{count}" for names, count in sorted(field_sets.items()))
        types_text = ";".join(f"{name}:{count}" for name, count in sorted(event_types.items()))
        handlers_text = ";".join(f"{name}:{count}" for name, count in sorted(handlers.items()))
        print(
            f"redis_dlq={key}|length={len(entries)}|reasons={reason_text}"
            f"|event_types={types_text}|handlers={handlers_text}|field_sets={fields_text}"
        )


def _dtype_name(value: object) -> str:
    try:
        from pymilvus import DataType

        return DataType(int(value)).name
    except (TypeError, ValueError):
        text = str(value)
        return text.rsplit(".", 1)[-1].upper()


def audit_milvus() -> None:
    from app.Base.Client.milvusClient import MilvusClientSingleton

    client = MilvusClientSingleton().get_client()
    description = client.describe_collection(MEMORY_COLLECTION)
    fields = {str(field["name"]): field for field in description.get("fields", [])}
    print(
        f"milvus_collection={MEMORY_COLLECTION}|auto_id={bool(description.get('auto_id'))}"
        f"|row_count={client.get_collection_stats(MEMORY_COLLECTION).get('row_count', 0)}"
    )
    for name in sorted(fields):
        field = fields[name]
        params = field.get("params") or {}
        dim = params.get("dim")
        print(
            f"milvus_field={name}|type={_dtype_name(field.get('type'))}"
            f"|primary={bool(field.get('is_primary'))}|dim={dim or '-'}"
        )
    drift = []
    for name, (expected_type, expected_dim) in EXPECTED_MEMORY_FIELDS.items():
        actual = fields.get(name)
        if actual is None:
            drift.append(f"missing:{name}")
            continue
        actual_type = _dtype_name(actual.get("type"))
        if expected_type not in actual_type:
            drift.append(f"type:{name}:{actual_type}->{expected_type}")
        actual_dim = int((actual.get("params") or {}).get("dim", 0)) or None
        if expected_dim is not None and actual_dim != expected_dim:
            drift.append(f"dim:{name}:{actual_dim}->{expected_dim}")
    print("milvus_model_drift=" + (";".join(drift) if drift else "NONE"))


def main() -> None:
    audit_redis()
    audit_milvus()


if __name__ == "__main__":
    main()
