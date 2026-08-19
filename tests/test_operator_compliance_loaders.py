"""Operator 合规 Loader 的纯离线测试。"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.WealthButler.Service.operatorComplianceLoaders import (
    HMACVerifiedPayeeLoader,
    ModelComplianceEvidenceLoader,
    ModelHoldingSummaryLoader,
    _is_age_65_plus_from_answers,
)
from app.WealthButler.Service.complianceWriteService import VerifiedPayeeService
from app.WealthButler.Utils.payeeFingerprint import fingerprint, normalize_account, normalize_name


NOW = datetime(2026, 8, 17, 12, 0, 0)
SECRET = "a-test-secret-with-at-least-32-bytes-long"


def test_evidence_loader_accepts_only_latest_issued_unexpired_event():
    records = {
        "RISK_DISCLOSURE_SIGNED": {
            "evidence_type": "RISK_DISCLOSURE_SIGNED",
            "action": "ISSUED",
            "valid_until": NOW + timedelta(days=1),
        },
        "DOUBLE_RECORD_COMPLETED": {
            "evidence_type": "DOUBLE_RECORD_COMPLETED",
            "action": "REVOKED",
            "valid_until": NOW + timedelta(days=1),
        },
    }
    loader = ModelComplianceEvidenceLoader(
        evidence_finder=lambda customer_id, product_id, kind: records.get(kind),
        context_loader=lambda customer_id: {
            "customer_age": 66,
            "has_prior_r3_plus_purchase": False,
        },
        now_provider=lambda: NOW,
    )

    result = loader(1, 2)

    assert result["risk_disclosure_signed"] is True
    assert result["double_record_completed"] is False
    assert result["customer_age"] == 66
    assert result["has_prior_r3_plus_purchase"] is False


def test_evidence_loader_fails_closed_per_evidence_on_read_error_or_expiry():
    def finder(customer_id, product_id, kind):
        if kind == "RISK_DISCLOSURE_SIGNED":
            raise RuntimeError("database unavailable")
        return {"evidence_type": kind, "action": "ISSUED", "valid_until": NOW}

    result = ModelComplianceEvidenceLoader(
        evidence_finder=finder,
        context_loader=lambda customer_id: (_ for _ in ()).throw(RuntimeError("unavailable")),
        now_provider=lambda: NOW,
    )(1, 2)

    assert all(result[name] is False for name in result)


def test_age_context_falls_back_to_latest_assessment_q1_option():
    assert _is_age_65_plus_from_answers([
        {"question_id": "Q1", "option_index": 5},
        {"question_id": "Q2", "option_index": 0},
    ]) is True
    assert _is_age_65_plus_from_answers([
        {"question_id": "Q1", "option_index": 4},
    ]) is False
    assert _is_age_65_plus_from_answers([]) is None


def test_holding_summary_uses_decimal_and_filters_soft_deleted_rows():
    holdings = [
        SimpleNamespace(product_id=1, current_value=Decimal("0.10"), deleted_at=None),
        SimpleNamespace(product_id=2, current_value="0.20", deleted_at=None),
        SimpleNamespace(product_id=1, current_value="99", deleted_at=NOW),
    ]
    products = {
        1: SimpleNamespace(risk_level="R4", status="在售"),
        2: SimpleNamespace(risk_level="R2", status="已下架"),
    }
    result = ModelHoldingSummaryLoader(
        holdings_loader=lambda customer_id: holdings,
        product_loader=lambda product_id: products[product_id],
    )(1, "R4")

    assert result == {"total_value": Decimal("0.30"), "risk_level_value": Decimal("0.10")}


def test_payee_loader_exactly_matches_both_hmacs_and_validity():
    account_hmac = fingerprint(SECRET, "account", 1, normalize_account("62220001"))
    name_hmac = fingerprint(SECRET, "name", 1, normalize_name("张三"))
    record = {
        "account_hmac": account_hmac,
        "payee_name_hmac": name_hmac,
        "status": "VERIFIED",
        "valid_until": NOW + timedelta(minutes=1),
    }
    seen = []
    loader = HMACVerifiedPayeeLoader(
        payee_finder=lambda customer_id, account, name: seen.append((customer_id, account, name)) or record,
        secret_provider=lambda: SECRET,
        now_provider=lambda: NOW,
    )

    assert loader(1, {"account": "62220001", "name": "张三"}) is True
    assert seen == [(1, account_hmac, name_hmac)]
    assert loader(1, {"account": "62220001", "name": "李四"}) is False


def test_payee_loader_fails_closed_without_environment_secret():
    called = False

    def finder(*args):
        nonlocal called
        called = True
        return None

    loader = HMACVerifiedPayeeLoader(payee_finder=finder, secret_provider=lambda: None)

    assert loader(1, {"account": "62220001", "name": "张三"}) is False
    assert called is False


def test_controlled_write_fingerprint_is_accepted_by_operator_loader():
    class MemoryPayee:
        rows = []

        def __init__(self, **values):
            self.__dict__.update(values)
            self.id = len(self.rows) + 1

        def save(self):
            self.rows.append(self)
            return self.id

        @classmethod
        def find_by_fingerprint(cls, customer_id, account_hmac):
            return next(
                (
                    row for row in cls.rows
                    if row.customer_id == customer_id and row.account_hmac == account_hmac
                ),
                None,
            )

    MemoryPayee.rows = []
    valid_until = datetime.now(timezone.utc) + timedelta(days=1)
    VerifiedPayeeService(model_class=MemoryPayee, hmac_key=SECRET).verify(
        customer_id=7,
        account="６２２２-０００１",
        payee_name="  Alice   ZHANG ",
        verification_method="OFFLINE_TEST",
        valid_until=valid_until,
        verified_by=8,
    )
    loader = HMACVerifiedPayeeLoader(
        payee_finder=lambda customer_id, account_hmac, name_hmac: (
            MemoryPayee.find_by_fingerprint(customer_id, account_hmac)
        ),
        secret_provider=lambda: SECRET,
        now_provider=lambda: datetime.now(),
    )

    assert loader(7, {"account": "6222 0001", "name": "alice zhang"}) is True
