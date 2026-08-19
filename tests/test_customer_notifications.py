import json
from types import SimpleNamespace

from app.WealthButler.Api import holdingsApi
from app.WealthButler.Service.chatService import ChatService
from app.WealthButler.Service.operatorContracts import OperationCommand
from app.WealthButler.Service.customerNotificationService import store_work_order_result_notification


def test_customer_notifications_returns_only_authenticated_customer_results(monkeypatch):
    monkeypatch.setattr(
        holdingsApi,
        "_get_customer",
        lambda _credentials: SimpleNamespace(id=7),
    )
    values = [
        json.dumps({
            "id": "trace-1",
            "event_id": "evt-1",
            "type": "work_order_result",
            "order_id": 31,
            "customer_id": 7,
            "status": "已完成",
            "message": "您的申购咨询已处理。",
            "handler_id": 9,
            "handler_name": "胡晓东",
            "trace_id": "trace-1",
            "created_at": "2026-08-17 10:00:00",
        }, ensure_ascii=False),
        json.dumps({
            "id": "trace-other",
            "type": "work_order_result",
            "order_id": 32,
            "customer_id": 8,
            "status": "已完成",
            "message": "不应返回",
        }, ensure_ascii=False),
        json.dumps({"id": "trace-internal", "type": "risk_alert", "customer_id": 7}),
        "not-json",
    ]
    client = SimpleNamespace(lrange=lambda key, start, end: values)
    monkeypatch.setattr("app.Base.Client.redisClient.redis_client.client", client)

    response = holdingsApi.get_customer_notifications(limit=50, credentials=object())

    assert response.status_code == 200
    assert response.data["total"] == 1
    assert response.data["items"] == [{
        "id": "evt-1",
        "event_id": "evt-1",
        "type": "work_order_result",
        "order_id": 31,
        "status": "已完成",
        "message": "您的申购咨询已处理。",
        "business_subtype": None,
        "session_id": None,
        "handler_id": 9,
        "handler_name": "胡晓东",
        "trace_id": "trace-1",
        "created_at": "2026-08-17 10:00:00",
    }]


def test_customer_notifications_uses_authenticated_customer_key(monkeypatch):
    monkeypatch.setattr(
        holdingsApi,
        "_get_customer",
        lambda _credentials: SimpleNamespace(id=12),
    )
    calls = []
    client = SimpleNamespace(
        lrange=lambda key, start, end: calls.append((key, start, end)) or []
    )
    monkeypatch.setattr("app.Base.Client.redisClient.redis_client.client", client)

    holdingsApi.get_customer_notifications(limit=20, credentials=object())

    assert calls == [("notifications:user:12", 0, 19)]


def test_customer_notifications_returns_compliance_evidence(monkeypatch):
    monkeypatch.setattr(holdingsApi, "_get_customer", lambda _credentials: SimpleNamespace(id=7))
    value = json.dumps({
        "id": "compliance-evidence:1",
        "type": "compliance_evidence",
        "customer_id": 7,
        "operator_id": 8,
        "operator_name": "胡晓东",
        "message": "客户经理已完成测试双录并归档合规证据。",
    }, ensure_ascii=False)
    monkeypatch.setattr("app.Base.Client.redisClient.redis_client.client", SimpleNamespace(lrange=lambda *_: [value]))
    result = holdingsApi.get_customer_notifications(limit=20, credentials=object())
    assert result.data["items"][0]["type"] == "compliance_evidence"
    assert result.data["items"][0]["operator_name"] == "胡晓东"


def test_customer_notifications_drops_and_cleans_stale_confirmation(monkeypatch):
    monkeypatch.setattr(holdingsApi, "_get_customer", lambda _credentials: SimpleNamespace(id=7))
    stale = json.dumps({
        "id": "operation-confirmation:stale",
        "type": "operation_confirmation",
        "customer_id": 7,
        "confirm_token": "stale-token",
        "status": "待确认",
    }, ensure_ascii=False)
    calls = []
    client = SimpleNamespace(
        lrange=lambda *_: [stale],
        lrem=lambda *args: calls.append(args),
    )
    monkeypatch.setattr("app.Base.Client.redisClient.redis_client.client", client)
    monkeypatch.setattr(
        "app.WealthButler.Service.chatService.ChatService._operator_runtime",
        SimpleNamespace(service=SimpleNamespace(confirmation_service=SimpleNamespace(get_pending=lambda _token: None))),
    )

    result = holdingsApi.get_customer_notifications(limit=20, credentials=object())

    assert result.data == {"items": [], "total": 0}
    assert calls == [("notifications:user:7", 0, stale)]


def test_customer_notifications_keeps_live_confirmation(monkeypatch):
    monkeypatch.setattr(holdingsApi, "_get_customer", lambda _credentials: SimpleNamespace(id=7))
    value = json.dumps({
        "id": "operation-confirmation:live",
        "type": "operation_confirmation",
        "customer_id": 7,
        "confirm_token": "live-token",
        "operator_id": 8,
        "operation_intent": "申购",
        "operation_params": {"amount": 1000},
        "status": "待确认",
    }, ensure_ascii=False)
    client = SimpleNamespace(lrange=lambda *_: [value], lrem=lambda *_: None)
    monkeypatch.setattr("app.Base.Client.redisClient.redis_client.client", client)
    pending = SimpleNamespace(status="待确认")
    monkeypatch.setattr(
        "app.WealthButler.Service.chatService.ChatService._operator_runtime",
        SimpleNamespace(service=SimpleNamespace(confirmation_service=SimpleNamespace(get_pending=lambda _token: pending))),
    )

    result = holdingsApi.get_customer_notifications(limit=20, credentials=object())

    assert result.data["total"] == 1
    assert result.data["items"][0]["confirm_token"] == "live-token"
    assert result.data["items"][0]["operator_id"] == 8


def test_operator_confirmation_notification_targets_customer_and_identifies_operator(monkeypatch):
    calls = []
    client = SimpleNamespace(
        lpush=lambda *args: calls.append(("lpush", *args)),
        ltrim=lambda *args: calls.append(("ltrim", *args)),
    )
    monkeypatch.setattr("app.Base.Client.redisClient.redis_client.client", client)
    pending = SimpleNamespace(
        token="token-1",
        employee_id=8,
        status="待确认",
        command=OperationCommand("purchase", {"product_id": 3, "amount": "5000"}),
        created_at=SimpleNamespace(isoformat=lambda: "2026-08-19T12:00:00"),
        expires_at=SimpleNamespace(isoformat=lambda: "2026-08-19T12:10:00"),
    )

    ChatService._publish_customer_confirmation(7, pending)

    assert calls[0][0:2] == ("lpush", "notifications:user:7")
    payload = json.loads(calls[0][2])
    assert payload["customer_id"] == 7
    assert payload["operator_id"] == 8
    assert payload["status"] == "待确认"
    assert calls[1] == ("ltrim", "notifications:user:7", 0, 199)


def test_customer_confirmation_result_notifies_originating_operator(monkeypatch):
    calls = []
    client = SimpleNamespace(
        lpush=lambda *args: calls.append(("lpush", *args)),
        ltrim=lambda *args: calls.append(("ltrim", *args)),
        lrange=lambda *_: [],
    )
    monkeypatch.setattr("app.Base.Client.redisClient.redis_client.client", client)
    monkeypatch.setattr(
        holdingsApi,
        "_get_customer",
        lambda _credentials: SimpleNamespace(id=7, username="测试客户"),
    )
    pending = SimpleNamespace(customer_id=7, employee_id=8)
    runtime = SimpleNamespace(
        service=SimpleNamespace(
            confirmation_service=SimpleNamespace(get_pending=lambda _token: pending)
        ),
        confirm=lambda employee_id, token, action: {
            "success": True,
            "message": "交易已完成",
            "data": {"transaction_id": 123},
        },
    )
    monkeypatch.setattr(
        "app.WealthButler.Service.chatService.ChatService._operator_runtime",
        runtime,
    )

    result = holdingsApi.confirm_customer_operation(
        "confirm-1",
        holdingsApi.CustomerOperationConfirmRequest(action="confirm"),
        credentials=object(),
    )

    assert result.status_code == 200
    assert calls[0][0:2] == ("lpush", "notifications:operator:8")
    payload = json.loads(calls[0][2])
    assert payload["type"] == "customer_confirmation_result"
    assert payload["operator_id"] == 8
    assert payload["customer_id"] == 7
    assert payload["action"] == "confirm"
    assert calls[1] == ("ltrim", "notifications:operator:8", 0, 199)


def test_workorder_result_notification_is_immediate_and_idempotent(monkeypatch):
    calls = []
    inserted = [True, False]
    client = SimpleNamespace(
        set=lambda *args, **kwargs: inserted.pop(0),
        lpush=lambda *args: calls.append(("lpush", *args)),
        ltrim=lambda *args: calls.append(("ltrim", *args)),
        expire=lambda *args: calls.append(("expire", *args)),
        delete=lambda *args: calls.append(("delete", *args)),
    )
    monkeypatch.setattr("app.Base.Client.redisClient.redis_client.client", client)
    payload = {
        "event_id": "workorder-result-1",
        "order_id": 449,
        "customer_id": 3665,
        "business_subtype": "申购",
        "status": "已关闭",
        "reply": "工单已关闭。关闭原因：可用余额不足",
        "handler_id": 3662,
        "handler_name": "胡晓东",
    }

    assert store_work_order_result_notification(payload, "trace-1") is True
    assert store_work_order_result_notification(payload, "trace-1") is False

    pushes = [call for call in calls if call[0] == "lpush"]
    assert len(pushes) == 1
    assert pushes[0][1] == "notifications:user:3665"
    notification = json.loads(pushes[0][2])
    assert notification["status"] == "已关闭"
    assert "可用余额不足" in notification["message"]
