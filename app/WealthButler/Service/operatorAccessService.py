"""Operator 员工角色与客户对象级访问控制。"""

from typing import Any


class OperatorAccessService:
    OPERATOR_ROLES = {"客户经理", "业务管理员"}
    # 已完成工单仍代表该客户由该经理负责的服务关系；只有待处理且未领取的工单不构成范围。
    ACTIVE_WORK_ORDER_STATUSES = {"处理中", "待审核", "已完成"}
    HISTORICAL_WORK_ORDER_STATUSES = ACTIVE_WORK_ORDER_STATUSES | {"已关闭", "已驳回"}

    @staticmethod
    def _business_user(employee_id: int) -> Any:
        from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel

        return BaseUserExtModel.get_by_id(employee_id)

    @classmethod
    def employee_role(cls, employee_id: int) -> str:
        user = cls._business_user(employee_id)
        if not user or getattr(user, "user_type", None) != "EMPLOYEE":
            return ""
        return str(getattr(user, "employee_role", None) or "")

    @classmethod
    def can_use_operator(cls, employee_id: int) -> bool:
        return cls.employee_role(employee_id) in cls.OPERATOR_ROLES

    @classmethod
    def can_manage_all_customers(cls, employee_id: int) -> bool:
        if cls.employee_role(employee_id) == "业务管理员":
            return True
        from app.Base.Service.authService import AuthService

        user = cls._business_user(employee_id)
        role_info = AuthService.get_user_role_info(
            employee_id,
            getattr(user, "source_module", None) if user else None,
        )
        return bool(role_info.get("is_admin"))

    @classmethod
    def can_access_customer(cls, employee_id: int, customer_id: int) -> bool:
        """客户经理仅可操作本人已领取且仍在办理的客户工单。"""
        if employee_id <= 0 or customer_id <= 0 or not cls.can_use_operator(employee_id):
            return False
        if cls.can_manage_all_customers(employee_id):
            return True

        from app.WealthButler.Models.workOrderModel import WorkOrderModel

        for order in WorkOrderModel.find_by_customer_id(customer_id):
            handler_ids = {
                getattr(order, "handled_by", None),
                getattr(order, "handler_id", None),
            }
            if employee_id in handler_ids and getattr(order, "status", None) in cls.ACTIVE_WORK_ORDER_STATUSES:
                return True
        return False

    @classmethod
    def can_view_customer(cls, employee_id: int, customer_id: int) -> bool:
        """Allow read-only customer history after a claimed work order reaches a terminal state."""
        if employee_id <= 0 or customer_id <= 0 or not cls.can_use_operator(employee_id):
            return False
        if cls.can_manage_all_customers(employee_id):
            return True
        from app.WealthButler.Models.workOrderModel import WorkOrderModel

        for order in WorkOrderModel.find_by_customer_id(customer_id):
            handler_ids = {getattr(order, "handled_by", None), getattr(order, "handler_id", None)}
            if employee_id in handler_ids and getattr(order, "status", None) in cls.HISTORICAL_WORK_ORDER_STATUSES:
                return True
        return False


__all__ = ["OperatorAccessService"]
