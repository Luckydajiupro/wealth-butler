"""合规证据与收款方指纹 Model 的离线合同测试。"""

import json
import re
from datetime import datetime

from app.Base.Repository.base.baseDBModel import BaseDBModel
from app.WealthButler.Models.complianceEvidenceModel import ComplianceEvidenceModel
from app.WealthButler.Models.verifiedPayeeModel import VerifiedPayeeModel


def _column_names(create_sql):
    return set(re.findall(r"^\s+`([a-z][a-z0-9_]*)`\s+", create_sql, flags=re.MULTILINE))


def test_models_follow_base_model_and_fixed_table_contracts():
    assert issubclass(ComplianceEvidenceModel, BaseDBModel)
    assert issubclass(VerifiedPayeeModel, BaseDBModel)
    assert ComplianceEvidenceModel.table_alias == "biz_compliance_evidence"
    assert VerifiedPayeeModel.table_alias == "fin_verified_payee"

    evidence_columns = _column_names(ComplianceEvidenceModel.create_table_sql)
    assert {"event_id", "evidence_id", "action", "artifact_uri", "artifact_sha256", "metadata"} <= evidence_columns
    assert "updated_at" not in evidence_columns
    assert "ENUM('ISSUED','REVOKED')" in ComplianceEvidenceModel.create_table_sql


def test_payee_schema_contains_only_hmac_fingerprints_not_plaintext_identity():
    columns = _column_names(VerifiedPayeeModel.create_table_sql)
    assert {"account_hmac", "account_last4", "payee_name_hmac"} <= columns
    assert {"account", "account_number", "payee_name", "counterparty_account"}.isdisjoint(columns)
    assert "UNIQUE KEY `uk_verified_payee_customer_account`" in VerifiedPayeeModel.create_table_sql
    assert "ENUM('PENDING','VERIFIED','REJECTED','EXPIRED','REVOKED')" in VerifiedPayeeModel.create_table_sql


def test_payee_name_fingerprint_requires_exact_constant_time_match():
    payee = VerifiedPayeeModel(
        customer_id=1,
        account_hmac="a" * 64,
        account_last4="1234",
        payee_name_hmac="b" * 64,
        verification_method="BANK_CALLBACK",
        status="VERIFIED",
        trace_id="trace-1",
    )
    assert payee.matches_payee_name_hmac("b" * 64) is True
    assert payee.matches_payee_name_hmac("c" * 64) is False


class _DatabaseStub:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return [self.row]


def test_evidence_latest_lookup_uses_append_id_not_business_timestamp(monkeypatch):
    row = {
        "id": 2,
        "event_id": "event-revoke",
        "evidence_id": "evidence-1",
        "action": "REVOKED",
        "customer_id": 1,
        "product_id": 2,
        "evidence_type": "DOUBLE_RECORDING",
        "completed_at": datetime(2025, 1, 1),
        "verified_by": 9,
        "verification_method": "MANUAL_REVIEW",
        "trace_id": "trace-2",
    }
    database = _DatabaseStub(row)
    monkeypatch.setattr(ComplianceEvidenceModel, "_ensure_table_exists", classmethod(lambda cls: None))
    monkeypatch.setattr(ComplianceEvidenceModel, "get_db_connection", classmethod(lambda cls: database))

    result = ComplianceEvidenceModel.find_latest_by_evidence_id("evidence-1")

    assert result.action == "REVOKED"
    sql, params = database.calls[0]
    assert "ORDER BY `id` DESC" in sql
    assert "ORDER BY `completed_at`" not in sql
    assert params == ("evidence-1",)


def test_evidence_metadata_serializes_for_database_and_deserializes_on_read():
    metadata = {"source": "双录", "checks": ["identity", "risk"]}
    fields = {
        "event_id": "event-issued",
        "evidence_id": "evidence-2",
        "action": "ISSUED",
        "customer_id": 1,
        "evidence_type": "DOUBLE_RECORDING",
        "completed_at": datetime(2026, 8, 17, 12, 0),
        "verified_by": 9,
        "verification_method": "MANUAL_REVIEW",
        "trace_id": "trace-3",
    }

    evidence = ComplianceEvidenceModel(**fields, metadata=metadata)
    dumped = evidence.model_dump()

    assert evidence.metadata == metadata
    assert isinstance(evidence.metadata, dict)
    assert isinstance(dumped["metadata"], str)
    assert json.loads(dumped["metadata"]) == metadata

    loaded = ComplianceEvidenceModel(**fields, metadata=dumped["metadata"])
    assert loaded.metadata == metadata
    assert isinstance(loaded.metadata, dict)
