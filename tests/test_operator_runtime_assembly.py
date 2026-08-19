"""Operator 生产装配的离线生命周期测试。"""

from __future__ import annotations

import asyncio
import importlib
import socket
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pymysql
import pytest

from app.WealthButler.Service.operatorRuntimeAssembly import (
    OperatorRuntimeResources,
    RedisStreamRetryConsumer,
    build_operator_runtime_resources,
    create_mysql_connection_provider,
    verify_operator_schema,
)
from app.WealthButler.runtimeConfig import OperatorRuntimeConfig


def evidence_loader(customer_id, product_id):
    return {}


def holding_summary_loader(customer_id, risk_level):
    return {"total_value": "0", "risk_level_value": "0"}


def payee_verifier(customer_id, payee):
    return True


class SchemaCursor:
    def __init__(self):
        self.query = ""

    def execute(self, query, params=()):
        self.query = query

    def fetchone(self):
        return {"health": 1}

    def fetchall(self):
        transaction = [
            {"TABLE_NAME": "fin_transaction", "COLUMN_NAME": name}
            for name in ("employee_id", "trace_id", "idempotency_key")
        ]
        audit = [
            {"TABLE_NAME": "biz_operation_audit", "COLUMN_NAME": name}
            for name in (
                "audit_event_id", "trace_id", "employee_id", "customer_id",
                "intent", "parameter_names", "success", "result_code",
            )
        ]
        return transaction + audit

    def close(self):
        pass


class SchemaConnection:
    db = b"wealth_butler"

    def __init__(self):
        self.closed = False

    def get_autocommit(self):
        return False

    def cursor(self):
        return SchemaCursor()

    def close(self):
        self.closed = True


class StubRedis:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        self.connection_pool = SimpleNamespace(disconnect=lambda: None)

    def ping(self):
        return True

    def eval(self, *args):
        return 1

    def hget(self, *args):
        return None

    def delete(self, *args):
        return 1

    def xadd(self, *args, **kwargs):
        return "1-0"

    def close(self):
        self.closed = True


class RetryRedis(StubRedis):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.groups = []
        self.acks = []
        self.added = []

    def xgroup_create(self, *args, **kwargs):
        self.groups.append((args, kwargs))
        return True

    def xack(self, *args):
        self.acks.append(args)
        return 1

    def xadd(self, *args, **kwargs):
        self.added.append((args, kwargs))
        return "1-0"


class CloseableClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class StubLlm:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.model_client = CloseableClient()
        self.async_model_client = CloseableClient()

    def invoke(self, prompt, stream=False):
        return '{"intent":"product_query","confidence":1,"extracted_params":{}}'


def _config():
    module = __name__
    return OperatorRuntimeConfig(
        enabled=True,
        mysql_host="db.internal",
        mysql_user="wealth",
        mysql_password="secret",
        mysql_database="wealth_butler",
        redis_host="redis.internal",
        llm_api_key="llm-secret",
        llm_base_url="https://llm.internal/v1",
        llm_model="deepseek-chat",
        compliance_evidence_loader=f"{module}:evidence_loader",
        holding_summary_loader=f"{module}:holding_summary_loader",
        payee_verifier=f"{module}:payee_verifier",
    )


def test_connection_provider_uses_dict_cursor_and_disables_autocommit():
    captured = {}

    def connect(**kwargs):
        captured.update(kwargs)
        return SchemaConnection()

    provider = create_mysql_connection_provider(_config(), connect)
    connection = provider()

    assert captured["cursorclass"] is pymysql.cursors.DictCursor
    assert captured["autocommit"] is False
    assert captured["password"] == "secret"
    assert isinstance(connection, SchemaConnection)


def test_schema_verification_requires_mapping_cursor_and_migration_columns():
    connection = SchemaConnection()

    verify_operator_schema(lambda: connection)

    assert connection.closed is True


def test_production_assembly_builds_real_runtime_and_closes_resources():
    captured = {}

    def runtime_builder(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(runtime_mode="real")

    redis_instance = StubRedis()
    llm_instance = StubLlm()
    resources = asyncio.run(build_operator_runtime_resources(
        _config(),
        mysql_connect=lambda **kwargs: SchemaConnection(),
        redis_factory=lambda **kwargs: redis_instance,
        llm_factory=lambda **kwargs: llm_instance,
        runtime_builder=runtime_builder,
    ))

    assert resources.runtime.runtime_mode == "real"
    assert captured["redis_client"] is redis_instance
    assert captured["transaction_gateway"].__class__.__name__ == "MySQLTransactionGateway"
    assert captured["operation_audit_gateway"].__class__.__name__ == "MySQLOperationAuditGateway"

    asyncio.run(resources.close())
    assert redis_instance.closed is True
    assert llm_instance.model_client.closed is True
    assert llm_instance.async_model_client.closed is True


def test_production_assembly_rejects_non_real_runtime_and_closes_resources():
    redis_instance = StubRedis()
    llm_instance = StubLlm()

    with pytest.raises(RuntimeError, match="非 real Runtime"):
        asyncio.run(build_operator_runtime_resources(
            _config(),
            mysql_connect=lambda **kwargs: SchemaConnection(),
            redis_factory=lambda **kwargs: redis_instance,
            llm_factory=lambda **kwargs: llm_instance,
            runtime_builder=lambda **kwargs: SimpleNamespace(runtime_mode="fake"),
        ))

    assert redis_instance.closed is True
    assert llm_instance.model_client.closed is True
    assert llm_instance.async_model_client.closed is True


def test_retry_consumer_replays_with_real_handler_and_does_not_ack_failures():
    redis = RetryRedis()
    calls = []
    consumer = RedisStreamRetryConsumer(
        redis,
        lambda event_type, payload, trace_id: calls.append(
            (event_type, payload, trace_id)
        ) or True,
    )

    consumer._process_message(
        "1-0",
        {
            "event_type": "operator_event_retry",
            "payload": '{"original_stream":"stream:large_transaction"}',
            "trace_id": "trace-1",
        },
    )

    assert calls == [(
        "operator_event_retry",
        {"original_stream": "stream:large_transaction"},
        "trace-1",
    )]
    assert redis.acks == [(
        "stream:large_transaction:retry",
        "operator_retry_group",
        "1-0",
    )]

    failing = RedisStreamRetryConsumer(
        redis,
        lambda *_: (_ for _ in ()).throw(RuntimeError("publish failed")),
    )
    failing._process_message(
        "2-0",
        {"event_type": "operator_event_retry", "payload": "{}", "trace_id": "trace-2"},
    )
    assert len(redis.acks) == 1


def test_retry_consumer_start_is_idempotent(monkeypatch):
    redis = RetryRedis()

    class StubThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.alive = False

        def start(self):
            self.alive = True

        def is_alive(self):
            return self.alive

    monkeypatch.setattr(
        "app.WealthButler.Service.operatorRuntimeAssembly.threading.Thread",
        StubThread,
    )
    consumer = RedisStreamRetryConsumer(redis, lambda *_: True)

    first = consumer.start()
    second = consumer.start()

    assert first is second
    assert len(redis.groups) == 1


def test_importing_main_does_not_open_network_or_start_scheduler():
    sys.modules.pop("app.WealthButler.main", None)
    with patch.object(socket.socket, "connect", side_effect=AssertionError("network attempted")) as connect:
        module = importlib.import_module("app.WealthButler.main")

    assert module.app is not None
    connect.assert_not_called()
    assert not hasattr(module.app.state, "operator_runtime_mode")


def test_lifespan_starts_retry_consumer_only_for_real_runtime(monkeypatch):
    main = importlib.import_module("app.WealthButler.main")
    configured = []
    lifecycle = []

    class FakeChatService:
        _operator_runtime = None

        @classmethod
        def configure_operator_runtime(cls, runtime):
            cls._operator_runtime = runtime
            configured.append(runtime)

    runtime = SimpleNamespace(runtime_mode="real")

    class FakeResources:
        def __init__(self):
            self.runtime = runtime

        def start_retry_consumer(self):
            lifecycle.append("retry-start")

        async def close(self):
            lifecycle.append("resources-close")

    resources = FakeResources()

    async def build(_config):
        lifecycle.append("resources-build")
        return resources

    class FakeScheduler:
        def __init__(self):
            self.scheduler = SimpleNamespace(running=False)

        def start(self):
            self.scheduler.running = True
            lifecycle.append("scheduler-start")

        def shutdown(self, wait=False):
            self.scheduler.running = False
            lifecycle.append("scheduler-stop")

    scheduler = FakeScheduler()
    monkeypatch.setattr(main, "_register_routes_once", lambda app: None)
    monkeypatch.setattr(main, "load_operator_runtime_config", lambda: _config())
    monkeypatch.setattr(
        "app.WealthButler.Service.operatorRuntimeAssembly.build_operator_runtime_resources",
        build,
    )
    monkeypatch.setitem(
        sys.modules,
        "app.WealthButler.Service.chatService",
        SimpleNamespace(ChatService=FakeChatService),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.WealthButler.EventBus.consumer",
        SimpleNamespace(
            start_all_consumers=lambda: lifecycle.append("consumers-start"),
            stop_all_consumers=lambda: lifecycle.append("consumers-stop"),
        ),
    )
    monkeypatch.setattr(main, "_register_scheduler_modules_once", lambda: lifecycle.append("scheduler-register"))
    monkeypatch.setattr(main, "_assert_unique_scheduler_jobs", lambda client: lifecycle.append("scheduler-unique"))
    monkeypatch.setitem(
        sys.modules,
        "app.Base.Service.schedulerService",
        SimpleNamespace(get_base_module_scheduler_client=lambda: scheduler),
    )
    fake_app = SimpleNamespace(state=SimpleNamespace())

    async def run_lifespan():
        async with main.lifespan(fake_app):
            assert fake_app.state.operator_runtime_mode == "real"

    asyncio.run(run_lifespan())

    assert configured == [None, runtime]
    assert lifecycle == [
        "resources-build",
        "retry-start",
        "consumers-start",
        "scheduler-register",
        "scheduler-unique",
        "scheduler-start",
        "scheduler-stop",
        "consumers-stop",
        "resources-close",
    ]


def test_scheduler_duplicate_job_ids_fail_before_start():
    main = importlib.import_module("app.WealthButler.main")

    class DuplicateScheduler:
        scheduler = SimpleNamespace(
            get_jobs=lambda: [SimpleNamespace(id="risk_daily_scan"), SimpleNamespace(id="risk_daily_scan")]
        )

    with pytest.raises(RuntimeError, match="risk_daily_scan"):
        main._assert_unique_scheduler_jobs(DuplicateScheduler())


def test_business_user_extra_data_json_is_deserialized():
    from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel

    user = BaseUserExtModel(
        username="seed-user",
        password_hash="hash",
        extra_data='{"seed_namespace":"WB-SEED-20260817"}',
    )
    assert user.extra_data == {"seed_namespace": "WB-SEED-20260817"}


def test_main_routes_are_complete_unique_and_idempotent():
    from fastapi import FastAPI

    main = importlib.import_module("app.WealthButler.main")
    test_app = FastAPI()
    main._register_routes_once(test_app)
    route_count = len(test_app.routes)
    main._register_routes_once(test_app)

    assert len(test_app.routes) == route_count
    operations = []
    for route in test_app.routes:
        for method in getattr(route, "methods", ()):
            if method not in {"HEAD", "OPTIONS"}:
                operations.append((route.path, method))
    assert len(operations) == len(set(operations))
    paths = set(test_app.openapi()["paths"])
    assert {
        "/api/auth/login", "/api/chat", "/api/chat/customer", "/api/chat/advisor",
        "/api/chat/analyst", "/api/chat/operator", "/api/chat/operator/confirm",
        "/api/wealth/holdings", "/api/wealth/risk/alerts", "/api/wealth/workorder/list",
        "/api/compliance/evidence", "/api/compliance/payees/verify",
    } <= paths
