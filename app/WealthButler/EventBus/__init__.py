"""Redis Streams 事件总线及标准事件模型。"""

from app.WealthButler.EventBus.consumer import start_all_consumers, stop_all_consumers
from app.WealthButler.EventBus.eventBus import EventBus
from app.WealthButler.EventBus.schemas import (
    LargeTransactionEvent,
    ProfileUpdatedEvent,
    RiskAlertEvent,
    SuspiciousIntentEvent,
    WorkOrderEvent,
    validate_event,
)

__all__ = [
    "EventBus",
    "LargeTransactionEvent",
    "SuspiciousIntentEvent",
    "RiskAlertEvent",
    "ProfileUpdatedEvent",
    "WorkOrderEvent",
    "validate_event",
    "start_all_consumers",
    "stop_all_consumers",
]
