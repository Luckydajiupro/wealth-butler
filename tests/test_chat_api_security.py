"""聊天 API 的认证、授权和错误脱敏回归测试。

这些测试不启动 ``WealthButler.main``，也不创建真实 Agent；所有业务身份、
RBAC 查询和流式 Agent 调用均使用进程内替身，确保不依赖数据库或网络。
"""

from __future__ import annotations

import asyncio
import importlib
import socket
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def chat_api():
    # 部分脚手架模块在导入时会探测基础设施；阻断 socket.connect，保证测试
    # 收集阶段也不会触达外部 Redis/MySQL 等服务。
    with patch.object(socket.socket, "connect", side_effect=OSError("network disabled in test")):
        return importlib.import_module("app.WealthButler.Api.chatApi")


@pytest.fixture()
def app(chat_api):
    test_app = FastAPI()
    chat_api.register_wealth_chat_router(test_app)
    return test_app


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def _user(user_id: int = 42):
    return SimpleNamespace(id=user_id, source_module="fin", status="active")


@contextmanager
def _authenticated_as(app, chat_api, current_user):
    app.dependency_overrides[chat_api.get_authenticated_chat_user] = lambda: current_user
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def _set_business_identity(
    monkeypatch,
    chat_api,
    user_type: str,
    employee_role: str | None = None,
) -> None:
    monkeypatch.setattr(
        chat_api.BaseUserExtModel,
        "get_by_id",
        classmethod(
            lambda cls, user_id: SimpleNamespace(
                user_type=user_type,
                employee_role=employee_role,
            )
        ),
    )


def _set_permissions(monkeypatch, chat_api, permissions: set[str]) -> None:
    monkeypatch.setattr(
        chat_api.AuthService,
        "has_permission",
        classmethod(lambda cls, user_id, permission, source_module=None: permission in permissions),
    )
    monkeypatch.setattr(
        chat_api.AuthService,
        "get_user_permissions",
        classmethod(lambda cls, user_id, source_module=None: list(permissions)),
    )


def _replace_agent_stream(monkeypatch, chat_api) -> None:
    async def fake_route(**kwargs):
        yield "ok"

    monkeypatch.setattr(chat_api.ChatService, "route_to_agent", fake_route)


def _allow_advisor_customer_scope(monkeypatch):
    from app.WealthButler.Service.advisorService import AdvisorService

    monkeypatch.setattr(
        AdvisorService,
        "advisor_can_access_customer",
        staticmethod(lambda _advisor_id, _customer_id: True),
    )


def _allow_operator_customer_scope(monkeypatch, chat_api):
    monkeypatch.setattr(
        chat_api.OperatorAccessService,
        "can_access_customer",
        classmethod(lambda cls, _employee_id, _customer_id: True),
    )


def test_chat_routes_require_authentication(client):
    response = client.post("/api/chat/customer", json={"message": "你好"})

    assert response.status_code == 401
    assert response.json()["detail"] == "缺少认证信息"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/chat/advisor", {"message": "推荐产品", "customer_id": 9}),
        ("/api/chat/analyst", {"message": "统计客户数"}),
        ("/api/chat/operator", {"message": "发起申购", "customer_id": 9}),
    ],
)
def test_customer_cannot_access_employee_agents(
    app, client, chat_api, monkeypatch, path, body
):
    _set_business_identity(monkeypatch, chat_api, "CUSTOMER")
    with _authenticated_as(app, chat_api, _user(7)):
        response = client.post(path, json=body)

    assert response.status_code == 403
    assert response.json()["detail"] == "该 Agent 仅限员工访问"


@pytest.mark.parametrize(
    ("path", "body", "expected_detail"),
    [
        (
            "/api/chat/advisor",
            {"message": "推荐产品", "customer_id": 9},
            "缺少权限: product:recommend",
        ),
        (
            "/api/chat/analyst",
            {"message": "统计客户数"},
            "缺少权限: data:nl2sql_query",
        ),
        (
            "/api/chat/operator",
            {"message": "发起申购", "customer_id": 9},
            "缺少业务操作 Agent 权限",
        ),
    ],
)
def test_employee_permission_boundary_denies_missing_permissions(
    app, client, chat_api, monkeypatch, path, body, expected_detail
):
    role = "客户经理" if path == "/api/chat/operator" else None
    _set_business_identity(monkeypatch, chat_api, "EMPLOYEE", role)
    _set_permissions(monkeypatch, chat_api, set())
    with _authenticated_as(app, chat_api, _user()):
        response = client.post(path, json=body)

    assert response.status_code == 403
    assert response.json()["detail"] == expected_detail


def test_legacy_advisor_role_allows_advisor_chat_without_rbac_row(
    app, client, chat_api, monkeypatch
):
    _set_business_identity(monkeypatch, chat_api, "EMPLOYEE", "理财顾问")
    _set_permissions(monkeypatch, chat_api, set())
    _allow_advisor_customer_scope(monkeypatch)
    _replace_agent_stream(monkeypatch, chat_api)

    with _authenticated_as(app, chat_api, _user(42)):
        response = client.post(
            "/api/chat/advisor",
            json={"message": "你好", "customer_id": 9},
        )

    assert response.status_code == 200
    assert response.text == "data: ok\n\n"


def test_non_advisor_role_cannot_use_advisor_fallback(
    app, client, chat_api, monkeypatch
):
    _set_business_identity(monkeypatch, chat_api, "EMPLOYEE", "客户经理")
    _set_permissions(monkeypatch, chat_api, set())

    with _authenticated_as(app, chat_api, _user(42)):
        response = client.post(
            "/api/chat/advisor",
            json={"message": "你好", "customer_id": 9},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "缺少权限: product:recommend"


def test_advisor_requires_customer_id(app, client, chat_api, monkeypatch):
    _set_business_identity(monkeypatch, chat_api, "EMPLOYEE")
    _set_permissions(monkeypatch, chat_api, {"product:recommend"})
    with _authenticated_as(app, chat_api, _user()):
        response = client.post("/api/chat/advisor", json={"message": "执行请求"})

    assert response.status_code == 400
    assert "customer_id" in response.json()["detail"]


def test_operator_product_query_does_not_require_customer_id(
    app, client, chat_api, monkeypatch
):
    captured = {}

    async def fake_route(**kwargs):
        captured.update(kwargs)
        yield "ok"

    _set_business_identity(monkeypatch, chat_api, "EMPLOYEE", "客户经理")
    _set_permissions(monkeypatch, chat_api, {"product:query"})
    monkeypatch.setattr(chat_api.ChatService, "route_to_agent", fake_route)

    with _authenticated_as(app, chat_api, _user()):
        response = client.post(
            "/api/chat/operator",
            json={"message": "查询在售理财产品"},
        )

    assert response.status_code == 200
    assert response.text == "data: ok\n\n"
    assert captured["customer_id"] is None


def test_authorized_employee_agent_uses_authenticated_user_id(
    app, client, chat_api, monkeypatch
):
    captured = {}

    async def fake_route(**kwargs):
        captured.update(kwargs)
        yield "ok"

    _set_business_identity(monkeypatch, chat_api, "EMPLOYEE")
    _set_permissions(monkeypatch, chat_api, {"product:recommend"})
    _allow_advisor_customer_scope(monkeypatch)
    monkeypatch.setattr(chat_api.ChatService, "route_to_agent", fake_route)

    with _authenticated_as(app, chat_api, _user(42)):
        response = client.post(
            "/api/chat/advisor",
            json={"message": "推荐产品", "customer_id": 9, "user_id": 999},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == "data: ok\n\n"
    assert captured["user_id"] == 42
    assert captured["customer_id"] == 9


def test_advisor_cannot_query_customer_outside_service_scope(
    app, client, chat_api, monkeypatch
):
    from app.WealthButler.Service.advisorService import AdvisorService

    _set_business_identity(monkeypatch, chat_api, "EMPLOYEE")
    _set_permissions(monkeypatch, chat_api, {"product:recommend"})
    monkeypatch.setattr(
        AdvisorService,
        "advisor_can_access_customer",
        staticmethod(lambda _advisor_id, _customer_id: False),
    )

    with _authenticated_as(app, chat_api, _user(42)):
        response = client.post(
            "/api/chat/advisor",
            json={"message": "推荐产品", "customer_id": 9},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "该客户不在当前理财顾问的服务范围内"


def test_advisor_cannot_use_operator_even_with_stale_transaction_permission(
    app, client, chat_api, monkeypatch
):
    _set_business_identity(monkeypatch, chat_api, "EMPLOYEE", "理财顾问")
    _set_permissions(monkeypatch, chat_api, {"operation:purchase"})

    with _authenticated_as(app, chat_api, _user(42)):
        response = client.post(
            "/api/chat/operator",
            json={"message": "发起申购", "customer_id": 9},
        )

    assert response.status_code == 403
    assert "仅限客户经理或业务管理员" in response.json()["detail"]


def test_operator_cannot_access_customer_without_claimed_work_order(
    app, client, chat_api, monkeypatch
):
    _set_business_identity(monkeypatch, chat_api, "EMPLOYEE", "客户经理")
    _set_permissions(monkeypatch, chat_api, {"operation:purchase"})
    monkeypatch.setattr(
        chat_api.OperatorAccessService,
        "can_access_customer",
        classmethod(lambda cls, _employee_id, _customer_id: False),
    )

    with _authenticated_as(app, chat_api, _user(42)):
        response = client.post(
            "/api/chat/operator",
            json={"message": "发起申购", "customer_id": 9},
        )

    assert response.status_code == 403
    assert "请先领取对应工单" in response.json()["detail"]


def test_risk_chat_fails_closed_at_api_and_service(
    app, client, chat_api, monkeypatch
):
    _set_business_identity(monkeypatch, chat_api, "EMPLOYEE")
    _set_permissions(monkeypatch, chat_api, {"data:nl2sql_query"})

    with _authenticated_as(app, chat_api, _user()):
        response = client.post(
            "/api/chat",
            json={"message": "分析预警", "agent_type": "risk"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "风控监测 Agent 不提供对话入口"

    async def collect_service_response():
        return [
            chunk
            async for chunk in chat_api.ChatService.route_to_agent(
                agent_type="risk",
                message="分析预警",
                session_id="test",
                user_id=42,
            )
        ]

    chunks = asyncio.run(collect_service_response())
    assert len(chunks) == 1
    assert "RISK_CHAT_NOT_SUPPORTED" in chunks[0]


def test_operator_cannot_confirm_on_behalf_of_customer(
    app, client, chat_api, monkeypatch
):
    _set_business_identity(monkeypatch, chat_api, "EMPLOYEE", "客户经理")
    _set_permissions(monkeypatch, chat_api, {"operation:purchase"})

    with _authenticated_as(app, chat_api, _user(42)):
        response = client.post(
            "/api/chat/operator/confirm",
            json={"confirm_token": "confirm-1", "action": "confirm", "employee_id": 999},
        )

    assert response.status_code == 409
    assert "客户本人" in response.json()["detail"]


def test_operator_cancel_binds_authenticated_employee_id(
    app, client, chat_api, monkeypatch
):
    captured = {}

    def fake_confirm(**kwargs):
        captured.update(kwargs)
        return {"success": True, "code": "OK", "message": "已撤回"}

    _set_business_identity(monkeypatch, chat_api, "EMPLOYEE", "客户经理")
    _set_permissions(monkeypatch, chat_api, {"operation:purchase"})
    monkeypatch.setattr(chat_api.ChatService, "confirm_operator_action", fake_confirm)

    with _authenticated_as(app, chat_api, _user(42)):
        response = client.post(
            "/api/chat/operator/confirm",
            json={"confirm_token": "confirm-1", "action": "cancel", "employee_id": 999},
        )

    assert response.status_code == 200
    assert captured == {
        "employee_id": 42,
        "confirm_token": "confirm-1",
        "action": "cancel",
    }


def test_operator_can_read_customer_confirmation_status(
    app, client, chat_api, monkeypatch
):
    pending = SimpleNamespace(status="待确认", customer_id=9, result=None)
    runtime = SimpleNamespace(
        service=SimpleNamespace(
            confirmation_service=SimpleNamespace(get_pending=lambda _token: pending)
        )
    )
    _set_business_identity(monkeypatch, chat_api, "EMPLOYEE", "客户经理")
    _set_permissions(monkeypatch, chat_api, {"operation:purchase"})
    monkeypatch.setattr(chat_api.ChatService, "_operator_runtime", runtime)
    monkeypatch.setattr(
        chat_api.OperatorAccessService,
        "can_access_customer",
        classmethod(lambda cls, _employee_id, _customer_id: True),
    )

    with _authenticated_as(app, chat_api, _user(42)):
        response = client.get("/api/chat/operator/confirmations/confirm-1")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "待确认", "result": None}


def test_operator_reads_only_notifications_addressed_to_self(
    app, client, chat_api, monkeypatch
):
    import json

    values = [
        json.dumps({
            "id": "own-result",
            "type": "customer_confirmation_result",
            "operator_id": 42,
            "customer_id": 9,
        }),
        json.dumps({
            "id": "other-result",
            "type": "customer_confirmation_result",
            "operator_id": 88,
            "customer_id": 10,
        }),
    ]
    fake_client = SimpleNamespace(lrange=lambda key, start, end: values)
    _set_business_identity(monkeypatch, chat_api, "EMPLOYEE", "客户经理")
    _set_permissions(monkeypatch, chat_api, {"operation:purchase"})
    monkeypatch.setattr("app.Base.Client.redisClient.redis_client.client", fake_client)

    with _authenticated_as(app, chat_api, _user(42)):
        response = client.get("/api/chat/operator/notifications")

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1
    assert response.json()["data"]["items"][0]["id"] == "own-result"


def test_sse_wrapper_does_not_leak_internal_exception(chat_api):
    secret = "mysql://admin:super-secret@internal-db/wealth"

    async def failing_generator():
        yield "first"
        raise RuntimeError(secret)

    async def collect_events():
        return [event async for event in chat_api.sse_wrapper(failing_generator())]

    events = asyncio.run(collect_events())
    public_payload = b"".join(events).decode("utf-8")

    assert "first" in public_payload
    assert "服务暂时不可用" in public_payload
    assert secret not in public_payload
