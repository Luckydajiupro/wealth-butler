"""客户长期记忆集合无损并行迁移。

默认 dry-run；不会 drop/rename/覆盖源集合。apply 只创建独立 v2 集合并按 source_id
追加缺失记录，verify 只读核对 schema 与源记录覆盖率。
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SOURCE_COLLECTION = "fin_customer_memory_collection"
TARGET_COLLECTION = "fin_customer_memory_collection_v2"
APPLY_CONFIRMATION = "CREATE_MEMORY_V2_NO_DROP"
VECTOR_DIM = 1024
QUERY_LIMIT = 16384

TARGET_FIELDS = {
    "id": "INT64",
    "source_id": "VARCHAR",
    "customer_id": "INT64",
    "memory_type": "VARCHAR",
    "content": "VARCHAR",
    "session_id": "VARCHAR",
    "agent_type": "VARCHAR",
    "importance": "FLOAT",
    "created_at": "INT64",
    "last_accessed_at": "INT64",
    "access_count": "INT64",
    "embedding": "FLOAT_VECTOR",
}


def _dtype_name(value: object) -> str:
    from pymilvus import DataType

    try:
        return DataType(int(value)).name
    except (TypeError, ValueError):
        return str(value).rsplit(".", 1)[-1].upper()


def normalize_source_row(row: dict[str, Any]) -> dict[str, Any]:
    """把旧集合 VARCHAR 数值安全转换为 v2 强类型，错误直接阻断。"""
    normalized = {
        "source_id": str(row["id"]),
        "customer_id": int(row["customer_id"]),
        "memory_type": str(row.get("memory_type") or ""),
        "content": str(row.get("content") or ""),
        "session_id": str(row.get("session_id") or ""),
        "agent_type": str(row.get("agent_type") or ""),
        "importance": float(row.get("importance") or 0),
        "created_at": int(row.get("created_at") or 0),
        "last_accessed_at": int(row.get("last_accessed_at") or 0),
        "access_count": int(row.get("access_count") or 0),
        "embedding": [float(value) for value in row["embedding"]],
    }
    limits = {"source_id": 128, "memory_type": 50, "content": 2000,
              "session_id": 64, "agent_type": 50}
    for name, maximum in limits.items():
        if len(normalized[name]) > maximum:
            raise ValueError(f"field too long: {name}")
    if normalized["customer_id"] <= 0:
        raise ValueError("customer_id must be positive")
    if len(normalized["embedding"]) != VECTOR_DIM:
        raise ValueError("embedding dimension mismatch")
    return normalized


def select_missing(rows: Iterable[dict[str, Any]], existing_ids: set[str]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row["source_id"]) not in existing_ids]


def values_match(field: str, source: Any, target: Any) -> bool:
    """Milvus FLOAT 以 float32 存储，校验时允许其正常精度差。"""
    if field == "importance":
        try:
            return math.isclose(float(source), float(target), rel_tol=1e-6, abs_tol=1e-7)
        except (TypeError, ValueError):
            return False
    return source == target


def get_client():
    from app.Base.Client.milvusClient import MilvusClientSingleton

    return MilvusClientSingleton().get_client()


def describe_fields(client: Any, collection: str) -> tuple[dict[str, dict[str, Any]], bool]:
    description = client.describe_collection(collection)
    return (
        {str(field["name"]): field for field in description.get("fields", [])},
        bool(description.get("auto_id")),
    )


def validate_target_schema(client: Any) -> list[str]:
    if not client.has_collection(TARGET_COLLECTION):
        return ["target collection missing"]
    fields, auto_id = describe_fields(client, TARGET_COLLECTION)
    errors = []
    if not auto_id:
        errors.append("target auto_id must be true")
    for name, expected_type in TARGET_FIELDS.items():
        field = fields.get(name)
        if field is None:
            errors.append(f"target field missing: {name}")
            continue
        actual_type = _dtype_name(field.get("type"))
        if actual_type != expected_type:
            errors.append(f"target type mismatch: {name}:{actual_type}->{expected_type}")
    embedding = fields.get("embedding") or {}
    dim = int((embedding.get("params") or {}).get("dim", 0))
    if dim != VECTOR_DIM:
        errors.append(f"target embedding dim mismatch: {dim}->{VECTOR_DIM}")
    return errors


def load_source_rows(client: Any) -> list[dict[str, Any]]:
    if not client.has_collection(SOURCE_COLLECTION):
        raise RuntimeError("source collection missing")
    fields, _auto_id = describe_fields(client, SOURCE_COLLECTION)
    required = set(TARGET_FIELDS) - {"source_id"}
    if not required.issubset(fields):
        raise RuntimeError(f"source fields missing: {sorted(required - set(fields))}")
    rows = client.query(
        collection_name=SOURCE_COLLECTION,
        filter='id != ""',
        output_fields=sorted(required),
        limit=QUERY_LIMIT,
    )
    return [normalize_source_row(dict(row)) for row in (rows or [])]


def load_target_rows(client: Any) -> list[dict[str, Any]]:
    if not client.has_collection(TARGET_COLLECTION):
        return []
    return list(client.query(
        collection_name=TARGET_COLLECTION,
        filter='source_id != ""',
        output_fields=[name for name in TARGET_FIELDS if name not in {"id", "embedding"}],
        limit=QUERY_LIMIT,
    ) or [])


def create_target(client: Any) -> None:
    """仅创建并行目标集合；绝不删除、重命名或覆盖源集合。"""
    from pymilvus import DataType

    schema = client.create_schema(auto_id=True, enable_dynamic_field=False)
    schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
    schema.add_field("source_id", DataType.VARCHAR, max_length=128)
    schema.add_field("customer_id", DataType.INT64)
    schema.add_field("memory_type", DataType.VARCHAR, max_length=50)
    schema.add_field("content", DataType.VARCHAR, max_length=2000)
    schema.add_field("session_id", DataType.VARCHAR, max_length=64)
    schema.add_field("agent_type", DataType.VARCHAR, max_length=50)
    schema.add_field("importance", DataType.FLOAT)
    schema.add_field("created_at", DataType.INT64)
    schema.add_field("last_accessed_at", DataType.INT64)
    schema.add_field("access_count", DataType.INT64)
    schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=VECTOR_DIM)
    indexes = client.prepare_index_params()
    indexes.add_index(
        field_name="embedding", index_name="embedding_hnsw",
        index_type="HNSW", metric_type="COSINE",
        params={"M": 16, "efConstruction": 200},
    )
    client.create_collection(
        collection_name=TARGET_COLLECTION, schema=schema, index_params=indexes,
    )


def verify(client: Any, source_rows: list[dict[str, Any]]) -> list[str]:
    errors = validate_target_schema(client)
    if errors:
        return errors
    target_rows = load_target_rows(client)
    source_by_id = {row["source_id"]: row for row in source_rows}
    target_by_id = {str(row["source_id"]): row for row in target_rows}
    missing = sorted(set(source_by_id) - set(target_by_id))
    if missing:
        errors.append(f"target source coverage missing: {len(missing)}")
    comparable = [name for name in TARGET_FIELDS if name not in {"id", "embedding", "source_id"}]
    mismatches = 0
    for source_id in set(source_by_id) & set(target_by_id):
        source = source_by_id[source_id]
        target = target_by_id[source_id]
        if any(not values_match(name, source[name], target.get(name)) for name in comparable):
            mismatches += 1
    if mismatches:
        errors.append(f"target row value mismatches: {mismatches}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--verify", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    mode = "apply" if args.apply else "verify" if args.verify else "dry-run"
    if mode == "apply" and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"apply requires --confirm {APPLY_CONFIRMATION}")

    client = get_client()
    source_rows = load_source_rows(client)
    target_exists = client.has_collection(TARGET_COLLECTION)
    target_rows = load_target_rows(client) if target_exists else []
    existing_ids = {str(row["source_id"]) for row in target_rows}
    missing = select_missing(source_rows, existing_ids)
    print(f"mode={mode}")
    print(f"source_collection={SOURCE_COLLECTION}|rows={len(source_rows)}")
    print(f"target_collection={TARGET_COLLECTION}|exists={str(target_exists).lower()}")
    print(f"would_copy={len(missing)}")
    print("safety=no_drop,no_rename,no_overwrite")

    if mode == "dry-run":
        print("status=DRY_RUN_OK")
        return 0
    if mode == "apply":
        if not target_exists:
            create_target(client)
        schema_errors = validate_target_schema(client)
        if schema_errors:
            for error in schema_errors:
                print(f"verification_error={error}")
            print("status=VERIFY_FAILED")
            return 1
        if missing:
            client.insert(collection_name=TARGET_COLLECTION, data=missing)
    errors = verify(client, source_rows)
    if errors:
        for error in errors:
            print(f"verification_error={error}")
        print("status=VERIFY_FAILED")
        return 1
    print("status=VERIFY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
