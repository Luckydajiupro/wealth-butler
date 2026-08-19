"""正式 Operator Runtime 的生产资源装配与生命周期管理。"""

from __future__ import annotations

import importlib
import inspect
import json
import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Optional
from uuid import uuid4

from app.WealthButler.runtimeConfig import OperatorRuntimeConfig


logger = logging.getLogger(__name__)
_REQUIRED_TRANSACTION_COLUMNS = {"employee_id", "trace_id", "idempotency_key"}
_REQUIRED_AUDIT_COLUMNS = {
    "audit_event_id", "trace_id", "employee_id", "customer_id", "intent",
    "parameter_names", "success", "result_code",
}


def load_configured_callable(path: str) -> Callable[..., Any]:
    """加载显式配置的 ``module:attribute`` callable，不提供隐式默认实现。"""
    module_name, separator, attribute_path = path.partition(":")
    if not separator or not module_name.strip() or not attribute_path.strip():
        raise ValueError(f"Loader 路径必须使用 module:attribute 格式: {path!r}")
    target: Any = importlib.import_module(module_name.strip())
    for attribute in attribute_path.strip().split("."):
        if not attribute or attribute.startswith("_"):
            raise ValueError(f"Loader 属性路径不合法: {path!r}")
        target = getattr(target, attribute)
    if not callable(target):
        raise TypeError(f"配置的 Loader 不可调用: {path!r}")
    return target


def create_mysql_connection_provider(
    config: OperatorRuntimeConfig,
    connect: Optional[Callable[..., Any]] = None,
) -> Callable[[], Any]:
    """创建每次返回 DictCursor、关闭自动提交的新连接 Provider。"""
    if connect is None:
        import pymysql

        connect = pymysql.connect

    def provide() -> Any:
        import pymysql

        return connect(
            host=config.mysql_host,
            port=config.mysql_port,
            user=config.mysql_user,
            password=config.mysql_password,
            database=config.mysql_database,
            charset=config.mysql_charset,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
            connect_timeout=config.mysql_connect_timeout,
        )

    return provide


def verify_operator_schema(connection_provider: Callable[[], Any]) -> None:
    """启动时验证 mapping cursor、事务模式及 Operator 必需迁移。"""
    connection = connection_provider()
    cursor = None
    try:
        get_autocommit = getattr(connection, "get_autocommit", None)
        if not callable(get_autocommit) or get_autocommit() is not False:
            raise RuntimeError("Operator MySQL 连接必须设置 autocommit=False")
        cursor = connection.cursor()
        cursor.execute("SELECT 1 AS health")
        row = cursor.fetchone()
        if not isinstance(row, Mapping) or row.get("health") != 1:
            raise RuntimeError("Operator MySQL 连接必须使用 mapping cursor")

        cursor.execute(
            "SELECT `TABLE_NAME`, `COLUMN_NAME` FROM information_schema.COLUMNS "
            "WHERE `TABLE_SCHEMA` = %s AND `TABLE_NAME` IN (%s, %s)",
            (config_database(connection), "fin_transaction", "biz_operation_audit"),
        )
        columns: dict[str, set[str]] = {}
        for item in cursor.fetchall() or []:
            if not isinstance(item, Mapping):
                raise RuntimeError("Operator Schema 检查必须返回 mapping row")
            columns.setdefault(str(item.get("TABLE_NAME")), set()).add(str(item.get("COLUMN_NAME")))
        missing_transaction = _REQUIRED_TRANSACTION_COLUMNS - columns.get("fin_transaction", set())
        missing_audit = _REQUIRED_AUDIT_COLUMNS - columns.get("biz_operation_audit", set())
        if missing_transaction or missing_audit:
            details = []
            if missing_transaction:
                details.append("fin_transaction:" + ",".join(sorted(missing_transaction)))
            if missing_audit:
                details.append("biz_operation_audit:" + ",".join(sorted(missing_audit)))
            raise RuntimeError("Operator Schema 迁移未完成: " + "; ".join(details))
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def config_database(connection: Any) -> str:
    """从 PyMySQL 连接取得当前库名，不把配置或凭证写入日志。"""
    database = getattr(connection, "db", None)
    if isinstance(database, bytes):
        database = database.decode("utf-8")
    if not isinstance(database, str) or not database:
        raise RuntimeError("Operator MySQL 连接未选择数据库")
    return database


class RedisStreamEventBus:
    """复用已建立的 Redis 客户端发布 Stream，避免导入全局 Redis 单例。"""

    def __init__(self, redis_client: Any):
        self.redis = redis_client

    def publish(
        self,
        stream_key: str,
        event_type: str,
        payload: dict,
        source_agent: str = "unknown",
        trace_id: Optional[str] = None,
        maxlen: int = 10000,
    ) -> Any:
        return self.redis.xadd(
            stream_key,
            {
                "event_type": event_type,
                "payload": json.dumps(payload, ensure_ascii=False),
                "timestamp": str(int(time.time() * 1000)),
                "trace_id": trace_id or str(uuid4()),
                "source_agent": source_agent,
            },
            maxlen=maxlen,
            approximate=True,
        )


class RedisStreamRetryConsumer:
    """用显式 Redis 连接消费 Operator 补发队列，并支持生命周期停止。"""

    STREAM_KEY = "stream:large_transaction:retry"
    CONSUMER_GROUP = "operator_retry_group"
    CONSUMER_NAME = "operator-retry-worker-1"

    def __init__(self, redis_client: Any, handler: Callable[[str, dict, str], bool]):
        self.redis = redis_client
        self.handler = handler
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> threading.Thread:
        """幂等启动守护线程；消费组创建失败时让应用启动失败。"""
        if self._thread is not None and self._thread.is_alive():
            return self._thread
        try:
            self.redis.xgroup_create(
                self.STREAM_KEY,
                self.CONSUMER_GROUP,
                id="0",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self.consume,
            daemon=True,
            name=f"EventBus-{self.CONSUMER_NAME}",
        )
        self._thread.start()
        return self._thread

    @staticmethod
    def _text(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    def _process_message(self, message_id: Any, fields: Mapping[str, Any]) -> None:
        normalized = {self._text(key): self._text(value) for key, value in fields.items()}
        try:
            payload = json.loads(normalized.get("payload", "{}"))
            success = self.handler(
                normalized.get("event_type", ""),
                payload,
                normalized.get("trace_id", ""),
            )
            if not success:
                self.redis.xadd(
                    f"{self.STREAM_KEY}:dead_letter",
                    {
                        "original_stream": self.STREAM_KEY,
                        "original_msg_id": self._text(message_id),
                        "event_type": normalized.get("event_type", ""),
                        "payload": normalized.get("payload", ""),
                        "trace_id": normalized.get("trace_id", ""),
                        "error": "retry handler returned false",
                    },
                )
            self.redis.xack(self.STREAM_KEY, self.CONSUMER_GROUP, message_id)
        except json.JSONDecodeError as exc:
            # 无法解析的信封不会因重放而恢复，转入死信队列后 ACK，避免永久阻塞 PEL。
            self.redis.xadd(
                f"{self.STREAM_KEY}:dead_letter",
                {
                    "original_stream": self.STREAM_KEY,
                    "original_msg_id": self._text(message_id),
                    "payload": normalized.get("payload", ""),
                    "error": f"JSONDecodeError: {exc}",
                },
            )
            self.redis.xack(self.STREAM_KEY, self.CONSUMER_GROUP, message_id)
        except Exception:
            # 重放或发布失败时不 ACK，保留在 PEL，等待服务重启后再次处理。
            logger.exception("Operator retry event processing failed: %s", message_id)

    def consume(self) -> None:
        pending = True
        while not self._stop_event.is_set():
            try:
                messages = self.redis.xreadgroup(
                    self.CONSUMER_GROUP,
                    self.CONSUMER_NAME,
                    {self.STREAM_KEY: "0" if pending else ">"},
                    count=10,
                    block=1000,
                )
                if pending and not messages:
                    pending = False
                    continue
                for _, items in messages or []:
                    for message_id, fields in items:
                        self._process_message(message_id, fields)
            except Exception:
                if not self._stop_event.is_set():
                    logger.exception("Operator retry consumer read failed")
                    time.sleep(1)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)


@dataclass
class OperatorRuntimeResources:
    runtime: Any
    redis_client: Any
    llm: Any
    event_publisher: Any = None
    retry_consumer: Optional[RedisStreamRetryConsumer] = None

    def start_retry_consumer(self) -> threading.Thread:
        """仅为正式装配的 Publisher 启动补发消费者。"""
        if getattr(self.runtime, "runtime_mode", None) != "real" or self.event_publisher is None:
            raise RuntimeError("Operator 补发消费者只能绑定正式 Runtime")
        if self.retry_consumer is None:
            self.retry_consumer = RedisStreamRetryConsumer(
                self.redis_client,
                self.event_publisher.handle_retry_event,
            )
        return self.retry_consumer.start()

    async def close(self) -> None:
        """解除 Runtime 并关闭本装配持有的 Redis/LLM 客户端。"""
        from app.WealthButler.Service.chatService import ChatService

        if ChatService._operator_runtime is self.runtime:
            ChatService.configure_operator_runtime(None)
        if self.retry_consumer is not None:
            self.retry_consumer.stop()
        for client_name in ("model_client", "async_model_client"):
            client = getattr(self.llm, client_name, None)
            close = getattr(client, "close", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
        close_redis = getattr(self.redis_client, "close", None)
        if callable(close_redis):
            result = close_redis()
            if inspect.isawaitable(result):
                await result
        pool = getattr(self.redis_client, "connection_pool", None)
        disconnect = getattr(pool, "disconnect", None)
        if callable(disconnect):
            disconnect()


async def build_operator_runtime_resources(
    config: OperatorRuntimeConfig,
    *,
    mysql_connect: Optional[Callable[..., Any]] = None,
    redis_factory: Optional[Callable[..., Any]] = None,
    llm_factory: Optional[Callable[..., Any]] = None,
    runtime_builder: Optional[Callable[..., Any]] = None,
) -> OperatorRuntimeResources:
    """建立并验证正式资源；任一步失败均关闭已创建资源后重新抛出。"""
    if not config.enabled:
        raise ValueError("正式 Operator Runtime 开关未启用")
    evidence_loader = load_configured_callable(config.compliance_evidence_loader)
    holding_loader = load_configured_callable(config.holding_summary_loader)
    payee_verifier = load_configured_callable(config.payee_verifier)
    connection_provider = create_mysql_connection_provider(config, mysql_connect)
    verify_operator_schema(connection_provider)

    redis_client = None
    llm = None
    try:
        if redis_factory is None:
            import redis

            redis_factory = redis.Redis
        redis_client = redis_factory(
            host=config.redis_host,
            port=config.redis_port,
            db=config.redis_db,
            password=config.redis_password,
            decode_responses=True,
            socket_timeout=config.redis_socket_timeout,
            socket_connect_timeout=config.redis_socket_timeout,
        )
        if redis_client.ping() is not True:
            raise RuntimeError("Operator Redis 健康检查失败")

        if llm_factory is None:
            from app.Base.Ai.llms.deepseekLlm import DeepSeekLlm

            llm_factory = DeepSeekLlm
        llm = llm_factory(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
            timeout=config.llm_timeout,
        )
        from app.WealthButler.Tools.nl2apiTool import LLMIntentParser
        from app.WealthButler.EventBus.schemas import validate_event
        from app.WealthButler.Service.operatorMySQLTransactionGateway import MySQLTransactionGateway
        from app.WealthButler.Service.operatorWriteAdapters import (
            AuthCustomerInfoGateway,
            EventBusPublisherGateway,
            ModelWorkOrderGateway,
            MySQLOperationAuditGateway,
            RepositoryRiskAlertGateway,
            ServiceRiskAssessmentGateway,
        )
        if runtime_builder is None:
            from app.WealthButler.Service.operatorRuntimeBuilder import create_real_runtime

            runtime_builder = create_real_runtime
        event_publisher = EventBusPublisherGateway(
            event_bus=RedisStreamEventBus(redis_client),
            validator=validate_event,
        )
        runtime = runtime_builder(
            intent_parser=LLMIntentParser(llm),
            redis_client=redis_client,
            transaction_gateway=MySQLTransactionGateway(connection_provider),
            work_order_gateway=ModelWorkOrderGateway(),
            risk_assessment_gateway=ServiceRiskAssessmentGateway(),
            customer_info_gateway=AuthCustomerInfoGateway(),
            risk_alert_gateway=RepositoryRiskAlertGateway(),
            event_publisher=event_publisher,
            operation_audit_gateway=MySQLOperationAuditGateway(connection_provider),
            compliance_evidence_loader=evidence_loader,
            holding_summary_loader=holding_loader,
            payee_verifier=payee_verifier,
        )
        if getattr(runtime, "runtime_mode", None) != "real":
            raise RuntimeError("Operator 生产装配返回了非 real Runtime")
        return OperatorRuntimeResources(
            runtime=runtime,
            redis_client=redis_client,
            llm=llm,
            event_publisher=event_publisher,
        )
    except Exception:
        await OperatorRuntimeResources(
            runtime=None,
            redis_client=redis_client,
            llm=llm,
        ).close()
        raise


__all__ = [
    "OperatorRuntimeResources",
    "RedisStreamRetryConsumer",
    "build_operator_runtime_resources",
    "create_mysql_connection_provider",
    "load_configured_callable",
    "verify_operator_schema",
]
