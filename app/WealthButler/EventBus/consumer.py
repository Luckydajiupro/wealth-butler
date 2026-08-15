"""事件消费者注册与启动

管理所有事件消费者的注册和启动，在 FastAPI 应用启动时调用。

使用方式：
    from app.WealthButler.EventBus.consumer import start_all_consumers

    # 在 app/Base/main.py 的 lifespan 或 startup 事件中调用
    @app.on_event("startup")
    async def startup_event():
        start_all_consumers()
"""
import threading
import logging
from typing import Dict, Any
from app.WealthButler.EventBus.eventBus import EventBus
from app.WealthButler.EventBus.schemas import validate_event

logger = logging.getLogger(__name__)

# 消费者配置（Stream Key → Consumer Group 映射）
CONSUMER_CONFIGS = [
    {
        'stream_key': 'stream:large_transaction',
        'consumer_group': 'risk_monitor_group',
        'consumer_name': 'risk-worker-1',
        'handler_name': 'handle_large_transaction'
    },
    {
        'stream_key': 'stream:suspicious_intent',
        'consumer_group': 'risk_monitor_group',
        'consumer_name': 'risk-worker-2',
        'handler_name': 'handle_suspicious_intent'
    },
    {
        'stream_key': 'stream:risk_alert',
        'consumer_group': 'advisor_group',
        'consumer_name': 'advisor-worker-1',
        'handler_name': 'handle_risk_alert'
    },
    {
        'stream_key': 'stream:profile_updated',
        'consumer_group': 'recommendation_group',
        'consumer_name': 'recommender-worker-1',
        'handler_name': 'handle_profile_updated'
    },
    {
        'stream_key': 'stream:work_order',
        'consumer_group': 'advisor_group',
        'consumer_name': 'advisor-worker-2',
        'handler_name': 'handle_work_order'
    }
]


# ============================================================
# 事件处理函数（Handler）
# ============================================================

def handle_large_transaction(event_type: str, payload: Dict[str, Any], trace_id: str) -> bool:
    """处理大额交易事件

    业务逻辑：
    1. 校验事件格式
    2. 触发风控规则引擎（RW-001/RW-003）
    3. 如果命中规则，写入 fin_risk_alert 表并发布 risk_alert 事件

    Args:
        event_type: 事件类型
        payload: 事件载荷
        trace_id: 追踪ID

    Returns:
        bool: 处理成功返回 True，失败返回 False
    """
    try:
        # 校验事件格式
        event = validate_event('large_transaction', payload)

        logger.info(
            f"[Consumer] Processing large_transaction: customer_id={event.customer_id}, "
            f"amount={event.amount}, tx_type={event.tx_type}, trace_id={trace_id}"
        )

        # TODO: 调用风控规则引擎
        # from app.WealthButler.Rules.ruleEngine import RuleEngine
        # result = RuleEngine.evaluate_transaction(event.dict())
        # if result['triggered']:
        #     # 写入 fin_risk_alert 表
        #     # 发布 risk_alert 事件
        #     pass

        logger.info(f"[Consumer] Large transaction processed successfully, trace_id={trace_id}")
        return True

    except Exception as e:
        logger.error(f"[Consumer] Failed to process large_transaction: {e}", exc_info=True)
        return False


def handle_suspicious_intent(event_type: str, payload: Dict[str, Any], trace_id: str) -> bool:
    """处理可疑意图事件

    业务逻辑：
    1. 校验事件格式
    2. 记录到 fin_risk_alert 表
    3. 如果置信度 > 0.7，立即发送预警通知

    Args:
        event_type: 事件类型
        payload: 事件载荷
        trace_id: 追踪ID

    Returns:
        bool: 处理成功返回 True，失败返回 False
    """
    try:
        event = validate_event('suspicious_intent', payload)

        logger.info(
            f"[Consumer] Processing suspicious_intent: customer_id={event.customer_id}, "
            f"intent_type={event.intent_type}, confidence={event.confidence}, trace_id={trace_id}"
        )

        # TODO: 实现可疑意图处理逻辑
        # if event.confidence > 0.7:
        #     # 高置信度，立即预警
        #     pass

        logger.info(f"[Consumer] Suspicious intent processed successfully, trace_id={trace_id}")
        return True

    except Exception as e:
        logger.error(f"[Consumer] Failed to process suspicious_intent: {e}", exc_info=True)
        return False


def handle_risk_alert(event_type: str, payload: Dict[str, Any], trace_id: str) -> bool:
    """处理风险预警事件

    业务逻辑：
    1. 校验事件格式
    2. 更新客户画像的风险标记
    3. 通知投顾助手 Agent 和客服 Agent

    Args:
        event_type: 事件类型
        payload: 事件载荷
        trace_id: 追踪ID

    Returns:
        bool: 处理成功返回 True，失败返回 False
    """
    try:
        event = validate_event('risk_alert', payload)

        logger.info(
            f"[Consumer] Processing risk_alert: customer_id={event.customer_id}, "
            f"rule_code={event.rule_code}, alert_level={event.alert_level}, trace_id={trace_id}"
        )

        # TODO: 更新客户画像的风险标记
        # from app.WealthButler.Service.profileService import ProfileService
        # ProfileService.update_risk_flag(event.customer_id, event.alert_level)

        logger.info(f"[Consumer] Risk alert processed successfully, trace_id={trace_id}")
        return True

    except Exception as e:
        logger.error(f"[Consumer] Failed to process risk_alert: {e}", exc_info=True)
        return False


def handle_profile_updated(event_type: str, payload: Dict[str, Any], trace_id: str) -> bool:
    """处理画像更新事件

    业务逻辑：
    1. 校验事件格式
    2. 触发个性化推荐重新计算
    3. 更新缓存

    Args:
        event_type: 事件类型
        payload: 事件载荷
        trace_id: 追踪ID

    Returns:
        bool: 处理成功返回 True，失败返回 False
    """
    try:
        event = validate_event('profile_updated', payload)

        logger.info(
            f"[Consumer] Processing profile_updated: customer_id={event.customer_id}, "
            f"updated_fields={list(event.updated_fields.keys())}, trace_id={trace_id}"
        )

        # TODO: 触发推荐重新计算
        # from app.WealthButler.Service.recommendationService import RecommendationService
        # RecommendationService.refresh_recommendations(event.customer_id)

        logger.info(f"[Consumer] Profile updated processed successfully, trace_id={trace_id}")
        return True

    except Exception as e:
        logger.error(f"[Consumer] Failed to process profile_updated: {e}", exc_info=True)
        return False


def handle_work_order(event_type: str, payload: Dict[str, Any], trace_id: str) -> bool:
    """处理工单事件

    业务逻辑：
    1. 校验事件格式
    2. 通知理财顾问工作台
    3. 发送站内消息或邮件

    Args:
        event_type: 事件类型
        payload: 事件载荷
        trace_id: 追踪ID

    Returns:
        bool: 处理成功返回 True，失败返回 False
    """
    try:
        event = validate_event('work_order', payload)

        logger.info(
            f"[Consumer] Processing work_order: order_id={event.order_id}, "
            f"order_type={event.order_type}, customer_id={event.customer_id}, trace_id={trace_id}"
        )

        # TODO: 通知理财顾问
        # from app.WealthButler.Service.notificationService import NotificationService
        # NotificationService.notify_advisor(event.handler_id, event.order_id)

        logger.info(f"[Consumer] Work order processed successfully, trace_id={trace_id}")
        return True

    except Exception as e:
        logger.error(f"[Consumer] Failed to process work_order: {e}", exc_info=True)
        return False


# Handler 映射表
HANDLERS = {
    'handle_large_transaction': handle_large_transaction,
    'handle_suspicious_intent': handle_suspicious_intent,
    'handle_risk_alert': handle_risk_alert,
    'handle_profile_updated': handle_profile_updated,
    'handle_work_order': handle_work_order,
}


# ============================================================
# 消费者启动函数
# ============================================================

def start_all_consumers():
    """启动所有事件消费者

    每个消费者在独立的守护线程中运行，主进程退出时自动退出。
    应在 FastAPI 应用启动时调用（app.on_event("startup")）。
    """
    logger.info("[EventBus] Starting all consumers...")

    for config in CONSUMER_CONFIGS:
        stream_key = config['stream_key']
        consumer_group = config['consumer_group']
        consumer_name = config['consumer_name']
        handler_name = config['handler_name']

        handler = HANDLERS.get(handler_name)
        if handler is None:
            logger.error(f"[EventBus] Handler {handler_name} not found, skipping {stream_key}")
            continue

        # 启动消费者线程
        thread = threading.Thread(
            target=EventBus.consume,
            args=(stream_key, consumer_group, consumer_name, handler),
            kwargs={'block_ms': 5000, 'count': 10},
            daemon=True,  # 守护线程，主进程退出时自动退出
            name=f"EventBus-{consumer_name}"
        )
        thread.start()

        logger.info(
            f"[EventBus] Started consumer: {consumer_name} for {stream_key} "
            f"in group {consumer_group}"
        )

    logger.info(f"[EventBus] All {len(CONSUMER_CONFIGS)} consumers started successfully")


def stop_all_consumers():
    """停止所有消费者（预留接口，当前使用守护线程自动退出）"""
    logger.info("[EventBus] Stopping all consumers (daemon threads will exit automatically)")
