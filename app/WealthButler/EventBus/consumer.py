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
from datetime import datetime
from typing import Dict, Any
from app.WealthButler.EventBus.eventBus import EventBus
from app.WealthButler.EventBus.schemas import validate_event

logger = logging.getLogger(__name__)
_consumer_lock = threading.Lock()
_consumer_stop_event = threading.Event()
_consumer_threads = []


def handle_large_transaction(event_type: str, payload: Dict[str, Any], trace_id: str) -> bool:
    """大额交易事件处理器（调用风控Agent）"""
    try:
        from app.WealthButler.Agent.riskAgent import large_transaction_event_handler
        return large_transaction_event_handler(event_type, payload, trace_id)
    except Exception as e:
        logger.error(f"large_transaction handler failed: {e}", exc_info=True)
        return False


def handle_suspicious_intent(event_type: str, payload: Dict[str, Any], trace_id: str) -> bool:
    """可疑意图事件处理器（调用风控Agent）"""
    try:
        from app.WealthButler.Agent.riskAgent import suspicious_intent_event_handler
        return suspicious_intent_event_handler(event_type, payload, trace_id)
    except Exception as e:
        logger.error(f"suspicious_intent handler failed: {e}", exc_info=True)
        return False


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
    },
    {
        'stream_key': 'stream:work_order_result',
        'consumer_group': 'customer_reply_group',
        'consumer_name': 'customer-reply-worker-1',
        'handler_name': 'handle_work_order_result'
    }
]


# ============================================================
# 事件处理函数（Handler）
# ============================================================



def handle_risk_alert(event_type: str, payload: Dict[str, Any], trace_id: str) -> bool:
    """处理风险预警事件

    业务逻辑：
    1. 校验事件格式
    2. 更新客户画像的风险标记（写入fin_customer_profile）
    3. 记录到Redis短期记忆（供投顾/客服Agent查询）

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
            f"rule_id={event.rule_id}, severity={event.severity}, trace_id={trace_id}"
        )

        # 1. 更新客户画像的风险标记（写入数据库）
        try:
            from app.WealthButler.Models.customerProfileModel import CustomerProfileModel

            profile = CustomerProfileModel.get_by_customer_id(event.customer_id)
            if profile:
                # 更新风险标记字段
                risk_flags = profile.risk_flags or {}
                if not isinstance(risk_flags, dict):
                    risk_flags = {}

                risk_flags['latest_alert'] = {
                    'alert_id': event.alert_id,
                    'rule_id': event.rule_id,
                    'severity': event.severity,
                    'updated_at': payload.get('created_at', ''),
                    'trace_id': trace_id
                }

                # 更新风险等级（根据severity映射）
                severity_to_level = {
                    'low': '低风险',
                    'medium': '中风险',
                    'high': '高风险',
                    'critical': '极高风险'
                }
                new_risk_level = severity_to_level.get(event.severity, '中风险')

                profile.risk_flags = risk_flags
                profile.risk_level = new_risk_level
                profile.save()

                logger.info(
                    f"[Consumer] 已更新客户画像风险标记: customer_id={event.customer_id}, "
                    f"risk_level={new_risk_level}"
                )
        except Exception as e:
            logger.error(f"[Consumer] 更新客户画像失败: {e}", exc_info=True)
            # 更新画像失败不影响整体处理，继续执行

        # 2. 写入Redis短期记忆（供投顾/客服Agent快速查询）
        try:
            from app.Base.Client.redisClient import redis_client

            redis_key = f"customer:risk_alert:{event.customer_id}"
            redis_value = {
                'alert_id': event.alert_id,
                'rule_id': event.rule_id,
                'severity': event.severity,
                'trigger_details': event.trigger_details or {},
                'created_at': payload.get('created_at', ''),
                'trace_id': trace_id
            }

            import json
            redis_client.client.setex(
                redis_key,
                7 * 24 * 3600,  # 7天过期
                json.dumps(redis_value, ensure_ascii=False)
            )

            logger.info(
                f"[Consumer] 已写入Redis短期记忆: {redis_key}"
            )
        except Exception as e:
            logger.error(f"[Consumer] 写入Redis短期记忆失败: {e}", exc_info=True)
            # Redis写入失败不影响整体处理

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
    2. 写入Redis通知队列（供前端轮询）
    3. 记录到日志供后续审计

    注意：工单本身已经在数据库中创建（由客服Agent创建），
    此处只是通知机制，不重复创建工单。

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

        # 1. 根据工单类型决定通知对象
        notification_target = None
        if event.order_type == "客户转介":
            notification_target = "advisor"  # 通知理财顾问
        elif event.order_type == "风控预警":
            notification_target = "risk_specialist"  # 通知风控专员
        elif event.order_type in ["投诉", "咨询"]:
            notification_target = "customer_service"  # 通知客服主管
        else:
            notification_target = "operator"  # 通知业务操作专员

        # 2. 写入Redis通知队列
        try:
            from app.Base.Client.redisClient import redis_client
            import json

            notification_key = f"notifications:{notification_target}"
            notification = {
                'type': 'work_order',
                'order_id': event.order_id,
                'order_type': event.order_type,
                'customer_id': event.customer_id,
                'description': event.description[:100],  # 截取前100字符
                'priority': event.priority,
                'handler_id': event.handler_id,
                'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'trace_id': trace_id
            }

            # 使用LPUSH + LTRIM保持队列长度
            redis_client.client.lpush(
                notification_key,
                json.dumps(notification, ensure_ascii=False)
            )
            redis_client.client.ltrim(notification_key, 0, 99)  # 保留最新100条
            redis_client.client.expire(notification_key, 7 * 24 * 3600)  # 7天过期

            logger.info(
                f"[Consumer] 已发送工单通知: target={notification_target}, "
                f"order_id={event.order_id}"
            )
        except Exception as e:
            logger.error(f"[Consumer] 发送工单通知失败: {e}", exc_info=True)
            # 通知失败不影响整体处理

        # 3. 如果指定了处理人，发送定向通知
        if event.handler_id:
            try:
                from app.Base.Client.redisClient import redis_client
                import json

                handler_key = f"notifications:user:{event.handler_id}"
                handler_notification = {
                    'type': 'work_order_assigned',
                    'order_id': event.order_id,
                    'order_type': event.order_type,
                    'customer_id': event.customer_id,
                    'description': event.description[:100],
                    'priority': event.priority,
                    'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'trace_id': trace_id
                }

                redis_client.client.lpush(
                    handler_key,
                    json.dumps(handler_notification, ensure_ascii=False)
                )
                redis_client.client.ltrim(handler_key, 0, 49)  # 保留最新50条
                redis_client.client.expire(handler_key, 7 * 24 * 3600)

                logger.info(
                    f"[Consumer] 已发送处理人定向通知: handler_id={event.handler_id}"
                )
            except Exception as e:
                logger.error(f"[Consumer] 发送处理人通知失败: {e}", exc_info=True)

        logger.info(f"[Consumer] Work order processed successfully, trace_id={trace_id}")
        return True

    except Exception as e:
        logger.error(f"[Consumer] Failed to process work_order: {e}", exc_info=True)
        return False


def handle_work_order_result(event_type: str, payload: Dict[str, Any], trace_id: str) -> bool:
    """Persist a bounded per-customer notification for browser delivery."""
    try:
        event = validate_event('work_order_result', payload)
        from app.WealthButler.Service.customerNotificationService import store_work_order_result_notification

        store_work_order_result_notification(event.model_dump(), trace_id)
        logger.info(
            "[Consumer] 已写入客户处理结果通知: customer_id=%s order_id=%s",
            event.customer_id,
            event.order_id,
        )
        return True
    except Exception as exc:
        logger.error("[Consumer] Failed to process work_order_result: %s", exc, exc_info=True)
        return False


# Handler 映射表
HANDLERS = {
    'handle_large_transaction': handle_large_transaction,
    'handle_suspicious_intent': handle_suspicious_intent,
    'handle_risk_alert': handle_risk_alert,
    'handle_profile_updated': handle_profile_updated,
    'handle_work_order': handle_work_order,
    'handle_work_order_result': handle_work_order_result,
}


# ============================================================
# 消费者启动函数
# ============================================================

def start_all_consumers():
    """启动所有事件消费者

    每个消费者在独立的守护线程中运行，主进程退出时自动退出。
    应在 FastAPI 应用启动时调用（app.on_event("startup")）。
    """
    with _consumer_lock:
        alive_threads = [thread for thread in _consumer_threads if thread.is_alive()]
        if alive_threads:
            logger.info("[EventBus] Consumers already running, skipping duplicate start")
            return tuple(alive_threads)
        _consumer_threads.clear()
        _consumer_stop_event.clear()

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
            kwargs={
                'block_ms': 1000,
                'count': 10,
                'stop_event': _consumer_stop_event,
            },
            daemon=True,  # 守护线程，主进程退出时自动退出
            name=f"EventBus-{consumer_name}"
        )
        thread.start()
        with _consumer_lock:
            _consumer_threads.append(thread)

        logger.info(
            f"[EventBus] Started consumer: {consumer_name} for {stream_key} "
            f"in group {consumer_group}"
        )

    logger.info(f"[EventBus] All {len(CONSUMER_CONFIGS)} consumers started successfully")
    with _consumer_lock:
        return tuple(_consumer_threads)


def stop_all_consumers():
    """通知所有消费者停止，并等待阻塞读取在限定时间内退出。"""
    logger.info("[EventBus] Stopping all consumers...")
    _consumer_stop_event.set()
    with _consumer_lock:
        threads = tuple(_consumer_threads)
    for thread in threads:
        if thread.is_alive():
            thread.join(timeout=2.0)
    remaining = tuple(thread.name for thread in threads if thread.is_alive())
    with _consumer_lock:
        _consumer_threads[:] = [thread for thread in threads if thread.is_alive()]
    if remaining:
        logger.warning("[EventBus] Consumers did not stop in time: %s", ", ".join(remaining))
    else:
        logger.info("[EventBus] All consumers stopped")
    return remaining
