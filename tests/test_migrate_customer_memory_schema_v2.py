"""客户长期记忆 v2 无损迁移脚本的离线合同测试。"""

import pytest

from scripts.migrate_customer_memory_schema_v2 import (
    VECTOR_DIM,
    normalize_source_row,
    select_missing,
    values_match,
)


def _legacy_row(source_id="legacy-1"):
    return {
        "id": source_id,
        "customer_id": "42",
        "memory_type": "preference",
        "content": "demo",
        "session_id": "session-1",
        "agent_type": "customer_service",
        "importance": "0.8",
        "created_at": "1786896000",
        "last_accessed_at": "1786896001",
        "access_count": "3",
        "embedding": ["0.0"] * VECTOR_DIM,
    }


def test_normalize_source_row_converts_legacy_varchar_numbers():
    row = normalize_source_row(_legacy_row())
    assert row["source_id"] == "legacy-1"
    assert row["customer_id"] == 42
    assert row["importance"] == pytest.approx(0.8)
    assert row["access_count"] == 3
    assert len(row["embedding"]) == VECTOR_DIM


def test_normalize_source_row_rejects_invalid_vector_dimension():
    legacy = _legacy_row()
    legacy["embedding"] = [0.0]
    with pytest.raises(ValueError, match="embedding dimension mismatch"):
        normalize_source_row(legacy)


def test_select_missing_never_overwrites_existing_source_id():
    rows = [normalize_source_row(_legacy_row("legacy-1")),
            normalize_source_row(_legacy_row("legacy-2"))]
    missing = select_missing(rows, {"legacy-1"})
    assert [row["source_id"] for row in missing] == ["legacy-2"]


def test_values_match_accepts_milvus_float32_precision_only_for_float_field():
    assert values_match("importance", 0.8, 0.800000011920929)
    assert not values_match("importance", 0.8, 0.81)
    assert not values_match("customer_id", 42, "42")
