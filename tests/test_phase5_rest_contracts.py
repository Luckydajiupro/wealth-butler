"""Phase 5 目标 REST 契约的离线聚焦测试。"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.WealthButler.Api import phase5ContractApi as api
from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel
from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
from app.WealthButler.Models.knowledgeMetaModel import KnowledgeMetaModel
from app.WealthButler.Service.riskAssessService import RiskAssessService


def _user(user_id=7):
    return SimpleNamespace(id=user_id, source_module="fin")


def _allow_business_user(monkeypatch, user_type="EMPLOYEE", user_id=7):
    monkeypatch.setattr(
        BaseUserExtModel,
        "get_by_id",
        classmethod(lambda cls, _user_id: SimpleNamespace(id=user_id, user_type=user_type)),
    )
    monkeypatch.setattr(api.AuthService, "has_permission", classmethod(lambda cls, *_args, **_kwargs: True))


def test_target_routes_are_registered_with_expected_methods():
    operations = {
        (method, route.path)
        for route in api.router.routes
        for method in (getattr(route, "methods", None) or set())
    }
    expected = {
        ("POST", "/api/knowledge/upload"),
        ("POST", "/api/knowledge/search"),
        ("GET", "/api/knowledge/list"),
        ("DELETE", "/api/knowledge/{knowledge_id}"),
        ("GET", "/api/profile/assessment/questions"),
        ("GET", "/api/profile/{customer_id}"),
        ("POST", "/api/profile/{customer_id}/assessment"),
        ("GET", "/api/product/list"),
        ("GET", "/api/product/{product_id}"),
        ("POST", "/api/product/recommend"),
        ("POST", "/api/risk/monitor"),
        ("GET", "/api/graph/stats"),
        ("GET", "/api/graph/visualization/{customer_id}"),
        ("POST", "/api/admin/recalculate-confidence"),
    }
    assert expected <= operations


def test_customer_profile_response_hides_internal_scoring_fields(monkeypatch):
    _allow_business_user(monkeypatch, user_type="CUSTOMER", user_id=101)
    profile = CustomerProfileModel(
        id=1,
        customer_id=101,
        risk_level="C2",
        risk_score=Decimal("38.50"),
        fm_flags=["FM-04"],
        confidence_score=Decimal("0.800"),
        asset_allocation={"cash": 0.4},
        product_preference={"type": "债券"},
    )
    monkeypatch.setattr(
        CustomerProfileModel,
        "find_by_customer_id",
        classmethod(lambda cls, _customer_id: profile),
    )
    monkeypatch.setattr(
        RiskAssessService,
        "get_latest_assessment",
        classmethod(lambda cls, _customer_id: SimpleNamespace(valid_until=datetime(2027, 8, 17))),
    )

    response = api.get_profile(101, _user(101))

    assert response.data == {
        "customer_id": 101,
        "risk_level": "C2",
        "asset_allocation": {"cash": 0.4},
        "product_preference": {"type": "债券"},
        "valid_until": "2027-08-17T00:00:00",
    }
    assert "fm_flags" not in response.data
    assert "confidence_score" not in response.data


def test_knowledge_list_maps_legacy_storage_values_to_public_contract(monkeypatch):
    _allow_business_user(monkeypatch)
    record = KnowledgeMetaModel(
        id=1,
        knowledge_type="产品说明书",
        collection_name="fin_product_collection",
        title="产品手册",
        status="待审核",
    )
    captured = {}

    def find_by(cls, **filters):
        captured.update(filters)
        return [record]

    monkeypatch.setattr(KnowledgeMetaModel, "find_by", classmethod(find_by))
    response = api.list_knowledge("产品说明", "待入库", 20, 0, _user())

    assert captured["knowledge_type"] == "产品说明书"
    assert captured["status"] == "待审核"
    assert response.data["items"][0]["knowledge_type"] == "产品说明"
    assert response.data["items"][0]["status"] == "待入库"


def test_system_config_routes_still_require_employee_identity(monkeypatch):
    _allow_business_user(monkeypatch, user_type="CUSTOMER", user_id=101)
    with pytest.raises(HTTPException) as exc_info:
        api._require_employee_permission(_user(101), "system:config")
    assert exc_info.value.status_code == 403


def test_risk_monitor_preserves_requested_rule_scope(monkeypatch):
    _allow_business_user(monkeypatch)
    calls = []

    class FakeRiskAgent:
        def scan_selected_rules(self, rule_codes, customer_ids=None):
            calls.append((rule_codes, customer_ids))
            return {"triggered_alerts": [{"rule_id": rule_codes[0]}]}

    monkeypatch.setattr("app.WealthButler.Agent.riskAgent.RiskAgent", FakeRiskAgent)
    response = api.monitor_risk(
        api.RiskMonitorRequest(customer_id=101, rule_codes=["RW-002"]),
        _user(),
    )

    assert calls == [(["RW-002"], [101])]
    assert response.data == [{"rule_id": "RW-002"}]


def test_recalculate_confidence_uses_memory_formula_and_updates_profile(monkeypatch):
    _allow_business_user(monkeypatch)
    profile = CustomerProfileModel(
        id=1,
        customer_id=101,
        memory_units=[{
            "content": "客户偏好稳健产品",
            "source": "风评问卷",
            "evidence_count": 1,
            "conflict_count": 0,
            "create_time": datetime.now().isoformat(),
        }],
    )
    captured = {}

    def update(self, **fields):
        captured.update(fields)
        return True

    monkeypatch.setattr(CustomerProfileModel, "update", update)
    monkeypatch.setattr(
        CustomerProfileModel,
        "find_by_customer_id",
        classmethod(lambda cls, _customer_id: profile),
    )

    response = api.recalculate_confidence(api.RecalculateConfidenceRequest(customer_id=101), _user())

    assert response.data == {"affected_count": 1}
    assert captured["memory_units"][0]["confidence"] == 0.95
    assert captured["confidence_score"] == Decimal("0.95")


def test_assessment_service_persists_with_base_model_save(monkeypatch):
    saved = []

    def save(self):
        self.id = 88
        saved.append(self)
        return self.id

    monkeypatch.setattr("app.WealthButler.Models.riskAssessmentModel.RiskAssessmentModel.save", save)
    result = RiskAssessService.save_assessment_result(
        101,
        [{"question_no": 9, "option": "C", "option_index": 2, "score": 6}],
        Decimal("60"),
        "C3",
    )

    assert result is saved[0]
    assert result.id == 88
    assert result.answers[0]["question_no"] == 9


def test_manual_risk_scan_accepts_realtime_rules_and_rejects_unknown_rules(monkeypatch):
    from app.WealthButler.Agent.riskAgent import RiskAgent

    agent = RiskAgent.__new__(RiskAgent)
    monkeypatch.setattr(
        agent,
        "_scan",
        lambda scan_type, rules, customer_ids, run_id: {
            "scan_type": scan_type,
            "rules": rules,
        },
    )
    result = agent.scan_selected_rules(["RW-001"])
    assert result == {"scan_type": "manual", "rules": ["RW-001"]}
    try:
        agent.scan_selected_rules(["RW-999"])
    except ValueError as exc:
        assert "不支持规则" in str(exc)
    else:
        raise AssertionError("未知规则应被手动扫描入口拒绝")
