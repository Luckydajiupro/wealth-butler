"""客服转人工工单工具。"""
from typing import Optional

from pydantic import BaseModel, Field

from app.Base.Ai.base.baseTool import BaseTool
from app.WealthButler.Service.workOrderService import WorkOrderService


class WorkOrderArgs(BaseModel):
    customer_id: int = Field(..., gt=0, description="客户 ID")
    intent_summary: str = Field(..., min_length=1, max_length=500, description="客户诉求摘要")
    priority: str = Field(default="中", pattern="^(低|中|高|紧急)$", description="工单优先级")
    session_id: str = Field(..., min_length=1, max_length=64, description="会话 ID")
    business_subtype: str = Field(..., description="结构化业务子类型")


class WorkOrderTool(BaseTool):
    """通过通用 WorkOrderService 创建客户转介工单。"""

    name = "WorkOrder"
    description = "客户需要人工服务时创建客户转介工单。"
    args_schema = WorkOrderArgs

    def __init__(self, service: Optional[WorkOrderService] = None):
        super().__init__()
        self.service = service or WorkOrderService()

    def execute(self, customer_id: int, intent_summary: str, priority: str, session_id: str, business_subtype: str) -> dict:
        return self.service.create_customer_referral(
            customer_id=customer_id,
            intent_summary=intent_summary,
            priority=priority,
            session_id=session_id,
            business_subtype=business_subtype,
        )
