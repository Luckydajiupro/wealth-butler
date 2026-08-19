"""客户经理对象级客户范围约束。"""

from types import SimpleNamespace

from app.WealthButler.Service.operatorAccessService import OperatorAccessService


def test_operator_scope_requires_active_owned_work_order(monkeypatch):
    employee = SimpleNamespace(user_type="EMPLOYEE", employee_role="客户经理", source_module="fin")
    monkeypatch.setattr(OperatorAccessService, "_business_user", staticmethod(lambda _id: employee))
    monkeypatch.setattr(OperatorAccessService, "can_manage_all_customers", classmethod(lambda cls, _id: False))

    owned = SimpleNamespace(handled_by=8, handler_id=None, status="处理中")
    other = SimpleNamespace(handled_by=9, handler_id=None, status="处理中")
    pending = SimpleNamespace(handled_by=None, handler_id=None, status="待处理")

    class Orders:
        @classmethod
        def find_by_customer_id(cls, customer_id):
            return {101: [owned], 102: [other], 103: [pending]}[customer_id]

    monkeypatch.setattr("app.WealthButler.Models.workOrderModel.WorkOrderModel", Orders)
    assert OperatorAccessService.can_access_customer(8, 101) is True
    assert OperatorAccessService.can_access_customer(8, 102) is False
    assert OperatorAccessService.can_access_customer(8, 103) is False


def test_operator_can_view_customer_after_closed_or_rejected_work_order(monkeypatch):
    employee = SimpleNamespace(user_type="EMPLOYEE", employee_role="客户经理", source_module="fin")
    monkeypatch.setattr(OperatorAccessService, "_business_user", staticmethod(lambda _id: employee))
    monkeypatch.setattr(OperatorAccessService, "can_manage_all_customers", classmethod(lambda cls, _id: False))

    closed = SimpleNamespace(handled_by=8, handler_id=None, status="已关闭")
    rejected = SimpleNamespace(handled_by=8, handler_id=None, status="已驳回")

    class Orders:
        @classmethod
        def find_by_customer_id(cls, customer_id):
            return [closed] if customer_id == 101 else [rejected]

    monkeypatch.setattr("app.WealthButler.Models.workOrderModel.WorkOrderModel", Orders)
    assert OperatorAccessService.can_view_customer(8, 101) is True
    assert OperatorAccessService.can_view_customer(8, 102) is True
    assert OperatorAccessService.can_access_customer(8, 101) is False
