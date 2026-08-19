from types import SimpleNamespace

from app.WealthButler.Api import advisorApi, operatorApi
from app.WealthButler.Service.operatorAccessService import OperatorAccessService


def test_advisor_allocation_plan_is_persisted_for_cross_role_read(monkeypatch):
    captured = {}

    class FakePlan:
        def __init__(self, **values):
            captured.update(values)
            self.id = None

        def save(self):
            self.id = 91
            return self.id

    monkeypatch.setattr(
        advisorApi,
        "_get_advisor_context",
        lambda _credentials: (SimpleNamespace(id=3656), False),
    )
    monkeypatch.setattr(advisorApi, "_require_customer_scope", lambda *_args: None)
    monkeypatch.setattr(advisorApi, "AdvisorAllocationPlanModel", FakePlan)
    monkeypatch.setattr(
        "app.WealthButler.Service.advisorService.AdvisorService.recommend_products",
        lambda _self, *_args, **_kwargs: {
            "context": {"risk_assessment": {"risk_level": "C4"}},
            "recommendations": [{
                "id": 12,
                "product_name": "稳健组合",
                "product_type": "混合型",
                "risk_level": "R3",
                "score": 0.8,
                "factor_scores": {"preference_score": 0.9},
            }],
        },
    )

    response = advisorApi.generate_advisor_allocation_plan(3664, credentials=None)

    assert response.status_code == 200
    assert response.data["id"] == 91
    assert captured["customer_id"] == 3664
    assert captured["advisor_id"] == 3656
    assert captured["products"][0]["allocation_percent"] == 100.0


def test_operator_overview_returns_portrait_and_latest_advisor_plan(monkeypatch):
    customer = SimpleNamespace(
        id=3664,
        username="李霞001",
        user_type="CUSTOMER",
        phone="13900000000",
        email="customer@example.com",
        customer_level="金卡",
    )
    advisor = SimpleNamespace(id=3656, username="理财顾问甲")
    profile = SimpleNamespace(
        risk_level="C4",
        risk_score=82,
        dimension1_score=20,
        dimension2_score=18,
        dimension3_score=27,
        dimension4_score=17,
        confidence_score=0.91,
        fm_flags=["FM-02"],
        updated_reason="行为",
        updated_at=None,
        asset_allocation={"cash": 0.2, "equity": 0.8, "available_balance": 5000},
        product_preference={"preferred_types": ["混合型"]},
    )
    plan = SimpleNamespace(
        id=91,
        advisor_id=3656,
        risk_level="C4",
        products=[{"product_name": "稳健组合", "allocation_percent": 100}],
        disclaimer="只读方案",
        created_at=None,
    )

    monkeypatch.setattr(OperatorAccessService, "can_view_customer", lambda *_args: True)
    monkeypatch.setattr(
        "app.WealthButler.Models.baseUserExtModel.BaseUserExtModel.get_by_id",
        lambda user_id: customer if user_id == 3664 else advisor,
    )
    monkeypatch.setattr(
        "app.WealthButler.Models.customerProfileModel.CustomerProfileModel.find_by_customer_id",
        lambda _customer_id: profile,
    )
    monkeypatch.setattr(
        "app.WealthButler.Models.riskAssessmentModel.RiskAssessmentModel.find_valid_by_customer_id",
        lambda _customer_id: SimpleNamespace(valid_until=None),
    )
    monkeypatch.setattr(
        "app.WealthButler.Service.riskAssessService.RiskAssessService.get_latest_assessment",
        lambda _customer_id: SimpleNamespace(valid_until=None),
    )
    monkeypatch.setattr(
        "app.WealthButler.Models.holdingsModel.HoldingsModel.find_by_customer_id",
        lambda _customer_id: [],
    )
    monkeypatch.setattr(
        "app.WealthButler.Models.transactionModel.TransactionModel.find_by_customer_id",
        lambda _customer_id, limit=20: [],
    )
    monkeypatch.setattr(
        "app.WealthButler.Models.advisorAllocationPlanModel.AdvisorAllocationPlanModel.find_latest_by_customer_id",
        lambda _customer_id: plan,
    )

    response = operatorApi.customer_overview(3664, current_user=SimpleNamespace(id=3662))

    assert response.status_code == 200
    assert response.data["profile"]["dimension3_score"] == 27
    assert response.data["profile"]["product_preference"] == {"preferred_types": ["混合型"]}
    assert response.data["advisor_plan"]["advisor_name"] == "理财顾问甲"
    assert response.data["advisor_plan"]["products"][0]["allocation_percent"] == 100


def test_operator_overview_uses_same_simulated_cash_fallback_as_gateway(monkeypatch):
    profile = SimpleNamespace(
        risk_level="C3", risk_score=70,
        dimension1_score=None, dimension2_score=None, dimension3_score=None, dimension4_score=None,
        confidence_score=None, fm_flags=None, updated_reason=None, updated_at=None,
        asset_allocation={"bond": 0.5, "cash": 0.2, "stock": 0.3}, product_preference=None,
    )
    customer = SimpleNamespace(
        id=3665, username="孙璐002", user_type="CUSTOMER", phone=None,
        email=None, customer_level="白金",
    )
    monkeypatch.setattr(OperatorAccessService, "can_view_customer", lambda *_args: True)
    monkeypatch.setattr(
        "app.WealthButler.Models.baseUserExtModel.BaseUserExtModel.get_by_id",
        lambda _user_id: customer,
    )
    monkeypatch.setattr(
        "app.WealthButler.Models.customerProfileModel.CustomerProfileModel.find_by_customer_id",
        lambda _customer_id: profile,
    )
    monkeypatch.setattr(
        "app.WealthButler.Service.riskAssessService.RiskAssessService.get_latest_assessment",
        lambda _customer_id: SimpleNamespace(valid_until=None),
    )
    monkeypatch.setattr(
        "app.WealthButler.Models.holdingsModel.HoldingsModel.find_by_customer_id",
        lambda _customer_id: [],
    )
    monkeypatch.setattr(
        "app.WealthButler.Models.transactionModel.TransactionModel.find_by_customer_id",
        lambda _customer_id, limit=20: [],
    )
    monkeypatch.setattr(
        "app.WealthButler.Models.advisorAllocationPlanModel.AdvisorAllocationPlanModel.find_latest_by_customer_id",
        lambda _customer_id: None,
    )
    monkeypatch.setenv("WEALTH_BUTLER_SIMULATED_COMPLIANCE_ENABLED", "true")
    monkeypatch.setenv("WEALTH_BUTLER_SIMULATED_INITIAL_CASH", "100000.00")

    response = operatorApi.customer_overview(3665, current_user=SimpleNamespace(id=3662))

    assert response.data["account"]["available_balance"] == 100000.0
    assert response.data["account"]["balance_source"] == "simulated_initial_cash"
    assert response.data["account"]["balance_is_simulated"] is True
