"""事件总线层

职责：
- 封装 Redis Streams 的 XADD（发布）和 XREAD（消费）操作
- 提供统一的事件发布/订阅接口，解耦 Agent 之间的消息传递
- 实现事件路由、消费组管理、错误重试机制
- 支持多 Agent 协作的异步通信（架构设计文档§2.4）

分层原则：
- 本层是事件驱动架构的基础设施，与具体业务解耦
- 复用 Base.Client.redisClient，不重新实现 Redis 连接池
- 事件 Schema 标准化：{event_type, payload, timestamp, trace_id}
- 消费者幂等性由业务层保证（本层只负责 at-least-once 投递）

核心概念（架构设计文档§2.4）：
- Stream Key: Redis Streams 的队列标识（如 stream:large_transaction）
- Event Type: 事件类型标签（如 product_purchased、risk_alert）
- Consumer Group: 消费组（本期单消费者，不做多实例竞争消费）
- Trace ID: 分布式跟踪标识（透传到所有下游 Agent）

4 个 Stream Key（架构设计文档§2.4.1/§2.4.2）：
1. stream:large_transaction     大额交易事件（业务操作 Agent → 风控监测 Agent）
2. stream:suspicious_intent     可疑意图事件（智能客服 Agent → 风控监测 Agent）
3. stream:profile_updated       画像更新事件（投顾助手 Agent → 推荐引擎）
4. stream:work_order           工单事件（智能客服 Agent → 理财顾问工作台）

典型模块：
- eventBus.py                 事件总线核心类
  - publish(stream_key, event_type, payload) -> message_id
  - consume(stream_key, consumer_group, handler, block_ms) -> None
  - create_consumer_group(stream_key, group_name)

- schemas.py                  事件 Schema 定义
  - LargeTransactionEvent
  - SuspiciousIntentEvent
  - ProfileUpdatedEvent
  - WorkOrderEvent

- consumer.py                 消费者注册与启动
  - register_consumer(stream_key, handler)
  - start_all_consumers()  # 在 Base.main.py 启动时调用

EventBus 核心类实现：
    from app.Base.Client.redisClient import get_redis_client
    import json
    import time
    import uuid

    class EventBus:
        '''Redis Streams 事件总线封装'''

        @staticmethod
        def publish(stream_key: str, event_type: str, payload: dict, trace_id: str = None) -> str:
            '''发布事件到指定 Stream

            Args:
                stream_key: Stream 队列标识（如 stream:large_transaction）
                event_type: 事件类型（如 product_purchased）
                payload: 事件载荷（业务数据，必须可 JSON 序列化）
                trace_id: 分布式跟踪 ID（可选，自动生成）

            Returns:
                message_id: Redis Streams 消息 ID（如 1692345678901-0）
            '''
            redis = get_redis_client()
            trace_id = trace_id or str(uuid.uuid4())

            event = {
                'event_type': event_type,
                'payload': json.dumps(payload, ensure_ascii=False),
                'timestamp': int(time.time() * 1000),
                'trace_id': trace_id
            }

            # XADD stream_key * field1 value1 field2 value2 ...
            message_id = redis.xadd(stream_key, event)

            # 日志记录（供调试与审计）
            print(f"[EventBus] Published {event_type} to {stream_key}, msg_id={message_id}")

            return message_id

        @staticmethod
        def consume(
            stream_key: str,
            consumer_group: str,
            consumer_name: str,
            handler: callable,
            block_ms: int = 5000,
            count: int = 10
        ):
            '''消费指定 Stream 的事件（阻塞式循环）

            Args:
                stream_key: Stream 队列标识
                consumer_group: 消费组名称
                consumer_name: 本消费者名称（单实例可用 "worker-1"）
                handler: 事件处理函数 (event_type, payload, trace_id) -> bool
                         返回 True 表示处理成功（ACK），False 表示失败（不 ACK，等待重试）
                block_ms: XREADGROUP 阻塞超时（毫秒）
                count: 每次拉取最多多少条消息
            '''
            redis = get_redis_client()

            # 确保消费组存在（首次调用时创建）
            try:
                redis.xgroup_create(stream_key, consumer_group, id='0', mkstream=True)
            except Exception as e:
                if 'BUSYGROUP' not in str(e):  # 消费组已存在，忽略
                    raise

            print(f"[EventBus] Consumer {consumer_name} started, group={consumer_group}, stream={stream_key}")

            while True:
                # XREADGROUP GROUP group_name consumer_name BLOCK block_ms COUNT count STREAMS stream_key >
                messages = redis.xreadgroup(
                    consumer_group,
                    consumer_name,
                    {stream_key: '>'},  # '>' 表示读取未被消费的新消息
                    block=block_ms,
                    count=count
                )

                if not messages:
                    continue  # 超时无消息，继续等待

                for stream, msg_list in messages:
                    for msg_id, fields in msg_list:
                        try:
                            event_type = fields.get(b'event_type', b'').decode('utf-8')
                            payload = json.loads(fields.get(b'payload', b'{}').decode('utf-8'))
                            trace_id = fields.get(b'trace_id', b'').decode('utf-8')

                            print(f"[EventBus] Received {event_type} from {stream_key}, msg_id={msg_id}")

                            # 调用业务处理函数
                            success = handler(event_type, payload, trace_id)

                            if success:
                                # ACK 确认（从 Pending List 移除）
                                redis.xack(stream_key, consumer_group, msg_id)
                            else:
                                # 处理失败，不 ACK（保留在 Pending List，等待重试或人工介入）
                                print(f"[EventBus] Handler failed for {msg_id}, kept in pending")

                        except Exception as e:
                            print(f"[EventBus] Error processing {msg_id}: {e}")
                            # 不 ACK，保留在 Pending List

        @staticmethod
        def create_consumer_group(stream_key: str, group_name: str):
            '''创建消费组（幂等操作）'''
            redis = get_redis_client()
            try:
                redis.xgroup_create(stream_key, group_name, id='0', mkstream=True)
                print(f"[EventBus] Created consumer group {group_name} for {stream_key}")
            except Exception as e:
                if 'BUSYGROUP' in str(e):
                    print(f"[EventBus] Consumer group {group_name} already exists")
                else:
                    raise

事件 Schema 定义：
    from pydantic import BaseModel

    class LargeTransactionEvent(BaseModel):
        '''大额交易事件（业务操作 Agent → 风控监测 Agent）'''
        customer_id: int
        product_id: int
        amount: float
        tx_type: str  # 'purchase' | 'redeem'
        tx_id: str

    class SuspiciousIntentEvent(BaseModel):
        '''可疑意图事件（智能客服 Agent → 风控监测 Agent）'''
        customer_id: int
        session_id: str
        suspicious_text: str
        intent_type: str  # 'money_laundering' | 'fraud' | 'other'

    class ProfileUpdatedEvent(BaseModel):
        '''画像更新事件（投顾助手 Agent → 推荐引擎）'''
        customer_id: int
        updated_fields: dict  # {risk_preference: '稳健型', investment_goal: '养老'}

    class WorkOrderEvent(BaseModel):
        '''工单事件（智能客服 Agent → 理财顾问工作台）'''
        order_id: int
        order_type: str  # '客户转介' | '投诉' | '咨询'
        customer_id: int
        description: str

消费者注册示例：
    # consumer.py
    from WealthButler.EventBus.eventBus import EventBus
    import threading

    def handle_large_transaction(event_type: str, payload: dict, trace_id: str) -> bool:
        '''处理大额交易事件'''
        try:
            from WealthButler.Agent.riskAgent import RiskAgent

            agent = RiskAgent()
            result = agent.evaluate_transaction(payload)

            if result['triggered']:
                # 触发风控规则，记录到 biz_risk_alert 表
                pass

            return True  # 处理成功
        except Exception as e:
            print(f"[Consumer] Error: {e}")
            return False  # 处理失败，不 ACK

    def start_all_consumers():
        '''启动所有消费者（在 Base.main.py 中调用）'''
        # 大额交易消费者
        threading.Thread(
            target=EventBus.consume,
            args=(
                'stream:large_transaction',
                'risk_monitor_group',
                'worker-1',
                handle_large_transaction
            ),
            daemon=True  # 守护线程，主进程退出时自动退出
        ).start()

        # 其他消费者...

在 Base/main.py 中注册：
    from WealthButler.EventBus.consumer import start_all_consumers

    # 在 app 创建后、uvicorn.run() 前调用
    start_all_consumers()

与架构设计文档的对应关系：
- §2.4: 事件总线整体设计（Pub/Sub 改 Streams 的 ADR-3）
- §2.4.1: 大额交易事件流（业务操作 Agent → 风控监测 Agent）
- §2.4.2: 可疑意图事件流（智能客服 Agent → 风控监测 Agent）
- §8.5: 业务操作 Agent 的 NL2API 执行后发布事件

技术约束（架构设计文档§3.2）：
- 本期单进程单消费者，不做多实例竞争消费（不用 XAUTOCLAIM）
- 消息保留 7 天（XTRIM MAXLEN ~ 10000 MINID）
- Pending List 超过 1 小时未 ACK 的消息需人工介入（监控告警）

使用规范：
- 事件发布是异步的，不阻塞 Agent 主流程
- 消费者处理函数应快速返回（<1s），长耗时任务提交到后台队列
- trace_id 透传到所有下游，便于分布式链路追踪
- 事件 payload 必须可 JSON 序列化（不能包含 SQLAlchemy 对象）
"""

from app.WealthButler.EventBus.eventBus import EventBus
from app.WealthButler.EventBus.schemas import (
    LargeTransactionEvent,
    SuspiciousIntentEvent,
    RiskAlertEvent,
    ProfileUpdatedEvent,
    WorkOrderEvent,
    validate_event
)
from app.WealthButler.EventBus.consumer import start_all_consumers, stop_all_consumers

__all__ = [
    'EventBus',
    'LargeTransactionEvent',
    'SuspiciousIntentEvent',
    'RiskAlertEvent',
    'ProfileUpdatedEvent',
    'WorkOrderEvent',
    'validate_event',
    'start_all_consumers',
    'stop_all_consumers'
]
