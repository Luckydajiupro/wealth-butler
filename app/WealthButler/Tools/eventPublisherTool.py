"""事件发布工具（组F，Agent设计 §7 工具族；公开名 EventPublisher）

职责边界：只负责把已结构化的业务事件发布到 Redis Streams 事件总线——
**不判断规则、不写数据库、不创建工单**（那些属于 RiskAgent 编排）。
发布前用 EventBus.schemas.validate_event 校验 event_type/payload；Redis/EventBus
不可用时返回结构化 error/degraded，绝不声称发布成功。

发布调用按**当前实际** EventBus.publish 签名（stream_key, event_type, payload,
source_agent, trace_id），不照搬旧文档的其他签名（任务§14红线）。

生产风控链路约束（RiskAgent 内固定）：stream_key="stream:risk_alert"、
event_type="risk_alert"、payload 兼容 RiskAlertEvent
（customer_id/alert_id/rule_id/severity/trigger_details/created_at）。
本工具本身是通用发布器（stream_key/event_type 为入参），不内置业务限制。

测试中的 Redis/EventBus 替身只存在于测试文件（MOCK_ONLY），本模块只含生产路径。
"""
import logging
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from pydantic import BaseModel, Field

from app.Base.Ai.base.baseTool import BaseTool  # 生产继承真实 BaseTool
from app.WealthButler.EventBus.schemas import validate_event

logger = logging.getLogger(__name__)


class EventPublisherInput(BaseModel):
    """EventPublisher 的 Function Calling 参数 schema（BaseTool.run 校验用）。

    至少兼容 stream_key / event_type / payload 三字段调用；source_agent / trace_id
    为扩展字段（有默认值，不破坏既有三字段调用）。
    """

    stream_key: str = Field(..., description="目标 Stream key（生产风控链路固定 stream:risk_alert）")
    event_type: str = Field(..., description="事件类型（与 EventBus.schemas.EVENT_SCHEMAS 键一致，如 risk_alert）")
    payload: Dict[str, Any] = Field(..., description="事件载荷（按对应 Schema 校验，如 RiskAlertEvent）")
    source_agent: str = Field("risk_agent", description="发布者 Agent 名称")
    trace_id: Optional[str] = Field(None, description="分布式跟踪 ID（缺省自动生成 UUID）")


def _default_publisher(stream_key: str, event_type: str, payload: Dict[str, Any],
                       source_agent: str, trace_id: Optional[str]) -> str:
    """默认发布实现：按当前实际 EventBus.publish 签名调用（惰性导入，失败向上抛）。"""
    from app.WealthButler.EventBus.eventBus import EventBus
    return EventBus.publish(stream_key=stream_key, event_type=event_type, payload=payload,
                            source_agent=source_agent, trace_id=trace_id)


class EventPublisherTool(BaseTool):
    """跨 Agent 事件发布工具（公开名 EventPublisher）。

    入参：stream_key / event_type / payload（+ 可选 source_agent / trace_id）。
    出参：{status: published|degraded|error, message_id, stream_key, event_type,
          trace_id, published_at, error?}——JSON 可序列化。
    """

    name = "EventPublisher"
    description = (
        "跨Agent事件发布工具：把已结构化的业务事件发布到 Redis Streams 事件总线"
        "（EventBus.publish，XADD）。只负责发布，不判断风控规则、不写数据库、不创建工单；"
        "发布前按 EventBus.schemas 校验 event_type/payload；Redis 或 EventBus 不可用时"
        "返回结构化 error/degraded，绝不声称发布成功。"
    )
    args_schema = EventPublisherInput

    def __init__(self, name=None, description=None, args_schema=None,
                 publisher: Callable = None, now_fn: Callable = None):
        super().__init__(name=name, description=description, args_schema=args_schema)
        self._publisher = publisher or _default_publisher
        self._now_fn = now_fn or datetime.now

    def execute(self, **kwargs) -> Dict[str, Any]:
        """执行发布（BaseTool.run 已用 args_schema 校验过 kwargs）。"""
        return self.publish(
            stream_key=kwargs["stream_key"],
            event_type=kwargs["event_type"],
            payload=kwargs["payload"],
            source_agent=kwargs.get("source_agent", "risk_agent"),
            trace_id=kwargs.get("trace_id"),
        )

    def publish(self, stream_key: str, event_type: str, payload: Dict[str, Any],
                source_agent: str = "risk_agent",
                trace_id: Optional[str] = None) -> Dict[str, Any]:
        """发布核心（供 Tool 与测试直接调用）。

        校验失败/发布异常 → status=error（携带 error 信息），不抛异常；
        只有 EventBus.publish 真正返回 message_id 才 status=published。
        """
        trace_id = trace_id or str(uuid.uuid4())
        published_at = self._now_fn().isoformat()
        base = {
            "status": "published",
            "message_id": None,
            "stream_key": stream_key,
            "event_type": event_type,
            "trace_id": trace_id,
            "published_at": published_at,
            "error": None,
        }
        try:
            validate_event(event_type, payload)
        except Exception as exc:
            base["status"] = "error"
            base["error"] = f"payload 校验失败: {exc}"
            return base
        try:
            message_id = self._publisher(stream_key=stream_key, event_type=event_type,
                                         payload=payload, source_agent=source_agent,
                                         trace_id=trace_id)
        except Exception as exc:
            logger.error("EventPublisher 发布失败: %s", exc)
            base["status"] = "error"
            base["error"] = f"EventBus 发布失败: {exc}"
            return base
        if not message_id:
            base["status"] = "error"
            base["error"] = "EventBus.publish 返回空 message_id，视为发布失败"
            return base
        base["message_id"] = message_id
        return base


__all__ = ["EventPublisherTool", "EventPublisherInput"]
