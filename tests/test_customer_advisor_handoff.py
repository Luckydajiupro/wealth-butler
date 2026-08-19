from types import SimpleNamespace

from app.WealthButler.Api.workOrderApi import (
    _filter_workorders_by_role,
    _role_can_handle_workorder,
    _workorder_summary,
)
from app.WealthButler.Models.workOrderModel import WorkOrderModel
from app.WealthButler.Repository.customerServiceRepository import CustomerServiceRepository


class _FakeClient:
    database = "wealth_butler"

    def __init__(self):
        self.calls = []

    def execute_sync(self, sql, params=None):
        self.calls.append((sql, params))
        if "SELECT id, order_no" in sql:
            return [{"id": 249, "order_no": "CS-TEST", "status": "待处理"}]
        return []

    def close(self):
        return None


def test_customer_referral_populates_advisor_handoff_fields():
    client = _FakeClient()
    repository = CustomerServiceRepository(client=client)
    repository._schema_checked = True

    result = repository.create_customer_referral(
        customer_id=1,
        intent_summary="我要办理申购",
        priority="中",
        session_id="handoff-session",
    )

    insert_sql, insert_params = next(
        (sql, params) for sql, params in client.calls if "INSERT INTO biz_work_order" in sql
    )
    assert "customer_name" in insert_sql
    assert "intent_summary" in insert_sql
    assert insert_params[1:3] == (1, 1)
    assert insert_params[4:6] == ("我要办理申购", "我要办理申购")
    assert result["id"] == 249


def test_purchase_referral_routes_to_customer_manager_not_advisor():
    order = SimpleNamespace(
        order_type="客户转介",
        intent_summary=None,
        description="我要办理申购",
        title="客户转人工服务",
        handle_records={"business_subtype": "申购"},
    )

    assert _workorder_summary(order) == "我要办理申购"
    assert _filter_workorders_by_role([order], "advisor") == []
    assert _filter_workorders_by_role([order], "manager") == [order]
    assert _role_can_handle_workorder(order, "advisor") is False
    assert _role_can_handle_workorder(order, "manager") is True


def test_advisory_configuration_routes_only_to_advisor():
    order = SimpleNamespace(
        order_type="客户转介",
        intent_summary="请为客户生成产品配置方案并说明适当性",
        description=None,
        title="客户转人工服务",
        handle_records={"business_subtype": "产品配置"},
    )

    assert _filter_workorders_by_role([order], "advisor") == [order]
    assert _filter_workorders_by_role([order], "manager") == []


def test_advisor_filter_excludes_routine_product_risk_question():
    order = SimpleNamespace(
        order_type="客户转介",
        intent_summary="理财产品的风险等级是什么？",
        description=None,
        title="客户转人工服务",
        handle_records={"business_subtype": None},
    )

    assert _filter_workorders_by_role([order], "advisor") == []


def test_workorder_query_applies_intent_keywords_before_pagination(monkeypatch):
    statements = []

    class FakeDb:
        def execute(self, sql, params=None):
            statements.append((sql, params))
            if "COUNT(*)" in sql:
                return [{"total": 0}]
            return []

    monkeypatch.setattr(WorkOrderModel, "_ensure_table_exists", classmethod(lambda cls: None))
    monkeypatch.setattr(WorkOrderModel, "get_db_connection", classmethod(lambda cls: FakeDb()))

    WorkOrderModel.find_by_filters(
        order_type="客户转介",
        status="待处理",
        intent_keywords=["申购", "赎回"],
        limit=20,
    )

    count_sql, params = statements[0]
    assert "COALESCE(intent_summary, description, title, '') LIKE %s" in count_sql
    assert params == ("客户转介", "待处理", "%申购%", "%赎回%")


def test_workorder_model_decodes_legacy_handle_record_array():
    order = WorkOrderModel(
        order_no="CS-TEST",
        order_type="客户转介",
        source="转人工",
        title="客户转人工服务",
        handle_records='[{"action":"客服Agent转人工"}]',
    )

    assert order.handle_records == [{"action": "客服Agent转人工"}]
