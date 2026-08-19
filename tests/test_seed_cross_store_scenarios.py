"""跨库种子契约纯函数测试（不连接 Redis/MinIO/MySQL）。"""

import json

from scripts.seed_cross_store_scenarios import (
    ARTIFACTS,
    CUSTOMER_KEYS,
    EMPLOYEE_KEYS,
    MINIO_PREFIX,
    NAMESPACE,
    PRODUCT_CODES,
    REDIS_PREFIX,
    STREAM_KEY,
    build_active_sessions,
    build_contract,
    build_redis_records,
    build_stream_fields,
)


def _contract():
    user_ids = {
        key: index + 1 for index, key in enumerate(CUSTOMER_KEYS + EMPLOYEE_KEYS)
    }
    product_ids = {code: index + 101 for index, code in enumerate(PRODUCT_CODES)}
    active = [(f"wb_seed_bulk_customer_{index:03d}", index + 1000) for index in range(40)]
    return build_contract(user_ids, product_ids, active)


def test_contract_uses_stable_natural_keys_and_deterministic_artifacts():
    first = _contract()
    second = _contract()
    assert first == second
    assert first["namespace"] == NAMESPACE
    assert len(ARTIFACTS) == 3
    for artifact in ARTIFACTS:
        assert artifact.object_name.startswith(f"{MINIO_PREFIX}/")
        assert artifact.uri.startswith("minio://fin-compliance-evidence/")
        assert len(artifact.sha256) == 64
        payload = json.loads(artifact.body)
        assert payload["marker"] == "DEMO_SEED"
        assert payload["demo_only"] is True
        assert "not a real customer signature" in payload["statement"]


def test_redis_records_are_isolated_under_seed_namespace():
    records = build_redis_records(_contract())
    assert records
    assert all(key.startswith(f"{REDIS_PREFIX}:") for key in records)
    assert STREAM_KEY == "stream:wb-seed:20260817:suspicious_intent"
    sessions = build_active_sessions(_contract())
    assert len(sessions) == 40
    assert all(key.startswith(f"{REDIS_PREFIX}:session:") for key in sessions)
    assert all(len(messages) == 2 for messages in sessions.values())


def test_seed_stream_payload_conforms_to_current_event_contract():
    fields = build_stream_fields(_contract())
    payload = json.loads(fields["payload"])
    assert fields["event_type"] == "suspicious_intent"
    assert fields["trace_id"].startswith(NAMESPACE)
    assert payload["intent_type"] == "fraud"
    assert payload["evidence"]["marker"] == "DEMO_SEED"
