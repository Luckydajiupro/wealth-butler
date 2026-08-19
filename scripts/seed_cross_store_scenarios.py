#!/usr/bin/env python
"""Redis + MinIO 跨库演示种子。

默认只做 dry-run；``--apply`` 只写入本脚本拥有的稳定 seed key/object，
不删除、不 flush、不扫描或输出业务值。``--verify`` 只校验种子元数据。

数字主键始终由 MySQL 自然键现查，禁止在脚本中硬编码。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


NAMESPACE = "WB-SEED-20260817"
REDIS_PREFIX = "wb-seed:20260817"
MINIO_PREFIX = "wb-seed/20260817"
MINIO_BUCKET = "fin-compliance-evidence"
STREAM_KEY = "stream:wb-seed:20260817:suspicious_intent"
STREAM_ID = "2026081700000-0"
ACTIVE_SESSION_COUNT = 40
ACTIVE_SESSION_TTL_SECONDS = 1800
SCENARIO_CACHE_TTL_SECONDS = 7 * 24 * 3600

CUSTOMER_KEYS = (
    "wb_seed_c1_elderly",
    "wb_seed_c3_balanced",
    "wb_seed_c4_professional",
    "wb_seed_c5_aggressive",
)
EMPLOYEE_KEYS = ("wb_seed_advisor", "wb_seed_risk", "wb_seed_operator")
PRODUCT_CODES = (
    "WBSEED-R1-CASH",
    "WBSEED-R2-BOND",
    "WBSEED-R3-MIX",
    "WBSEED-R4-EQUITY",
    "WBSEED-R5-PRIVATE",
)


@dataclass(frozen=True)
class EvidenceArtifact:
    stable_key: str
    customer_key: str
    product_code: str
    evidence_type: str

    @property
    def object_name(self) -> str:
        return f"{MINIO_PREFIX}/evidence/{self.stable_key}.json"

    @property
    def uri(self) -> str:
        return f"minio://{MINIO_BUCKET}/{self.object_name}"

    @property
    def body(self) -> bytes:
        payload = {
            "artifact_version": 1,
            "customer_key": self.customer_key,
            "demo_only": True,
            "evidence_type": self.evidence_type,
            "marker": "DEMO_SEED",
            "namespace": NAMESPACE,
            "product_code": self.product_code,
            "stable_evidence_key": self.stable_key,
            "statement": "Project-generated integration evidence; not a real customer signature or recording.",
        }
        return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


ARTIFACTS = (
    EvidenceArtifact(
        "c4-professional-r5-private-risk-disclosure-v1",
        "wb_seed_c4_professional",
        "WBSEED-R5-PRIVATE",
        "RISK_DISCLOSURE_SIGNED",
    ),
    EvidenceArtifact(
        "c4-professional-r5-private-risk-notification-v1",
        "wb_seed_c4_professional",
        "WBSEED-R5-PRIVATE",
        "RISK_NOTIFICATION_ACKNOWLEDGED",
    ),
    EvidenceArtifact(
        "c4-professional-r5-private-double-record-v1",
        "wb_seed_c4_professional",
        "WBSEED-R5-PRIVATE",
        "DOUBLE_RECORD_COMPLETED",
    ),
)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def build_contract(
    user_ids: dict[str, int],
    product_ids: dict[str, int],
    active_customers: list[tuple[str, int]] | None = None,
) -> dict[str, Any]:
    """生成跨库映射；数字 ID 只来自 apply/verify 当时的 MySQL 查询。"""
    return {
        "marker": "DEMO_SEED",
        "namespace": NAMESPACE,
        "customers": {key: user_ids[key] for key in CUSTOMER_KEYS},
        "employees": {key: user_ids[key] for key in EMPLOYEE_KEYS},
        "products": {code: product_ids[code] for code in PRODUCT_CODES},
        "active_sessions": [
            {"customer_key": key, "customer_id": customer_id}
            for key, customer_id in (active_customers or [])
        ],
        "evidence": [
            {
                "stable_key": artifact.stable_key,
                "customer_key": artifact.customer_key,
                "product_code": artifact.product_code,
                "evidence_type": artifact.evidence_type,
                "uri": artifact.uri,
                "sha256": artifact.sha256,
            }
            for artifact in ARTIFACTS
        ],
    }


def resolve_mysql_ids() -> tuple[dict[str, int], dict[str, int], list[tuple[str, int]]]:
    """只读解析种子自然键；任何缺失都阻断跨库写入。"""
    from app.Base.Client.mysqlClient import MySQLClient

    client = MySQLClient()
    user_marks = ",".join(["%s"] * len(CUSTOMER_KEYS + EMPLOYEE_KEYS))
    product_marks = ",".join(["%s"] * len(PRODUCT_CODES))
    users = client.execute_sync(
        f"SELECT id, username FROM base_user WHERE username IN ({user_marks})",
        tuple(CUSTOMER_KEYS + EMPLOYEE_KEYS),
    ) or []
    products = client.execute_sync(
        f"SELECT id, product_code FROM fin_product WHERE product_code IN ({product_marks})",
        PRODUCT_CODES,
    ) or []
    active_rows = client.execute_sync(
        "SELECT id, username FROM base_user "
        "WHERE username LIKE %s AND user_type=%s AND deleted_at IS NULL "
        "AND JSON_UNQUOTE(JSON_EXTRACT(extra_data, '$.seed_namespace'))=%s "
        "ORDER BY username ASC LIMIT %s",
        ("wb_seed_%", "CUSTOMER", NAMESPACE, ACTIVE_SESSION_COUNT),
    ) or []
    user_ids = {str(row["username"]): int(row["id"]) for row in users}
    product_ids = {str(row["product_code"]): int(row["id"]) for row in products}
    missing_users = sorted(set(CUSTOMER_KEYS + EMPLOYEE_KEYS) - set(user_ids))
    missing_products = sorted(set(PRODUCT_CODES) - set(product_ids))
    if missing_users or missing_products:
        raise RuntimeError(
            "MySQL seed contract incomplete: "
            f"missing_users={missing_users}, missing_products={missing_products}"
        )
    active_customers = [
        (str(row["username"]), int(row["id"])) for row in active_rows
    ]
    if len(active_customers) < ACTIVE_SESSION_COUNT:
        raise RuntimeError(
            "MySQL seed contract incomplete: "
            f"active_customers={len(active_customers)}, required={ACTIVE_SESSION_COUNT}"
        )
    return user_ids, product_ids, active_customers


def build_redis_records(contract: dict[str, Any]) -> dict[str, str]:
    """只生成 seed 前缀键，不占用生产 profile/session/payee 键。"""
    c1_id = contract["customers"]["wb_seed_c1_elderly"]
    records = {
        f"{REDIS_PREFIX}:contract": contract,
        f"{REDIS_PREFIX}:customer:wb_seed_c1_elderly:fraud-context": {
            "customer_id": c1_id,
            "customer_key": "wb_seed_c1_elderly",
            "marker": "DEMO_SEED",
            "namespace": NAMESPACE,
            "scenario": "elderly_anti_fraud",
        },
        f"{REDIS_PREFIX}:customer:wb_seed_c1_elderly:verified-payee-context": {
            "customer_id": c1_id,
            "customer_key": "wb_seed_c1_elderly",
            "marker": "DEMO_SEED",
            "namespace": NAMESPACE,
            "payee_stable_key": "WBSEED-PAYEE-FAMILY-01",
            "status": "VERIFIED_REFERENCE_ONLY",
        },
    }
    return {key: _json_bytes(value).decode("utf-8") for key, value in records.items()}


def build_stream_fields(contract: dict[str, Any]) -> dict[str, str]:
    """使用现有 SuspiciousIntentEvent schema 的隔离测试信封。"""
    payload = {
        "customer_id": contract["customers"]["wb_seed_c1_elderly"],
        "session_id": f"{NAMESPACE}-ANTI-FRAUD-01",
        "intent_type": "fraud",
        "confidence": "0.90",
        "suspicious_text": "DEMO_SEED anti-fraud integration envelope",
        "evidence": {
            "marker": "DEMO_SEED",
            "namespace": NAMESPACE,
            "customer_key": "wb_seed_c1_elderly",
            "scenario": "elderly_anti_fraud",
        },
        "detected_at": "2026-08-17 00:00:00",
    }
    # 字段与 EventBus.schemas.SuspiciousIntentEvent 保持一致。此处不直接
    # import EventBus 包，避免 dry-run/单测在预检前初始化全局 Redis 单例。
    return {
        "event_type": "suspicious_intent",
        "payload": json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "timestamp": "1786896000000",
        "trace_id": f"{NAMESPACE}-SUSPICIOUS-INTENT-01",
        "source_agent": "seed_cross_store_scenarios",
    }


def build_active_sessions(contract: dict[str, Any]) -> dict[str, list[str]]:
    """为稳定排序的 40 个种子客户构造低污染、带 TTL 的活跃会话。"""
    sessions: dict[str, list[str]] = {}
    for item in contract.get("active_sessions", []):
        customer_key = str(item["customer_key"])
        session_key = f"{REDIS_PREFIX}:session:{customer_key}:messages"
        sessions[session_key] = [
            json.dumps(
                {
                    "role": "user",
                    "content": "DEMO_SEED 会话活跃状态，不包含真实客户输入。",
                    "customer_id": int(item["customer_id"]),
                    "customer_key": customer_key,
                    "namespace": NAMESPACE,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            json.dumps(
                {
                    "role": "assistant",
                    "content": "DEMO_SEED 联调会话已建立。",
                    "namespace": NAMESPACE,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ]
    return sessions


def _minio_client(endpoint: str | None):
    from minio import Minio
    from app.Base.Config.setting import settings

    return Minio(
        endpoint or os.getenv("WEALTH_BUTLER_SEED_MINIO_ENDPOINT") or settings.minio.endpoint,
        access_key=settings.minio.access_key,
        secret_key=settings.minio.secret_key,
        secure=False,
    )


def preflight(endpoint: str | None) -> tuple[Any, Any, dict[str, Any]]:
    from app.Base.Client.redisClient import RedisClient

    user_ids, product_ids, active_customers = resolve_mysql_ids()
    contract = build_contract(user_ids, product_ids, active_customers)
    redis_client = RedisClient().client
    if not redis_client.ping():
        raise RuntimeError("Redis preflight failed")
    minio_client = _minio_client(endpoint)
    minio_client.list_buckets()
    return redis_client, minio_client, contract


def apply_seed(redis_client, minio_client, contract: dict[str, Any]) -> None:
    for key, value in build_redis_records(contract).items():
        ttl = None if key == f"{REDIS_PREFIX}:contract" else SCENARIO_CACHE_TTL_SECONDS
        redis_client.set(key, value, ex=ttl)

    for key, messages in build_active_sessions(contract).items():
        # 用户已授权同一稳定 seed key 覆盖；事务中只删本 namespace 目标键。
        pipe = redis_client.pipeline(transaction=True)
        pipe.delete(key)
        pipe.rpush(key, *messages)
        pipe.expire(key, ACTIVE_SESSION_TTL_SECONDS)
        pipe.execute()

    fields = build_stream_fields(contract)
    existing = redis_client.xrange(STREAM_KEY, min=STREAM_ID, max=STREAM_ID, count=1)
    if existing:
        if existing[0][1] != fields:
            raise RuntimeError(f"seed stream id {STREAM_ID} exists with different fields")
    else:
        redis_client.xadd(STREAM_KEY, fields, id=STREAM_ID)

    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)
    for artifact in ARTIFACTS:
        body = artifact.body
        minio_client.put_object(
            MINIO_BUCKET,
            artifact.object_name,
            BytesIO(body),
            len(body),
            content_type="application/json",
            metadata={
                "seed-marker": "DEMO_SEED",
                "seed-namespace": NAMESPACE,
                "sha256": artifact.sha256,
                "evidence-type": artifact.evidence_type,
            },
        )


def verify_seed(redis_client, minio_client, contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key, expected in build_redis_records(contract).items():
        if redis_client.get(key) != expected:
            errors.append(f"Redis mismatch: {key}")
            continue
        if key != f"{REDIS_PREFIX}:contract":
            ttl = redis_client.ttl(key)
            if ttl <= 0 or ttl > SCENARIO_CACHE_TTL_SECONDS:
                errors.append(f"Redis scenario cache TTL mismatch: {key}")
    for key, expected_messages in build_active_sessions(contract).items():
        if redis_client.type(key) != "list" or redis_client.lrange(key, 0, -1) != expected_messages:
            errors.append(f"Redis active session mismatch: {key}")
            continue
        ttl = redis_client.ttl(key)
        if ttl <= 0 or ttl > ACTIVE_SESSION_TTL_SECONDS:
            errors.append(f"Redis active session TTL mismatch: {key}")
    fields = build_stream_fields(contract)
    existing = redis_client.xrange(STREAM_KEY, min=STREAM_ID, max=STREAM_ID, count=1)
    if not existing or existing[0][1] != fields:
        errors.append(f"Redis stream mismatch: {STREAM_KEY}/{STREAM_ID}")

    if not minio_client.bucket_exists(MINIO_BUCKET):
        errors.append(f"MinIO bucket missing: {MINIO_BUCKET}")
    else:
        for artifact in ARTIFACTS:
            try:
                stat = minio_client.stat_object(MINIO_BUCKET, artifact.object_name)
            except Exception as exc:
                errors.append(f"MinIO object missing: {artifact.object_name} ({type(exc).__name__})")
                continue
            metadata = {str(k).lower(): str(v) for k, v in (stat.metadata or {}).items()}
            if int(stat.size) != len(artifact.body):
                errors.append(f"MinIO size mismatch: {artifact.object_name}")
            if metadata.get("x-amz-meta-sha256") != artifact.sha256:
                errors.append(f"MinIO sha256 metadata mismatch: {artifact.object_name}")
            if metadata.get("x-amz-meta-seed-marker") != "DEMO_SEED":
                errors.append(f"MinIO marker mismatch: {artifact.object_name}")

    errors.extend(verify_mysql_contract())
    return errors


def verify_mysql_contract() -> list[str]:
    """只读核对 MySQL 证据索引与 MinIO 稳定对象契约。"""
    from app.Base.Client.mysqlClient import MySQLClient

    client = MySQLClient()
    rows = client.execute_sync(
        "SELECT e.evidence_type, e.artifact_uri, e.artifact_sha256, "
        "u.username, p.product_code "
        "FROM biz_compliance_evidence e "
        "JOIN base_user u ON u.id=e.customer_id "
        "JOIN fin_product p ON p.id=e.product_id "
        "WHERE e.event_id LIKE %s AND e.action=%s",
        (NAMESPACE + ":evidence:%", "ISSUED"),
    ) or []
    actual = {
        str(row["evidence_type"]): (
            str(row["artifact_uri"]),
            str(row["artifact_sha256"]),
            str(row["username"]),
            str(row["product_code"]),
        )
        for row in rows
    }
    expected = {
        artifact.evidence_type: (
            artifact.uri,
            artifact.sha256,
            artifact.customer_key,
            artifact.product_code,
        )
        for artifact in ARTIFACTS
    }
    errors: list[str] = []
    if actual != expected:
        errors.append("MySQL compliance evidence contract mismatch")

    payee_rows = client.execute_sync(
        "SELECT COUNT(*) AS count FROM fin_verified_payee v "
        "JOIN base_user u ON u.id=v.customer_id "
        "WHERE u.username=%s AND v.trace_id LIKE %s AND v.status=%s",
        ("wb_seed_c1_elderly", NAMESPACE + ":payee:%", "VERIFIED"),
    ) or []
    payee_count = int(payee_rows[0]["count"]) if payee_rows else 0
    if payee_count < 1:
        errors.append("MySQL elderly verified-payee seed missing")
    return errors


def print_contract(contract: dict[str, Any], mode: str) -> None:
    """仅输出自然键映射、seed URI/SHA 和操作数，不输出凭证/业务值。"""
    print(f"mode={mode}")
    print(f"namespace={NAMESPACE}")
    print(f"mysql_customers_resolved={len(contract['customers'])}")
    print(f"mysql_employees_resolved={len(contract['employees'])}")
    print(f"mysql_products_resolved={len(contract['products'])}")
    print(f"redis_seed_key_count={len(build_redis_records(contract))}")
    print(f"redis_active_session_count={len(build_active_sessions(contract))}")
    print(f"redis_seed_stream={STREAM_KEY}")
    for artifact in ARTIFACTS:
        print(
            "evidence_contract="
            f"{artifact.customer_key}|{artifact.product_code}|{artifact.evidence_type}|"
            f"{artifact.uri}|{artifact.sha256}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--apply", action="store_true", help="写入本 namespace 的稳定 seed 记录")
    modes.add_argument("--verify", action="store_true", help="只读校验已写入的 seed 记录")
    parser.add_argument("--minio-endpoint", help="MinIO S3 API endpoint（不含协议）")
    args = parser.parse_args()
    mode = "apply" if args.apply else "verify" if args.verify else "dry-run"

    redis_client, minio_client, contract = preflight(args.minio_endpoint)
    print_contract(contract, mode)
    if mode == "dry-run":
        print("status=DRY_RUN_OK")
        return 0
    if mode == "apply":
        apply_seed(redis_client, minio_client, contract)
    errors = verify_seed(redis_client, minio_client, contract)
    if errors:
        for error in errors:
            print(f"verification_error={error}")
        print("status=VERIFY_FAILED")
        return 1
    print("status=VERIFY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
