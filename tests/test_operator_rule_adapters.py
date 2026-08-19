"""Operator 真实规则 Adapter 的隔离回归测试。"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.WealthButler.Service.operatorContracts import OperationCommand
from app.WealthButler.Service.operatorRuleAdapters import (
    ModelOperationRiskGateway,
    ModelPurchaseComplianceGateway,
    ModelSuitabilityGateway,
)


NOW = datetime(2026, 8, 17, 12, 0, 0)


def _assessment(level="C3", *, valid=True, professional=False):
    return {
        "risk_level": level,
        "valid_until": NOW + timedelta(days=30) if valid else NOW - timedelta(seconds=1),
        "is_professional_investor": professional,
    }


def _product(level="R3", product_id=10):
    return {"id": product_id, "risk_level": level, "product_type": "公募基金"}


def _suitability(*, assessment=None, profile=None, product=None):
    assessment_value = _assessment() if assessment is None else assessment
    profile_value = {"fm_flags": []} if profile is None else profile
    product_value = _product() if product is None else product
    return ModelSuitabilityGateway(
        assessment_loader=lambda customer_id: assessment_value,
        profile_loader=lambda customer_id: profile_value,
        product_loader=lambda product_id: product_value,
        now_provider=lambda: NOW,
    )


def test_suitability_allows_matching_risk_level():
    result = _suitability().check(1, 10)

    assert result["passed"] is True
    assert result["action"] == "allow"
    assert result["required_controls"] == []


def test_suitability_returns_disclosure_path_for_c3_r4():
    result = _suitability(
        assessment=_assessment("C3"), product=_product("R4")
    ).check(1, 10)

    assert result["passed"] is True
    assert result["action"] == "disclosure"
    assert result["requires_disclosure"] is True
    assert result["exemption_used"] is False
    assert "risk_disclosure_signed" in result["required_controls"]


def test_suitability_forbids_c1_r4():
    result = _suitability(
        assessment=_assessment("C1"), product=_product("R4")
    ).check(1, 10)

    assert result["passed"] is False
    assert result["action"] == "forbidden"
    assert "不得购买" in result["reason"]


def test_suitability_professional_exemption_still_requires_disclosure():
    result = _suitability(
        assessment=_assessment("C1", professional=True), product=_product("R5")
    ).check(1, 10)

    assert result["passed"] is True
    assert result["action"] == "disclosure"
    assert result["exemption_used"] is True
    assert set(result["required_controls"]) >= {
        "risk_disclosure_signed",
        "risk_notification_acknowledged",
    }


def test_suitability_fails_closed_when_profile_missing():
    gateway = ModelSuitabilityGateway(
        assessment_loader=lambda customer_id: _assessment(),
        profile_loader=lambda customer_id: None,
        product_loader=lambda product_id: _product(),
        now_provider=lambda: NOW,
    )

    result = gateway.check(1, 10)

    assert result["passed"] is False
    assert "画像缺失" in result["reason"]


def test_suitability_fails_closed_when_assessment_expired():
    result = _suitability(assessment=_assessment(valid=False)).check(1, 10)

    assert result["passed"] is False
    assert "已过期" in result["reason"]
    assert result["fm_hits"] == [{"code": "FM-03", "level": "block"}]


def test_suitability_exposes_structured_fm02_position_limit():
    result = _suitability(
        profile={"fm_flags": ["FM-02-仅允许R1-R3且R3≤30%"]}
    ).check(1, 10)

    fm02 = next(hit for hit in result["fm_hits"] if hit["code"] == "FM-02")
    assert result["passed"] is True
    assert fm02["constraints"]["max_r3_position_pct"] == "0.30"


def test_purchase_compliance_requires_disclosure_evidence():
    suitability = _suitability(
        assessment=_assessment("C3"), product=_product("R4")
    )
    gateway = ModelPurchaseComplianceGateway(
        suitability_gateway=suitability,
        evidence_loader=lambda customer_id, product_id: {},
        holding_summary_loader=lambda customer_id, risk_level: {
            "total_value": "1000000",
            "risk_level_value": "0",
        },
    )

    reason = gateway.validate_purchase(
        1, _product("R4"), OperationCommand("purchase", {"amount": "100000"})
    )

    assert reason is not None
    assert "risk_disclosure_signed" in reason


def test_purchase_compliance_enforces_disclosure_position_cap():
    suitability = _suitability(
        assessment=_assessment("C3"), product=_product("R4")
    )
    gateway = ModelPurchaseComplianceGateway(
        suitability_gateway=suitability,
        evidence_loader=lambda customer_id, product_id: {
            "risk_disclosure_signed": True,
            "double_record_completed": True,
            "customer_age": 30,
            "has_prior_r3_plus_purchase": True,
        },
        holding_summary_loader=lambda customer_id, risk_level: {
            "total_value": "1000000",
            "risk_level_value": "190000",
        },
    )

    reason = gateway.validate_purchase(
        1, _product("R4"), OperationCommand("purchase", {"amount": "100000"})
    )

    assert reason == "申购后R4持仓将超过总资产20%上限"


def test_purchase_over_500k_requires_double_record():
    gateway = ModelPurchaseComplianceGateway(
        suitability_gateway=_suitability(),
        evidence_loader=lambda customer_id, product_id: {},
    )

    reason = gateway.validate_purchase(
        1, _product(), OperationCommand("purchase", {"amount": "500000.01"})
    )

    assert reason is not None
    assert "double_record_completed" in reason


def test_purchase_compliance_accepts_real_product_gateway_shape():
    gateway = ModelPurchaseComplianceGateway(
        suitability_gateway=_suitability(),
        evidence_loader=lambda customer_id, product_id: {
            "customer_age": 30,
            "has_prior_r3_plus_purchase": True,
        },
    )

    reason = gateway.validate_purchase(
        1,
        {"product_id": 10, "risk_level": "R3", "product_type": "公募基金"},
        OperationCommand("purchase", {"amount": "10000"}),
    )

    assert reason is None


@pytest.mark.parametrize(
    ("product", "assessment", "evidence"),
    [
        (_product("R3"), _assessment("C3"), {"customer_age": 30, "has_prior_r3_plus_purchase": False}),
        (_product("R2"), _assessment("C3"), {"customer_age": 65, "has_prior_r3_plus_purchase": True}),
        (_product("R5"), _assessment("C1", professional=True), {"customer_age": 30, "has_prior_r3_plus_purchase": True, "risk_disclosure_signed": True, "risk_notification_acknowledged": True}),
        ({**_product("R2"), "product_type": "结构性存款"}, _assessment("C3"), {"customer_age": 30, "has_prior_r3_plus_purchase": True}),
    ],
)
def test_purchase_double_record_triggers_fail_closed(product, assessment, evidence):
    gateway = ModelPurchaseComplianceGateway(
        suitability_gateway=_suitability(assessment=assessment, product=product),
        evidence_loader=lambda customer_id, product_id: evidence,
        holding_summary_loader=lambda customer_id, risk_level: {
            "total_value": "10000000", "risk_level_value": "0"
        },
    )

    reason = gateway.validate_purchase(
        1, product, OperationCommand("purchase", {"amount": "10000"})
    )

    assert reason is not None and "double_record_completed" in reason


def test_expired_assessment_allows_redeeming_existing_position():
    gateway = ModelOperationRiskGateway(
        profile_loader=lambda customer_id: {"fm_flags": ["FM-03-风评过期冻结新购"]}
    )

    assert gateway.validate_redeem(1, 10, Decimal("1")) is None


@pytest.mark.parametrize(
    "flag",
    ["FM-04-证件过期冻结全部交易", "FM-05-疑似账户盗用立即冻结"],
)
def test_full_transaction_freeze_blocks_redeem(flag):
    gateway = ModelOperationRiskGateway(
        profile_loader=lambda customer_id: {"fm_flags": [flag]}
    )

    reason = gateway.validate_redeem(1, 10, Decimal("1"))

    assert reason is not None
    assert "冻结" in reason


def test_expired_assessment_blocks_transfer_but_not_redeem():
    gateway = ModelOperationRiskGateway(
        profile_loader=lambda customer_id: {"fm_flags": ["FM-03-风评过期冻结新购"]},
        payee_verifier=lambda customer_id, payee: True,
    )

    reason = gateway.validate_transfer(
        1, Decimal("100"), {"account": "62220000", "name": "张三"}
    )

    assert reason == "风评过期后仅允许赎回存量，暂不能转账"


def test_transfer_fails_closed_when_payee_verification_is_unknown():
    gateway = ModelOperationRiskGateway(
        profile_loader=lambda customer_id: {"fm_flags": []},
        payee_verifier=lambda customer_id, payee: None,
    )

    reason = gateway.validate_transfer(
        1, Decimal("100"), {"account": "62220000", "name": "张三"}
    )

    assert reason == "收款方未通过核验，暂不能转账"


def test_redeem_and_transfer_fail_closed_without_profile():
    gateway = ModelOperationRiskGateway(profile_loader=lambda customer_id: None)

    redeem_reason = gateway.validate_redeem(1, 10, Decimal("1"))
    transfer_reason = gateway.validate_transfer(
        1, Decimal("100"), {"account": "62220000", "name": "张三"}
    )

    assert "画像缺失" in redeem_reason
    assert "画像缺失" in transfer_reason
