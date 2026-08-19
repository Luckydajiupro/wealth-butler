"""合规受控写入的业务、RBAC 与敏感信息回归测试。"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.WealthButler.Api import complianceWriteApi
from app.WealthButler.Api.complianceWriteApi import (
    EvidenceIssueRequest,
    PayeeVerifyRequest,
    get_compliance_writer,
    register_compliance_write_api,
    router,
)
from app.WealthButler.Service.complianceWriteService import (
    ComplianceEvidenceService,
    ControlledWriteError,
    VerifiedPayeeService,
)
from app.WealthButler.Service.operatorComplianceLoaders import HMACVerifiedPayeeLoader


class FakeEvidenceModel:
    records = []

    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)

    def save(self):
        self.__class__.records.append(self)
        return len(self.__class__.records)

    @classmethod
    def find_latest_by_evidence_id(cls, evidence_id):
        return next(
            (item for item in reversed(cls.records) if item.evidence_id == evidence_id),
            None,
        )


class FakePayeeModel:
    records = {}

    def __init__(self, **values):
        self.id = values.pop("id", None)
        for key, value in values.items():
            setattr(self, key, value)

    def save(self):
        self.id = len(self.__class__.records) + 1
        self.__class__.records[self.id] = self
        return self.id

    def update(self, **values):
        for key, value in values.items():
            setattr(self, key, value)
        return True

    @classmethod
    def find_by_fingerprint(cls, customer_id, account_hmac):
        return next((
            item for item in cls.records.values()
            if item.customer_id == customer_id and item.account_hmac == account_hmac
        ), None)

    @classmethod
    def get_by_id(cls, payee_id):
        return cls.records.get(payee_id)


@pytest.fixture(autouse=True)
def reset_fake_models():
    FakeEvidenceModel.records = []
    FakePayeeModel.records = {}


def _times():
    completed = datetime.now()
    return completed, completed + timedelta(days=30)


def test_evidence_issue_stores_only_minio_reference_and_digest():
    completed, valid_until = _times()
    service = ComplianceEvidenceService(FakeEvidenceModel)

    result = service.issue(
        customer_id=7,
        product_id=9,
        evidence_type="RISK_DISCLOSURE_SIGNED",
        artifact_uri="minio://compliance-evidence/customer-7/disclosure.pdf",
        artifact_sha256="a" * 64,
        completed_at=completed,
        valid_until=valid_until,
        verification_method="OFFLINE_REVIEW",
        verified_by=42,
    )

    stored = FakeEvidenceModel.records[0]
    assert stored.action == "ISSUED"
    assert stored.artifact_uri.startswith("minio://")
    assert stored.artifact_sha256 == "a" * 64
    assert result["verified_by"] == 42
    assert not hasattr(stored, "artifact_content")


def test_evidence_revoke_appends_event_without_mutating_issue():
    completed, valid_until = _times()
    service = ComplianceEvidenceService(FakeEvidenceModel)
    issued = service.issue(
        customer_id=7,
        product_id=9,
        evidence_type="DOUBLE_RECORD_COMPLETED",
        artifact_uri="minio://compliance-evidence/customer-7/double-recording.mp4",
        artifact_sha256="b" * 64,
        completed_at=completed,
        valid_until=valid_until,
        verification_method="VIDEO_REVIEW",
        verified_by=10,
    )

    revoked = service.revoke(
        evidence_id=issued["evidence_id"],
        reason="客户撤回授权",
        verified_by=42,
    )

    assert len(FakeEvidenceModel.records) == 2
    assert FakeEvidenceModel.records[0].action == "ISSUED"
    assert FakeEvidenceModel.records[0].verified_by == 10
    assert FakeEvidenceModel.records[1].action == "REVOKED"
    assert revoked["verified_by"] == 42


def test_evidence_rejects_non_minio_or_invalid_digest():
    completed, valid_until = _times()
    service = ComplianceEvidenceService(FakeEvidenceModel)
    with pytest.raises(ControlledWriteError, match="MinIO"):
        service.issue(
            customer_id=7,
            product_id=9,
            evidence_type="RISK_DISCLOSURE_SIGNED",
            artifact_uri="raw evidence contents",
            artifact_sha256="a" * 64,
            completed_at=completed,
            valid_until=valid_until,
            verification_method="OFFLINE_REVIEW",
            verified_by=42,
        )

    with pytest.raises(ControlledWriteError) as unsupported:
        service.issue(
            customer_id=7,
            product_id=9,
            evidence_type="RISK_DISCLOSURE",
            artifact_uri="minio://compliance-evidence/customer-7/disclosure.pdf",
            artifact_sha256="a" * 64,
            completed_at=completed,
            valid_until=valid_until,
            verification_method="OFFLINE_REVIEW",
            verified_by=42,
        )
    assert unsupported.value.code == "UNSUPPORTED_EVIDENCE_TYPE"


def test_payee_hmac_is_fail_closed_and_public_result_contains_only_last4():
    with pytest.raises(ControlledWriteError) as missing:
        VerifiedPayeeService(FakePayeeModel, environ={})
    assert missing.value.code == "HMAC_KEY_UNAVAILABLE"

    service = VerifiedPayeeService(FakePayeeModel, hmac_key="k" * 32)
    result = service.verify(
        customer_id=7,
        account="6222-0000 1234 5678",
        payee_name="张 三",
        verification_method="BANK_CALLBACK",
        valid_until=datetime.now() + timedelta(days=30),
        verified_by=42,
    )

    stored = FakePayeeModel.records[result["id"]]
    assert result["account_last4"] == "5678"
    assert "account_hmac" not in result
    assert "payee_name_hmac" not in result
    assert "account" not in result
    assert "payee_name" not in result
    assert stored.account_hmac != "6222000012345678"
    assert stored.payee_name_hmac != "张 三"
    assert not hasattr(stored, "account")
    assert not hasattr(stored, "payee_name")


def test_payee_name_mismatch_is_rejected_and_revoke_never_returns_hmac():
    service = VerifiedPayeeService(FakePayeeModel, hmac_key="k" * 32)
    verified = service.verify(
        customer_id=7,
        account="6222000012345678",
        payee_name="张三",
        verification_method="BANK_CALLBACK",
        valid_until=datetime.now() + timedelta(days=30),
        verified_by=42,
    )
    with pytest.raises(ControlledWriteError) as mismatch:
        service.verify(
            customer_id=7,
            account="6222000012345678",
            payee_name="李四",
            verification_method="BANK_CALLBACK",
            valid_until=datetime.now() + timedelta(days=30),
            verified_by=42,
        )
    assert mismatch.value.code == "PAYEE_NAME_MISMATCH"

    revoked = service.revoke(payee_id=verified["id"], verified_by=99)
    assert revoked["status"] == "REVOKED"
    assert revoked["verified_by"] == 99
    assert all("hmac" not in key for key in revoked)


def test_payee_written_by_service_is_accepted_by_runtime_loader():
    secret = "a-test-secret-with-at-least-32-bytes-long"
    service = VerifiedPayeeService(FakePayeeModel, hmac_key=secret)
    result = service.verify(
        customer_id=7,
        account="６２２２-0000 1234 5678",
        payee_name=" 张   三 ",
        verification_method="BANK_CALLBACK",
        valid_until=datetime.now() + timedelta(days=30),
        verified_by=42,
    )
    stored = FakePayeeModel.records[result["id"]]
    loader = HMACVerifiedPayeeLoader(
        payee_finder=lambda customer_id, account_hmac, name_hmac: stored,
        secret_provider=lambda: secret,
        now_provider=datetime.now,
    )

    assert loader(7, {"account": "6222000012345678", "name": "张 三"}) is True


def test_rbac_rejects_customer_and_employee_without_risk_override(monkeypatch):
    monkeypatch.setattr(
        complianceWriteApi.AuthService,
        "has_permission",
        lambda *args, **kwargs: True,
    )
    with pytest.raises(HTTPException) as customer_error:
        get_compliance_writer(SimpleNamespace(id=1, user_type="CUSTOMER", source_module="fin"))
    assert customer_error.value.status_code == 403

    monkeypatch.setattr(
        complianceWriteApi.AuthService,
        "has_permission",
        lambda *args, **kwargs: False,
    )
    with pytest.raises(HTTPException) as employee_error:
        get_compliance_writer(SimpleNamespace(id=2, user_type="EMPLOYEE", source_module="fin"))
    assert employee_error.value.status_code == 403


def test_request_rejects_client_supplied_identity_and_api_uses_jwt_user(monkeypatch):
    completed, valid_until = _times()
    with pytest.raises(ValidationError):
        EvidenceIssueRequest(
            customer_id=7,
            product_id=9,
            evidence_type="RISK_DISCLOSURE_SIGNED",
            artifact_uri="minio://compliance-evidence/customer-7/disclosure.pdf",
            artifact_sha256="a" * 64,
            completed_at=completed,
            valid_until=valid_until,
            verification_method="OFFLINE_REVIEW",
            verified_by=999,
        )

    captured = {}

    class StubService:
        def issue(self, **kwargs):
            captured.update(kwargs)
            return {"evidence_id": "e-1"}

    monkeypatch.setattr(complianceWriteApi, "ComplianceEvidenceService", StubService)
    request = EvidenceIssueRequest(
        customer_id=7,
        product_id=9,
        evidence_type="RISK_DISCLOSURE_SIGNED",
        artifact_uri="minio://compliance-evidence/customer-7/disclosure.pdf",
        artifact_sha256="a" * 64,
        completed_at=completed,
        valid_until=valid_until,
        verification_method="OFFLINE_REVIEW",
    )
    response = complianceWriteApi.issue_evidence(
        request,
        current_user=SimpleNamespace(id=42),
    )
    assert response.data == {"evidence_id": "e-1"}
    assert captured["verified_by"] == 42


def test_routes_are_registered_on_business_api_router():
    app = FastAPI()
    register_compliance_write_api(app)
    paths = {route.path for route in router.routes}
    assert "/api/compliance/evidence" in paths
    assert "/api/compliance/evidence/{evidence_id}/revoke" in paths
    assert "/api/compliance/payees/verify" in paths
    assert "/api/compliance/payees/{payee_id}/revoke" in paths


def test_api_requires_jwt_and_enforces_risk_override(monkeypatch):
    app = FastAPI()
    register_compliance_write_api(app)
    payload = {
        "customer_id": 7,
        "account": "6222000012345678",
        "payee_name": "张三",
        "verification_method": "BANK_CALLBACK",
        "valid_until": (datetime.now() + timedelta(days=30)).isoformat(),
    }
    with TestClient(app) as client:
        unauthenticated = client.post("/api/compliance/payees/verify", json=payload)
        assert unauthenticated.status_code == 401

        app.dependency_overrides[
            complianceWriteApi.get_authenticated_employee
        ] = lambda: SimpleNamespace(id=2, user_type="EMPLOYEE", source_module="fin")
        monkeypatch.setattr(
            complianceWriteApi.AuthService,
            "has_permission",
            lambda *args, **kwargs: False,
        )
        denied = client.post("/api/compliance/payees/verify", json=payload)
        assert denied.status_code == 403
        assert "risk:override" in denied.json()["detail"]
