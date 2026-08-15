"""事件总线核心类 - Redis Streams 封装

基于 Redis Streams 实现的事件总线，支持跨 Agent 异步通信。
复用 Base.Client.redisClient，封装 XADD/XREADGROUP/XACK 操作。

架构设计文档 §2.4 - 跨Agent协作机制
"""
import json
import time
import uuid
import logging
from typing import Callable, Optional, Dict, Any
from app.Base.Client.redisClient import redis_client

logger = logging.getLogger(__name__)


class EventBus:
    """Redis Streams 事件总线封装

    职责：
    - 发布事件到 Redis Streams（XADD）
    - 消费事件（XREADGROUP + XACK）
    - 管理消费组（XGROUP CREATE）
    - 提供幂等性保证（at-least-once 投递）

    使用示例：
        # 发布事件
        EventBus.publish(
            stream_key='stream:large_transaction',
            event_type='product_purchased',
            payload={'customer_id': 123, 'amount': 50000}
        )

        # 消费事件
        def handler(event_type, payload, trace_id):
            print(f"处理事件: {event_type}, {payload}")
            return True  # 返回 True 表示处理成功

        EventBus.consume(
            stream_key='stream:large_transaction',
            consumer_group='risk_monitor_group',
            consumer_name='worker-1',
            handler=handler
        )
    """

    @staticmethod
    def publish(
        stream_key: str,
        event_type: str,
        payload: Dict[str, Any],
        source_agent: str = 'unknown',
        trace_id: Optional[str] = None,
        maxlen: int = 10000
    ) -> str:
        """发布事件到指定 Stream

        Args:
            stream_key: Stream 队列标识（如 stream:large_transaction）
            event_type: 事件类型（如 product_purchased）
            payload: 事件载荷（业务数据，必须可 JSON 序列化）
            source_agent: 发布者Agent名称（默认'unknown'）
            trace_id: 分布式跟踪 ID（可选，自动生成UUID）
            maxlen: Stream 最大长度（近似裁剪，避免内存无限增长）

        Returns:
            message_id: Redis Streams 消息 ID（如 1692345678901-0）

        Raises:
            TypeError: payload 不可 JSON 序列化
            redis.RedisError: Redis 连接或写入失败
        """
        if trace_id is None:
            trace_id = str(uuid.uuid4())

        # 构造事件消息
        event = {
            'event_type': event_type,
            'payload': json.dumps(payload, ensure_ascii=False),
            'timestamp': str(int(time.time() * 1000)),  # 毫秒时间戳字符串
            'trace_id': trace_id,
            'source_agent': source_agent
        }

        try:
            # XADD stream_key MAXLEN ~ maxlen * field1 value1 field2 value2 ...
            message_id = redis_client.client.xadd(
                stream_key,
                event,
                maxlen=maxlen,
                approximate=True  # 近似裁剪，性能更好
            )

            logger.info(
                f"[EventBus] Published {event_type} to {stream_key}, "
                f"msg_id={message_id}, trace_id={trace_id}"
            )

            return message_id

        except TypeError as e:
            logger.error(f"[EventBus] Payload not JSON serializable: {e}")
            raise
        except Exception as e:
            logger.error(f"[EventBus] Failed to publish to {stream_key}: {e}")
            raise

    @staticmethod
    def consume(
        stream_key: str,
        consumer_group: str,
        consumer_name: str,
        handler: Callable[[str, Dict[str, Any], str], bool],
        block_ms: int = 5000,
        count: int = 10
    ) -> None:
        """消费指定 Stream 的事件（阻塞式循环，常驻后台）

        Args:
            stream_key: Stream 队列标识
            consumer_group: 消费组名称
            consumer_name: 本消费者名称（单实例可用 "worker-1"）
            handler: 事件处理函数 (event_type, payload, trace_id) -> bool
                     返回 True 表示处理成功，False 表示失败（写入死信队列）
            block_ms: XREADGROUP 阻塞超时（毫秒），0 表示永久阻塞
            count: 每次拉取最多多少条消息

        注意：
            - 本方法会阻塞当前线程，应在独立线程中调用
            - 采用无条件ACK + 幂等检查机制（at-least-once语义）
            - 消费者重启时会先重放 Pending List 中的消息，再消费新消息
        """
        # 确保消费组存在（幂等操作）
        EventBus.create_consumer_group(stream_key, consumer_group)

        logger.info(
            f"[EventBus] Consumer {consumer_name} started, "
            f"group={consumer_group}, stream={stream_key}"
        )

        # ═══════════════════════════════════════════════════════════
        # 步骤1: 重放 Pending List（重启恢复）
        # ═══════════════════════════════════════════════════════════
        logger.info(f"[EventBus] 检查 Pending List: {stream_key}:{consumer_group}:{consumer_name}")

        while True:
            try:
                # 读取pending消息（id='0' 重放PEL）
                pending_messages = redis_client.client.xreadgroup(
                    consumer_group,
                    consumer_name,
                    {stream_key: '0'},  # '0' 重放该消费者的Pending List
                    count=count,
                    block=0  # 非阻塞，立即返回
                )

                if not pending_messages or not pending_messages[0][1]:
                    logger.info(f"[EventBus] Pending List 已清空，切换到新消息模式")
                    break

                # 处理pending消息
                for stream, msg_list in pending_messages:
                    for msg_id, fields in msg_list:
                        logger.warning(f"[EventBus] 重放PEL消息: {msg_id}")
                        EventBus._process_message(
                            stream_key, consumer_group, msg_id, fields, handler
                        )

            except Exception as e:
                logger.error(f"[EventBus] PEL重放异常: {e}", exc_info=True)
                break

        # ═══════════════════════════════════════════════════════════
        # 步骤2: 持续消费新消息
        # ═══════════════════════════════════════════════════════════
        logger.info(f"[EventBus] 开始消费新消息: {stream_key}")

        while True:
            try:
                # XREADGROUP 读取新消息（id='>' 只读取未消费的新消息）
                messages = redis_client.client.xreadgroup(
                    consumer_group,
                    consumer_name,
                    {stream_key: '>'},  # '>' 只读取新消息
                    block=block_ms,
                    count=count
                )

                if not messages:
                    continue  # 超时无消息，继续等待

                # messages 格式: [(stream_key, [(msg_id, fields), ...])]
                for stream, msg_list in messages:
                    for msg_id, fields in msg_list:
                        EventBus._process_message(
                            stream_key, consumer_group, msg_id, fields, handler
                        )

            except KeyboardInterrupt:
                logger.info(f"[EventBus] Consumer {consumer_name} stopped by user")
                break
            except Exception as e:
                logger.error(f"[EventBus] Consumer error: {e}", exc_info=True)
                time.sleep(1)  # 短暂休眠，避免错误循环

    @staticmethod
    def _process_message(
        stream_key: str,
        consumer_group: str,
        msg_id: str,
        fields: Dict,
        handler: Callable
    ) -> None:
        """处理单条消息（无条件ACK + 幂等检查）"""
        redis_client = get_redis_client()

        try:
            # ═══════════════════════════════════════════════════════
            # 步骤1: 立即ACK（无条件）
            # ═══════════════════════════════════════════════════════
            redis_client.client.xack(stream_key, consumer_group, msg_id)
            logger.info(f"[EventBus] ACK消息: {msg_id}")

            # ═══════════════════════════════════════════════════════
            # 步骤2: 解析消息字段（修复bytes键bug）
            # ═══════════════════════════════════════════════════════
            event_type = fields.get('event_type', '')
            payload_str = fields.get('payload', '{}')
            trace_id = fields.get('trace_id', '')
            timestamp = fields.get('timestamp', '')

            payload = json.loads(payload_str)

            # ═══════════════════════════════════════════════════════
            # 步骤3: 幂等检查（trace_id去重）
            # ═══════════════════════════════════════════════════════
            idempotent_key = f"eventbus:processed:{trace_id}"

            # SET NX EX 86400 → 如果key不存在则设置，过期时间24小时
            is_first_time = redis_client.client.set(idempotent_key, '1', nx=True, ex=86400)

            if not is_first_time:
                logger.warning(f"[EventBus] 重复消息，跳过: trace_id={trace_id}")
                return

            logger.info(
                f"[EventBus] Processing {event_type} from {stream_key}, "
                f"msg_id={msg_id}, trace_id={trace_id}"
            )

            # ═══════════════════════════════════════════════════════
            # 步骤4: 调用业务handler
            # ═══════════════════════════════════════════════════════
            success = handler(event_type, payload, trace_id)

            if not success:
                # ═══════════════════════════════════════════════════
                # 步骤5: 失败写入死信队列
                # ═══════════════════════════════════════════════════
                dead_letter_key = f"{stream_key}:dead_letter"
                redis_client.client.xadd(dead_letter_key, {
                    'original_stream': stream_key,
                    'original_msg_id': msg_id,
                    'event_type': event_type,
                    'payload': payload_str,
                    'trace_id': trace_id,
                    'error_time': datetime.now().isoformat(),
                    'handler_name': handler.__name__
                })
                logger.error(f"[EventBus] 处理失败，已写入死信队列: {dead_letter_key}")

        except json.JSONDecodeError as e:
            logger.error(f"[EventBus] Invalid JSON in {msg_id}: {e}")
            # JSON 格式错误，写入死信队列
            dead_letter_key = f"{stream_key}:dead_letter"
            redis_client.client.xadd(dead_letter_key, {
                'original_stream': stream_key,
                'original_msg_id': msg_id,
                'payload': fields.get('payload', ''),
                'error': f"JSONDecodeError: {str(e)}",
                'error_time': datetime.now().isoformat()
            })

        except Exception as e:
            logger.error(
                f"[EventBus] Error processing {msg_id}: {e}",
                exc_info=True
            )
            # 不 ACK，保留在 Pending List

    @staticmethod
    def create_consumer_group(
        stream_key: str,
        group_name: str,
        start_id: str = '0'
    ) -> None:
        """创建消费组（幂等操作）

        Args:
            stream_key: Stream 队列标识
            group_name: 消费组名称
            start_id: 起始消息 ID（'0' 表示从头开始，'$' 表示从最新开始）
        """
        try:
            redis_client.client.xgroup_create(
                stream_key,
                group_name,
                id=start_id,
                mkstream=True  # 如果 Stream 不存在则创建
            )
            logger.info(
                f"[EventBus] Created consumer group {group_name} "
                f"for {stream_key}"
            )
        except Exception as e:
            if 'BUSYGROUP' in str(e):
                logger.debug(
                    f"[EventBus] Consumer group {group_name} already exists"
                )
            else:
                logger.error(f"[EventBus] Failed to create consumer group: {e}")
                raise

    @staticmethod
    def get_pending_count(stream_key: str, consumer_group: str) -> int:
        """获取 Pending List 中的消息数量

        Args:
            stream_key: Stream 队列标识
            consumer_group: 消费组名称

        Returns:
            pending_count: 未 ACK 的消息数量
        """
        try:
            pending_info = redis_client.client.xpending(stream_key, consumer_group)
            return pending_info['pending']
        except Exception as e:
            logger.error(f"[EventBus] Failed to get pending count: {e}")
            return 0

    @staticmethod
    def get_stream_length(stream_key: str) -> int:
        """获取 Stream 的长度（消息总数）

        Args:
            stream_key: Stream 队列标识

        Returns:
            length: Stream 中的消息总数
        """
        try:
            return redis_client.client.xlen(stream_key)
        except Exception as e:
            logger.error(f"[EventBus] Failed to get stream length: {e}")
            return 0
