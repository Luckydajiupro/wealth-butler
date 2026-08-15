"""事件 Schema 定义

定义事件总线中流转的各类事件数据结构，使用 Pydantic 保证类型安全。

架构设计文档 §2.4 - 已定义事件类型
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class LargeTransactionEvent(BaseModel):
    """大额交易事件（业务操作 Agent → 风控监测 Agent）

    触发条件：单笔交易金额 ≥ 50000 元
    用途：实时风控规则 RW-001/RW-003 的触发信号
    """
    customer_id: int = Field(..., description="客户ID")
    product_id: int = Field(..., description="产品ID")
    amount: float = Field(..., description="交易金额（元）")
    tx_type: str = Field(..., description="交易类型: purchase | redeem")
    tx_id: str = Field(..., description="交易流水号")
    timestamp: Optional[int] = Field(None, description="交易时间戳（毫秒）")


class SuspiciousIntentEvent(BaseModel):
    """可疑意图事件（智能客服 Agent → 风控监测 Agent）

    触发条件：客服对话中检测到敏感关键词或可疑行为模式
    用途：反洗钱规则的辅助信号
    """
    customer_id: int = Field(..., description="客户ID")
    session_id: str = Field(..., description="会话ID")
    suspicious_text: str = Field(..., description="可疑对话文本片段")
    intent_type: str = Field(..., description="意图类型: money_laundering | fraud | phishing | other")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="置信度 0-1")


class RiskAlertEvent(BaseModel):
    """风险预警事件（风控监测 Agent → 投顾助手 Agent / 客服 Agent）

    触发条件：风控规则命中，生成预警
    用途：通知下游 Agent 更新客户风险标记
    """
    customer_id: int = Field(..., description="客户ID")
    alert_id: int = Field(..., description="预警记录ID（fin_risk_alert表主键）")
    rule_code: str = Field(..., description="触发规则编号（如 RW-001）")
    alert_level: str = Field(..., description="预警级别: 低 | 中 | 高")
    alert_reason: str = Field(..., description="预警原因描述")
    triggered_at: int = Field(..., description="触发时间戳（毫秒）")


class ProfileUpdatedEvent(BaseModel):
    """画像更新事件（投顾助手 Agent → 推荐引擎）

    触发条件：客户画像关键字段变更（风险等级、投资偏好等）
    用途：触发个性化推荐重新计算
    """
    customer_id: int = Field(..., description="客户ID")
    updated_fields: Dict[str, Any] = Field(..., description="更新的字段 {字段名: 新值}")
    update_reason: str = Field(..., description="更新原因: risk_reassessment | behavior_change | manual")


class WorkOrderEvent(BaseModel):
    """工单事件（智能客服 Agent → 理财顾问工作台）

    触发条件：客户咨询需要人工介入、投诉、转介等
    用途：自动创建工单并分配给相应理财顾问
    """
    order_id: int = Field(..., description="工单ID（biz_work_order表主键）")
    order_type: str = Field(..., description="工单类型: 客户转介 | 投诉 | 咨询 | 适当性例外审批")
    customer_id: int = Field(..., description="客户ID")
    description: str = Field(..., description="工单描述")
    priority: str = Field("中", description="优先级: 低 | 中 | 高")
    handler_id: Optional[int] = Field(None, description="指定处理人ID（可选）")


# 事件类型与 Schema 的映射（供运行时校验）
EVENT_SCHEMAS = {
    'large_transaction': LargeTransactionEvent,
    'suspicious_intent': SuspiciousIntentEvent,
    'risk_alert': RiskAlertEvent,
    'profile_updated': ProfileUpdatedEvent,
    'work_order': WorkOrderEvent,
}


def validate_event(event_type: str, payload: dict) -> BaseModel:
    """校验事件 payload 是否符合 Schema

    Args:
        event_type: 事件类型
        payload: 事件载荷

    Returns:
        校验后的 Pydantic 模型实例

    Raises:
        ValueError: 未知的事件类型
        pydantic.ValidationError: payload 格式错误
    """
    schema_class = EVENT_SCHEMAS.get(event_type)

    if schema_class is None:
        raise ValueError(f"Unknown event type: {event_type}")

    return schema_class(**payload)
