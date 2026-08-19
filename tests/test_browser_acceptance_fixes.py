"""浏览器人工验收发现问题的回归测试。"""

from types import SimpleNamespace

from app.WealthButler.Api import holdingsApi, workOrderApi
from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent
from app.WealthButler.Models.customerProfileModel import CustomerProfileModel


def test_customer_profile_decodes_mysql_json_columns() -> None:
    profile = CustomerProfileModel(
        customer_id=7,
        fm_flags='["FM-01"]',
        asset_allocation='{"currency":"CNY"}',
        product_preference='{"risk":"C3"}',
        memory_units='[{"tag":"稳健"}]',
    )

    assert profile.fm_flags == ["FM-01"]
    assert profile.asset_allocation == {"currency": "CNY"}
    assert profile.product_preference == {"risk": "C3"}
    assert profile.memory_units == [{"tag": "稳健"}]

    assert profile.model_dump()["asset_allocation"] == {"currency": "CNY"}


def test_workorder_role_lookup_uses_authenticated_source_module(monkeypatch) -> None:
    calls = []

    def role_info(user_id, source_module):
        calls.append((user_id, source_module))
        return {
            "permissions": ["product:recommend"],
            "is_admin": False,
        }

    monkeypatch.setattr(workOrderApi.AuthService, "get_user_role_info", role_info)

    role_type = workOrderApi._get_user_role_type(
        SimpleNamespace(id=5, source_module="fin")
    )

    assert role_type == "advisor"
    assert calls == [(5, "fin")]


def test_customer_transactions_are_scoped_to_authenticated_customer(monkeypatch) -> None:
    statements = []

    class FakeDb:
        def execute(self, sql, params=None):
            statements.append((sql, params))
            if "COUNT(*)" in sql:
                return [{"total": 1}]
            return [{
                "id": 1, "transaction_type": "申购", "amount": 1000,
                "shares": 1000, "nav": 1, "fee": 0, "channel": "APP",
                "status": "成交", "transaction_time": "2026-08-17 10:00:00",
                "product_name": "稳健产品", "product_code": "P001",
            }]

    monkeypatch.setattr(
        holdingsApi, "_get_customer", lambda credentials: SimpleNamespace(id=42)
    )
    monkeypatch.setattr(
        holdingsApi.TransactionModel, "get_db_connection", lambda: FakeDb()
    )

    response = holdingsApi.get_customer_transactions(
        limit=20, offset=0, credentials=SimpleNamespace(credentials="token")
    )

    assert response.data["items"][0]["product_name"] == "稳健产品"
    assert statements[0][1] == (42, 20, 0)
    assert statements[1][1] == (42,)


def test_customer_without_valid_assessment_cannot_list_suitable_products(monkeypatch) -> None:
    monkeypatch.setattr(
        holdingsApi, "_get_customer", lambda credentials: SimpleNamespace(id=42)
    )
    monkeypatch.setattr(
        holdingsApi.RiskAssessmentModel,
        "find_valid_by_customer_id",
        lambda _customer_id: None,
    )

    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as exc_info:
        holdingsApi.get_customer_products(
            limit=50, credentials=SimpleNamespace(credentials="token")
        )

    assert exc_info.value.status_code == 409


def test_customer_risk_status_distinguishes_missing_and_valid(monkeypatch) -> None:
    monkeypatch.setattr(
        holdingsApi, "_get_customer", lambda credentials: SimpleNamespace(id=42)
    )
    monkeypatch.setattr(
        holdingsApi.RiskAssessmentModel,
        "find_valid_by_customer_id",
        lambda _customer_id: SimpleNamespace(
            risk_level="C3", total_score=58, assessment_time="2026-08-17", valid_until="2027-08-17"
        ),
    )

    response = holdingsApi.get_customer_risk_assessment_status(
        credentials=SimpleNamespace(credentials="token")
    )

    assert response.data["status"] == "valid"
    assert response.data["required"] is False
    assert response.data["risk_level"] == "C3"


def test_customer_agent_routes_risk_assessment_to_client_action() -> None:
    assert CustomerServiceAgent._fast_path_intent("我想重新做风险测评") == (
        "risk_assessment", 0.99
    )

    assert CustomerServiceAgent._fast_path_intent("风险评估有效期多久？") == (
        "policy_explain", 0.92
    )
    assert CustomerServiceAgent._fast_path_intent("我的风险等级是什么") == (
        "risk_level_query", 0.99
    )
