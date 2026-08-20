"""EventBus 模式和发布合约的离线单元测试。"""

import json
import threading
import time
from unittest.mock import ANY, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.WealthButler.EventBus.eventBus import EventBus
from app.WealthButler.EventBus import consumer
from app.WealthButler.EventBus.schemas import (
    LargeTransactionEvent,
    ProfileUpdatedEvent,
    RecommendationRefreshRequestedEvent,
    RiskAlertEvent,
    SuspiciousIntentEvent,
    WorkOrderEvent,
    WorkOrderResultEvent,
    validate_event,
)


@pytest.mark.parametrize(
    ("event_type", "payload", "schema"),
    [
        (
            "large_transaction",
            {
                "customer_id": 1,
                "transaction_id": 1001,
                "product_id": 101,
                "amount": "100000.00",
                "transaction_type": "申购",
            },
            LargeTransactionEvent,
        ),
        (
            "suspicious_intent",
            {
                "customer_id": 2,
                "session_id": "session-1",
                "intent_type": "money_laundering",
                "confidence": "0.85",
            },
            SuspiciousIntentEvent,
        ),
        (
            "risk_alert",
            {
                "customer_id": 2,
                "alert_id": 2001,
                "rule_id": "RW-001",
                "severity": "high",
            },
            RiskAlertEvent,
        ),
        (
            "profile_updated",
            {
                "customer_id": 3,
                "updated_fields": {"risk_level": "C4"},
                "update_reason": "risk_reassessment",
            },
            ProfileUpdatedEvent,
        ),
        (
            "recommendation_refresh_requested",
            {
                "event_id": "recommendation-refresh:trace-profile-1",
                "customer_id": 3,
                "profile_event_trace_id": "trace-profile-1",
                "updated_fields": ["risk_level"],
                "update_reason": "risk_reassessment",
                "status": "pending",
            },
            RecommendationRefreshRequestedEvent,
        ),
        (
            "work_order",
            {
                "order_id": 3001,
                "order_type": "客户转介",
                "customer_id": 3,
                "description": "需要人工处理",
            },
            WorkOrderEvent,
        ),
        (
            "work_order_result",
            {
                "event_id": "evt-3001",
                "order_id": 3001,
                "customer_id": 3,
                "status": "已完成",
                "reply": "理财顾问已完成您的服务请求。",
                "handler_id": 9,
            },
            WorkOrderResultEvent,
        ),
    ],
)
def test_validate_current_event_schemas(event_type, payload, schema):
    assert isinstance(validate_event(event_type, payload), schema)


def test_validate_event_rejects_unknown_type():
    with pytest.raises(ValueError, match="Unknown event type"):
        validate_event("unknown", {})


def test_large_transaction_requires_current_contract_fields():
    with pytest.raises(ValidationError):
        LargeTransactionEvent(customer_id=1, tx_id="legacy-id")


def test_large_transaction_rejects_non_positive_customer_before_handler():
    with pytest.raises(ValidationError):
        LargeTransactionEvent(customer_id=0, transaction_id=1001)


def test_suspicious_intent_rejects_non_positive_customer_before_handler():
    with pytest.raises(ValidationError):
        SuspiciousIntentEvent(
            customer_id=0,
            session_id="invalid-customer",
            intent_type="fraud",
            confidence="0.90",
        )


def test_work_order_result_is_written_only_to_customer_notification_key(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr("app.Base.Client.redisClient.redis_client.client", client)

    handled = consumer.handle_work_order_result(
        "work_order_result",
        {
            "event_id": "evt-3001",
            "order_id": 3001,
            "customer_id": 3,
            "status": "已完成",
            "reply": "理财顾问已完成您的服务请求。",
            "handler_id": 9,
            "handler_name": "胡晓东",
        },
        "result-trace-1",
    )

    assert handled is True
    key, serialized = client.lpush.call_args.args
    assert key == "notifications:user:3"
    notification = json.loads(serialized)
    assert notification["id"] == "evt-3001"
    assert notification["event_id"] == "evt-3001"
    assert notification["message"] == "理财顾问已完成您的服务请求。"
    assert notification["handler_id"] == 9
    assert notification["handler_name"] == "胡晓东"
    client.ltrim.assert_called_once_with(key, 0, 99)
    client.expire.assert_called_once_with(key, 7 * 24 * 3600)


def test_profile_updated_publishes_auditable_refresh_request(monkeypatch):
    client = MagicMock()
    client.get.return_value = None
    monkeypatch.setattr("app.Base.Client.redisClient.redis_client.client", client)
    publish = MagicMock(return_value="123-0")
    monkeypatch.setattr(consumer.EventBus, "publish", publish)

    handled = consumer.handle_profile_updated(
        "profile_updated",
        {
            "customer_id": 3,
            "updated_fields": {"risk_score": 72.0, "risk_level": "C4"},
            "update_reason": "risk_reassessment",
        },
        "trace-profile-1",
    )

    assert handled is True
    publish.assert_called_once()
    assert publish.call_args.kwargs == {
        "stream_key": "stream:recommendation_refresh",
        "event_type": "recommendation_refresh_requested",
        "payload": {
            "event_id": "recommendation-refresh:trace-profile-1",
            "customer_id": 3,
            "profile_event_trace_id": "trace-profile-1",
            "updated_fields": ["risk_level", "risk_score"],
            "update_reason": "risk_reassessment",
            "status": "pending",
        },
        "source_agent": "profile_updated_consumer",
        "trace_id": "trace-profile-1",
    }
    assert client.setex.call_count == 2
    final_state = json.loads(client.setex.call_args.args[2])
    assert final_state["status"] == "published"
    assert final_state["message_id"] == "123-0"


def test_profile_updated_replay_skips_already_published_refresh(monkeypatch):
    client = MagicMock()
    client.get.return_value = json.dumps({"status": "published"})
    monkeypatch.setattr("app.Base.Client.redisClient.redis_client.client", client)
    publish = MagicMock()
    monkeypatch.setattr(consumer.EventBus, "publish", publish)

    handled = consumer.handle_profile_updated(
        "profile_updated",
        {
            "customer_id": 3,
            "updated_fields": {"risk_level": "C4"},
            "update_reason": "manual",
        },
        "trace-profile-1",
    )

    assert handled is True
    publish.assert_not_called()
    client.setex.assert_not_called()


def test_profile_updated_keeps_pending_state_when_refresh_publish_fails(monkeypatch):
    client = MagicMock()
    client.get.return_value = None
    monkeypatch.setattr("app.Base.Client.redisClient.redis_client.client", client)
    monkeypatch.setattr(consumer.EventBus, "publish", MagicMock(side_effect=RuntimeError("redis down")))

    handled = consumer.handle_profile_updated(
        "profile_updated",
        {
            "customer_id": 3,
            "updated_fields": {"risk_level": "C4"},
            "update_reason": "manual",
        },
        "trace-profile-failed",
    )

    assert handled is False
    assert client.setex.call_count == 1
    pending_state = json.loads(client.setex.call_args.args[2])
    assert pending_state["status"] == "pending"


def test_publish_serializes_standard_event_envelope():
    payload = {
        "customer_id": 1,
        "transaction_id": 1001,
        "amount": "100000.00",
        "transaction_type": "申购",
    }

    with patch(
        "app.WealthButler.EventBus.eventBus.redis_client.client.xadd",
        return_value="1-0",
    ) as xadd:
        message_id = EventBus.publish(
            stream_key="stream:large_transaction",
            event_type="large_transaction",
            payload=payload,
            source_agent="operator_agent",
            trace_id="trace-1",
        )

    assert message_id == "1-0"
    stream_key, envelope = xadd.call_args.args
    assert stream_key == "stream:large_transaction"
    assert envelope["event_type"] == "large_transaction"
    assert envelope["source_agent"] == "operator_agent"
    assert envelope["trace_id"] == "trace-1"
    assert json.loads(envelope["payload"]) == payload
    assert xadd.call_args.kwargs == {"maxlen": 10000, "approximate": True}


def _valid_suspicious_fields():
    return {
        "event_type": "suspicious_intent",
        "payload": json.dumps({
            "customer_id": 1,
            "session_id": "session-test",
            "intent_type": "fraud",
            "confidence": "0.90",
        }),
        "trace_id": "trace-test",
    }


def test_process_message_marks_processed_only_after_handler_success(monkeypatch):
    client = MagicMock()
    client.get.return_value = None
    client.set.return_value = True
    pipeline = client.pipeline.return_value
    monkeypatch.setattr("app.WealthButler.EventBus.eventBus.redis_client.client", client)

    completed = EventBus._process_message(
        "stream:suspicious_intent", "risk_monitor_group", "1-0",
        _valid_suspicious_fields(), lambda *_args: True,
    )

    assert completed is True
    client.set.assert_called_once_with(
        "eventbus:processing:trace-test", ANY, nx=True, ex=60,
    )
    pipeline.set.assert_called_once_with(
        "eventbus:processed:trace-test", "1", ex=86400,
    )
    pipeline.xack.assert_called_once_with(
        "stream:suspicious_intent", "risk_monitor_group", "1-0",
    )


def test_process_message_handler_failure_stays_pending_and_has_stable_dlq(monkeypatch):
    client = MagicMock()
    client.get.return_value = None
    client.set.side_effect = [True, True]  # processing lock, DLQ dedupe marker
    monkeypatch.setattr("app.WealthButler.EventBus.eventBus.redis_client.client", client)

    completed = EventBus._process_message(
        "stream:suspicious_intent", "risk_monitor_group", "2-0",
        _valid_suspicious_fields(), lambda *_args: False,
    )

    assert completed is False
    client.xack.assert_not_called()
    _, dlq_fields = client.xadd.call_args.args
    assert dlq_fields["error_code"] == "HANDLER_REJECTED"
    assert dlq_fields["error_type"] == "BusinessHandlerRejected"
    assert not client.pipeline.called


def test_process_message_processing_lock_prevents_concurrent_handler(monkeypatch):
    client = MagicMock()
    client.get.return_value = None
    client.set.return_value = False
    handler = MagicMock(return_value=True)
    monkeypatch.setattr("app.WealthButler.EventBus.eventBus.redis_client.client", client)

    completed = EventBus._process_message(
        "stream:suspicious_intent", "risk_monitor_group", "3-0",
        _valid_suspicious_fields(), handler,
    )

    assert completed is False
    handler.assert_not_called()
    client.xack.assert_not_called()
    client.xadd.assert_not_called()


def test_process_message_failure_can_replay_then_mark_success(monkeypatch):
    client = MagicMock()
    client.get.side_effect = [None, None]
    client.set.side_effect = [True, True, True]  # first lock, DLQ marker, replay lock
    handler = MagicMock(side_effect=[False, True])
    monkeypatch.setattr("app.WealthButler.EventBus.eventBus.redis_client.client", client)

    first = EventBus._process_message(
        "stream:suspicious_intent", "risk_monitor_group", "5-0",
        _valid_suspicious_fields(), handler,
    )
    second = EventBus._process_message(
        "stream:suspicious_intent", "risk_monitor_group", "5-0",
        _valid_suspicious_fields(), handler,
    )

    assert first is False
    assert second is True
    assert handler.call_count == 2
    client.pipeline.return_value.set.assert_called_once_with(
        "eventbus:processed:trace-test", "1", ex=86400,
    )
    client.pipeline.return_value.xack.assert_called_once()


def test_process_message_schema_failure_is_terminal_and_sanitized(monkeypatch):
    client = MagicMock()
    client.set.return_value = True
    monkeypatch.setattr("app.WealthButler.EventBus.eventBus.redis_client.client", client)
    fields = _valid_suspicious_fields()
    fields["payload"] = json.dumps({"customer_id": 1, "secret": "do-not-log"})

    completed = EventBus._process_message(
        "stream:suspicious_intent", "risk_monitor_group", "4-0", fields,
        MagicMock(return_value=True),
    )

    assert completed is True
    client.xack.assert_called_once()
    _, dlq_fields = client.xadd.call_args.args
    assert dlq_fields["error_code"] == "SCHEMA_VALIDATION_FAILED"
    assert dlq_fields["error_type"] == "ValidationError"
    assert "do-not-log" not in dlq_fields["error"]


def test_consume_honors_stop_event_during_idle_read(monkeypatch):
    """空闲消费者应在停止信号后结束，避免应用关闭残留线程。"""
    stop_event = threading.Event()
    calls = []

    monkeypatch.setattr(EventBus, "create_consumer_group", lambda *_args: None)

    def xreadgroup(*_args, **kwargs):
        calls.append(kwargs.get("block"))
        if kwargs.get("block") is not None:
            stop_event.set()
        return []

    monkeypatch.setattr(
        "app.WealthButler.EventBus.eventBus.redis_client.client.xreadgroup",
        xreadgroup,
    )

    EventBus.consume(
        "stream:test",
        "group:test",
        "worker:test",
        lambda *_args: True,
        block_ms=5000,
        stop_event=stop_event,
    )

    assert calls == [None, 1000]


def test_consumer_start_is_idempotent_and_stop_joins_threads(monkeypatch):
    """重复启动不增加消费者，停止后线程全部退出。"""
    monkeypatch.setattr(
        consumer,
        "CONSUMER_CONFIGS",
        [{
            "stream_key": "stream:test",
            "consumer_group": "group:test",
            "consumer_name": "worker:test",
            "handler_name": "handler:test",
        }],
    )
    monkeypatch.setattr(consumer, "HANDLERS", {"handler:test": lambda *_args: True})

    def consume(*_args, stop_event=None, **_kwargs):
        while not stop_event.wait(0.01):
            pass

    monkeypatch.setattr(consumer.EventBus, "consume", consume)
    consumer.stop_all_consumers()

    first = consumer.start_all_consumers()
    second = consumer.start_all_consumers()
    assert first == second
    assert len(first) == 1
    assert first[0].is_alive()

    assert consumer.stop_all_consumers() == ()
    assert not first[0].is_alive()
