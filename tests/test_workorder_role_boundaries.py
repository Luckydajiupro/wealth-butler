"""工单角色隔离和风险详情前端契约。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.WealthButler.Api.workOrderApi import (
    UpdateWorkOrderRequest,
    _filter_workorders_by_role,
    _role_can_handle_workorder,
    update_workorder,
)
from pathlib import Path


def _order(order_type, summary="申购产品", subtype=None):
    return SimpleNamespace(order_type=order_type, intent_summary=summary, description=None, title=None,
                           handle_records={"business_subtype": subtype} if subtype else None)


def test_operator_never_sees_or_claims_risk_orders():
    risk_orders = [_order("风险预警"), _order("风控预警"), _order("风控处置")]
    assert _filter_workorders_by_role(risk_orders, "manager") == []
    assert all(not _role_can_handle_workorder(order, "manager") for order in risk_orders)
    assert all(_role_can_handle_workorder(order, "risk") for order in risk_orders)


def test_advisor_and_operator_pools_are_disjoint():
    advisor_order = _order("客户转介", "完全无关摘要", "产品配置")
    operator_order = _order("客户转介", "完全无关摘要", "申购")
    assert _filter_workorders_by_role([advisor_order, operator_order], "advisor") == [advisor_order]
    assert _filter_workorders_by_role([advisor_order, operator_order], "manager") == [operator_order]


def test_referral_without_subtype_is_not_routed_by_summary():
    legacy_order = _order("客户转介", "申购产品", None)
    assert _filter_workorders_by_role([legacy_order], "advisor") == []
    assert _filter_workorders_by_role([legacy_order], "manager") == []


def test_completed_legacy_workorder_recovers_subtype_from_linked_transaction(monkeypatch):
    completed = SimpleNamespace(
        order_type="客户转介",
        intent_summary="历史业务摘要",
        description=None,
        title=None,
        handle_records=None,
        business_subtype=None,
        related_entity_type="transaction",
        related_entity_id=10227,
    )
    monkeypatch.setattr(
        "app.WealthButler.Models.transactionModel.TransactionModel.get_by_id",
        classmethod(lambda cls, transaction_id: SimpleNamespace(transaction_type="赎回")),
    )

    assert _filter_workorders_by_role([completed], "manager") == [completed]


def test_workorder_completion_accepts_typed_transaction_link():
    request = UpdateWorkOrderRequest(
        action="complete",
        remark="申购已成交，交易流水 #81",
        related_entity_type="transaction",
        related_entity_id=81,
    )

    assert request.related_entity_type == "transaction"
    assert request.related_entity_id == 81


def test_operator_closes_own_purchase_order_and_publishes_reason(monkeypatch):
    saved = []
    published = []
    order = SimpleNamespace(
        id=7, deleted_at=None, status="处理中", handled_by=42,
        handle_records={"business_subtype": "申购"}, business_subtype="申购",
        closed_at=None, remark=None, save=lambda: saved.append(True) or 7,
    )
    user = SimpleNamespace(id=42, username="胡晓东")
    monkeypatch.setattr("app.WealthButler.Api.workOrderApi._get_current_user", lambda _: user)
    monkeypatch.setattr("app.WealthButler.Api.workOrderApi._get_user_role_type", lambda _: "manager")
    monkeypatch.setattr("app.WealthButler.Api.workOrderApi.WorkOrderModel.get_by_id", lambda _: order)
    monkeypatch.setattr(
        "app.WealthButler.Api.workOrderApi._publish_customer_result",
        lambda workorder, handler_id, status, remark: published.append((workorder, handler_id, status, remark)),
    )

    response = update_workorder(
        7,
        UpdateWorkOrderRequest(action="close", remark="申购金额不满足产品起投要求"),
        credentials=object(),
    )

    assert response.status_code == 200
    assert order.status == "已关闭"
    assert order.remark == "申购金额不满足产品起投要求"
    assert order.closed_at is not None
    assert order.handle_records["close_record"]["handler_id"] == 42
    assert saved == [True]
    assert published == [(order, 42, "已关闭", "申购金额不满足产品起投要求")]


def test_operator_close_requires_reason_and_ownership(monkeypatch):
    order = SimpleNamespace(
        id=7, deleted_at=None, status="处理中", handled_by=99,
        handle_records={"business_subtype": "赎回"}, business_subtype="赎回",
    )
    user = SimpleNamespace(id=42, username="胡晓东")
    monkeypatch.setattr("app.WealthButler.Api.workOrderApi._get_current_user", lambda _: user)
    monkeypatch.setattr("app.WealthButler.Api.workOrderApi._get_user_role_type", lambda _: "manager")
    monkeypatch.setattr("app.WealthButler.Api.workOrderApi.WorkOrderModel.get_by_id", lambda _: order)

    with pytest.raises(HTTPException, match="只能关闭自己领取的工单"):
        update_workorder(7, UpdateWorkOrderRequest(action="close", remark="份额不足"), credentials=object())

    order.handled_by = 42
    with pytest.raises(HTTPException, match="必须填写原因"):
        update_workorder(7, UpdateWorkOrderRequest(action="close"), credentials=object())


def test_workorder_list_assignment_is_derived_from_authenticated_user():
    api_source = (Path(__file__).parents[1] / "app" / "WealthButler" / "Api" / "workOrderApi.py").read_text(encoding="utf-8")
    assert '"owned" if user.id in handler_ids' in api_source
    assert '"unclaimed" if not any(handler_ids)' in api_source
    assert '"assignment_scope": assignment_scope' in api_source


def test_risk_detail_button_uses_real_modal_and_detail_api():
    html = (Path(__file__).parents[1] / "app" / "WealthButler" / "Frontend" / "pages" / "risk_dashboard.html").read_text(encoding="utf-8")
    assert "id=\"alertDetailModal\"" in html
    assert "function closeAlertDetail()" in html
    assert "/api/wealth/risk/alert/${encodeURIComponent(alertId)}" in html
    assert "实际项目中这里会打开详情页面或弹窗" not in html
    assert "// 模拟更新" not in html
    assert "页面未修改任何预警状态" in html
    assert "generateMockAlerts" not in html
    assert "generateMockTrendData" not in html
    assert "暂无数据" in html


def test_risk_dashboard_has_read_only_rule_and_report_entrypoints():
    html = (Path(__file__).parents[1] / "app" / "WealthButler" / "Frontend" / "pages" / "risk_dashboard.html").read_text(encoding="utf-8")
    assert 'href="#ruleConfig"' in html
    assert 'href="#dataReports"' in html
    assert 'id="ruleConfig"' in html
    assert 'id="dataReports"' in html
    assert "function loadRules()" in html
    assert "/api/wealth/risk/rules" in html
    assert "暂无可用风控规则" in html
