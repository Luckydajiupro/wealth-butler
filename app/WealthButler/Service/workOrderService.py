"""通用业务工单的确定性服务。"""
from typing import Optional

from app.WealthButler.Repository.customerServiceRepository import CustomerServiceRepository


class WorkOrderService:
    """提供可由多个 Agent 复用的客户转介工单创建能力。"""

    def __init__(self, repository: Optional[CustomerServiceRepository] = None):
        self.repository = repository or CustomerServiceRepository()

    def create_customer_referral(
        self,
        customer_id: int,
        intent_summary: str,
        priority: str,
        session_id: str,
        business_subtype: Optional[str] = None,
    ) -> dict:
        """创建初始状态为“待处理”的客户转介工单。"""
        return self.repository.create_customer_referral(
            customer_id=customer_id,
            intent_summary=intent_summary,
            priority=priority,
            session_id=session_id,
            business_subtype=business_subtype,
        )
