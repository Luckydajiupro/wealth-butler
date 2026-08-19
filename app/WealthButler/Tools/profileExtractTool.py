"""客服对话中的显式客户偏好规则提取工具。"""
from pydantic import BaseModel, Field

from app.Base.Ai.base.baseTool import BaseTool


class ProfileExtractArgs(BaseModel):
    conversation_text: str = Field(..., min_length=1, description="本轮客户对话文本")
    customer_id: int = Field(..., gt=0, description="客户 ID")


class ProfileExtractTool(BaseTool):
    """只提取客户明确表达的信息，不把模型推测写成客户事实。"""

    name = "ProfileExtract"
    description = "提取客户主动表达的风险偏好或投资目标，供后续人工确认。"
    args_schema = ProfileExtractArgs

    def execute(self, conversation_text: str, customer_id: int) -> dict:
        attrs = {}
        if "稳健" in conversation_text:
            attrs["risk_preference"] = "稳健"
        elif "激进" in conversation_text:
            attrs["risk_preference"] = "进取"
        if "养老" in conversation_text:
            attrs["investment_goal"] = "养老"
        return {"customer_id": customer_id, "extracted_attrs": attrs, "persisted": False}
