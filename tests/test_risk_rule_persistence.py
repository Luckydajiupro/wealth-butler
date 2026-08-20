from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.WealthButler.Api import riskApi
from app.WealthButler.Models.riskRuleConfigModel import RiskRuleConfigModel


@pytest.fixture(autouse=True)
def clear_rule_cache():
    original = dict(riskApi._RULE_OVERRIDES)
    riskApi._RULE_OVERRIDES.clear()
    yield
    riskApi._RULE_OVERRIDES.clear()
    riskApi._RULE_OVERRIDES.update(original)


def test_persisted_rule_metadata_keeps_code_owned_checker(monkeypatch):
    base = riskApi.AML_RULES["RW-001"]
    config = RiskRuleConfigModel(
        rule_id=base.rule_id,
        rule_name="持久化后的规则名称",
        trigger_scope=base.trigger_scope,
        risk_level=base.risk_level,
        weight_tier=base.weight_tier,
        priority=2,
        thresholds={"daily_limit": "60000"},
        source_tables=list(base.source_tables),
        source_fields=list(base.source_fields),
        rule_version="1.4",
        enabled=False,
        updated_by=77,
    )
    monkeypatch.setattr(RiskRuleConfigModel, "load_all", classmethod(lambda cls: [config]))

    rule = riskApi._rule_catalog()["RW-001"]

    assert rule.rule_name == "持久化后的规则名称"
    assert rule.rule_version == "1.4"
    assert rule.enabled is False
    assert rule.check_func is base.check_func


def test_update_rule_persists_before_cache_change(monkeypatch):
    base = riskApi.AML_RULES["RW-001"]
    captured = {}
    monkeypatch.setattr(riskApi, "_require_rule_admin", lambda _credentials: SimpleNamespace(id=88))
    monkeypatch.setattr(riskApi, "_rule_catalog", lambda: {base.rule_id: base})
    monkeypatch.setattr(
        RiskRuleConfigModel,
        "upsert_snapshot",
        classmethod(lambda cls, snapshot: captured.update(snapshot)),
    )

    riskApi.update_risk_rule(
        base.rule_id,
        riskApi.RuleChangeRequest(rule_name="新名称", priority=3),
        credentials=None,
    )

    assert captured["rule_name"] == "新名称"
    assert captured["priority"] == 3
    assert captured["updated_by"] == 88
    assert captured["rule_version"] != base.rule_version
    assert riskApi._RULE_OVERRIDES[base.rule_id].rule_name == "新名称"


def test_update_rule_fails_closed_when_persistence_fails(monkeypatch):
    base = riskApi.AML_RULES["RW-001"]
    monkeypatch.setattr(riskApi, "_require_rule_admin", lambda _credentials: SimpleNamespace(id=88))
    monkeypatch.setattr(riskApi, "_rule_catalog", lambda: {base.rule_id: base})

    def fail(_cls, _snapshot):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(RiskRuleConfigModel, "upsert_snapshot", classmethod(fail))

    with pytest.raises(HTTPException) as exc_info:
        riskApi.update_risk_rule(
            base.rule_id,
            riskApi.RuleChangeRequest(rule_name="不能生效"),
            credentials=None,
        )

    assert exc_info.value.status_code == 503
    assert base.rule_id not in riskApi._RULE_OVERRIDES


def test_risk_dashboard_does_not_fabricate_comparison_values():
    html = (
        __import__("pathlib").Path(__file__).parents[1]
        / "app/WealthButler/Frontend/pages/risk_dashboard.html"
    ).read_text(encoding="utf-8")

    assert "textContent = '+5'" not in html
    assert "textContent = '-1.2%'" not in html
    assert "暂无对比" in html
