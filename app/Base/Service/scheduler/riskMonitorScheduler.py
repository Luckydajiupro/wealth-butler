"""风控监测Agent定时任务

职责：
- 每日批量扫描：执行DAILY_RULE_IDS（10条日批规则）
- 每周批量扫描：执行WEEKLY_RULE_IDS（2条周批规则）
- 复用脚手架TaskSchedulerClient和auto_register机制

架构设计文档§2.4：批量轨规则通过APScheduler定时触发，
与交易事件流无关，独立扫描全量客户。
"""
import logging
from datetime import datetime

from app.Base.Service.schedulerService import get_base_module_scheduler_client

logger = logging.getLogger(__name__)


def daily_risk_scan():
    """每日风控规则批量扫描

    调度时间：每天凌晨2点
    规则范围：DAILY_RULE_IDS（10条日批规则）
    客户范围：fin_customer_profile全量客户（显式上限1000）
    """
    logger.info(f"[RiskScheduler] 开始执行每日风控扫描 - {datetime.now()}")

    try:
        from app.WealthButler.Agent.riskAgent import RiskAgent

        agent = RiskAgent()
        result = agent.scan_daily_rules()

        logger.info(
            f"[RiskScheduler] 每日扫描完成 - "
            f"状态: {result.get('status')}, "
            f"处理客户数: {len(result.get('processed_customers', []))}, "
            f"触发告警数: {len(result.get('triggered_alerts', []))}, "
            f"创建工单数: {len(result.get('created_work_orders', []))}, "
            f"发布事件数: {len(result.get('published_events', []))}"
        )

        if result.get('errors'):
            logger.warning(f"[RiskScheduler] 每日扫描存在错误: {result['errors'][:3]}")

        return result

    except Exception as e:
        logger.error(f"[RiskScheduler] 每日扫描异常: {e}", exc_info=True)
        return {"status": "error", "errors": [str(e)]}


def weekly_risk_scan():
    """每周风控规则批量扫描

    调度时间：每周一凌晨3点
    规则范围：WEEKLY_RULE_IDS（2条周批规则）
    客户范围：fin_customer_profile全量客户（显式上限1000）
    """
    logger.info(f"[RiskScheduler] 开始执行每周风控扫描 - {datetime.now()}")

    try:
        from app.WealthButler.Agent.riskAgent import RiskAgent

        agent = RiskAgent()
        result = agent.scan_weekly_rules()

        logger.info(
            f"[RiskScheduler] 每周扫描完成 - "
            f"状态: {result.get('status')}, "
            f"处理客户数: {len(result.get('processed_customers', []))}, "
            f"触发告警数: {len(result.get('triggered_alerts', []))}, "
            f"创建工单数: {len(result.get('created_work_orders', []))}, "
            f"发布事件数: {len(result.get('published_events', []))}"
        )

        if result.get('errors'):
            logger.warning(f"[RiskScheduler] 每周扫描存在错误: {result['errors'][:3]}")

        return result

    except Exception as e:
        logger.error(f"[RiskScheduler] 每周扫描异常: {e}", exc_info=True)
        return {"status": "error", "errors": [str(e)]}


# 使用装饰器注册定时任务
scheduler_client = get_base_module_scheduler_client()


@scheduler_client.scheduled(
    id='risk_daily_scan',
    trigger='cron',
    cron='0 2 * * *'  # 每天凌晨2点
)
def scheduled_daily_risk_scan():
    """每日风控扫描定时任务（装饰器注册）"""
    return daily_risk_scan()


@scheduler_client.scheduled(
    id='risk_weekly_scan',
    trigger='cron',
    cron='0 3 * * 1'  # 每周一凌晨3点
)
def scheduled_weekly_risk_scan():
    """每周风控扫描定时任务（装饰器注册）"""
    return weekly_risk_scan()


__all__ = [
    'daily_risk_scan',
    'weekly_risk_scan',
    'scheduled_daily_risk_scan',
    'scheduled_weekly_risk_scan',
]
