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
        trace_id: Optional[str] = None,
        maxlen: int = 10000
    ) -> str:
        """发布事件到指定 Stream

        Args:
            stream_key: Stream 队列标识（如 stream:large_transaction）
            event_type: 事件类型（如 product_purchased）
            payload: 事件载荷（业务数据，必须可 JSON 序列化）
            trace_id: 分布式跟踪 ID（可选，自动生成）
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
            'timestamp': str(int(time.time() * 1000)),
            'trace_id': trace_id
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
                     返回 True 表示处理成功（ACK），False 表示失败（不 ACK）
            block_ms: XREADGROUP 阻塞超时（毫秒），0 表示永久阻塞
            count: 每次拉取最多多少条消息

        注意：
            - 本方法会阻塞当前线程，应在独立线程中调用
            - 处理失败的消息会留在 Pending List，需人工介入或重试机制
            - 消费者重启后会自动重放 Pending List 中的消息（at-least-once）
        """
        # 确保消费组存在（幂等操作）
        EventBus.create_consumer_group(stream_key, consumer_group)

        logger.info(
            f"[EventBus] Consumer {consumer_name} started, "
            f"group={consumer_group}, stream={stream_key}"
        )

        while True:
            try:
                # XREADGROUP GROUP group_name consumer_name BLOCK block_ms COUNT count STREAMS stream_key >
                messages = redis_client.client.xreadgroup(
                    consumer_group,
                    consumer_name,
                    {stream_key: '>'},  # '>' 表示读取未被消费的新消息
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
        fields: Dict[bytes, bytes],
        handler: Callable
    ) -> None:
        """处理单条消息（内部方法）"""
        try:
            # 解析消息字段
            event_type = fields.get(b'event_type', b'').decode('utf-8')
            payload_str = fields.get(b'payload', b'{}').decode('utf-8')
            payload = json.loads(payload_str)
            trace_id = fields.get(b'trace_id', b'').decode('utf-8')

            logger.info(
                f"[EventBus] Processing {event_type} from {stream_key}, "
                f"msg_id={msg_id}, trace_id={trace_id}"
            )

            # 调用业务处理函数
            success = handler(event_type, payload, trace_id)

            if success:
                # ACK 确认（从 Pending List 移除）
                redis_client.client.xack(stream_key, consumer_group, msg_id)
                logger.info(f"[EventBus] ACK {msg_id}")
            else:
                # 处理失败，不 ACK（保留在 Pending List）
                logger.warning(
                    f"[EventBus] Handler returned False for {msg_id}, "
                    f"kept in pending"
                )

        except json.JSONDecodeError as e:
            logger.error(f"[EventBus] Invalid JSON in {msg_id}: {e}")
            # JSON 格式错误，无法重试，直接 ACK 丢弃
            redis_client.client.xack(stream_key, consumer_group, msg_id)

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
