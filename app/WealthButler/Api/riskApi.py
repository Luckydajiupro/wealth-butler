"""风险预警 API 接口层

职责：
- 提供风险预警的查询、处理、统计功能
- JWT认证，根据用户角色自动筛选预警
- 支持风控专员和业务管理员两种角色的不同权限
"""
from typing import Optional
from datetime import datetime
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.Base.RicUtils.httpUtils import HttpResponse
from app.Base.Service.authService import AuthService
from app.WealthButler.Models.riskAlertModel import RiskAlertModel
from app.WealthButler.Models.transactionModel import TransactionModel
from app.Base.Models.userModel import UserModel
from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel
from app.WealthButler.Models.riskRuleConfigModel import RiskRuleConfigModel
from dataclasses import replace
from app.WealthButler.Rules.ruleDefinitions import AML_RULES, RuleMeta


router = APIRouter(prefix="/api/wealth/risk", tags=["风险预警"])
security = HTTPBearer(auto_error=False)
_RULE_OVERRIDES: dict[str, RuleMeta] = {}
logger = logging.getLogger(__name__)


# ==================== 请求模型 ====================

class HandleAlertRequest(BaseModel):
    """处理风险预警请求"""
    action: str = Field(..., description="操作：process/confirm/mark_false/override_approve/override_reject")
    remark: Optional[str] = Field(None, description="处理备注")


class RuleChangeRequest(BaseModel):
    rule_id: Optional[str] = Field(None, min_length=3, max_length=32)
    rule_name: Optional[str] = Field(None, min_length=1, max_length=200)
    risk_level: Optional[str] = Field(None, min_length=1, max_length=20)
    priority: Optional[int] = Field(None, ge=1, le=5)
    enabled: Optional[bool] = None


# ==================== 辅助函数 ====================

def _get_current_user(credentials: HTTPAuthorizationCredentials):
    """获取当前登录用户（JWT认证）"""
    if not credentials:
        raise HTTPException(status_code=401, detail="缺少认证信息")
    user = AuthService.get_current_user(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账户已被禁用")
    return user


def _check_risk_permission(user_id: int) -> tuple[bool, bool]:
    """
    检查用户的风控权限
    返回：(是否是风控专员, 是否是业务管理员)
    """
    permissions = AuthService.get_user_permissions(user_id)
    business_user = BaseUserExtModel.get_by_id(user_id)
    employee_role = getattr(business_user, "employee_role", None)

    # 检查是否有可疑交易上报权限（风控专员）
    is_risk_officer = "risk:suspicious_report" in permissions

    # 检查是否有风险裁决权限（业务管理员）
    is_admin = "risk:override" in permissions or employee_role == "业务管理员"

    return is_risk_officer, is_admin


def _pending_rule_check(_customer_id, _context=None):
    """Draft rules are configuration-only until code supplies a reviewed checker."""
    return None


def _next_rule_version(version: str) -> str:
    try:
        major, minor = str(version).split(".", 1)
        return f"{int(major)}.{int(minor) + 1}"
    except (TypeError, ValueError):
        return "1.1"


def _rule_from_config(config: RiskRuleConfigModel) -> RuleMeta:
    base = AML_RULES.get(config.rule_id)
    return RuleMeta(
        rule_id=config.rule_id,
        rule_name=config.rule_name,
        trigger_scope=config.trigger_scope,
        risk_level=config.risk_level,
        weight_tier=float(config.weight_tier),
        priority=config.priority,
        check_func=base.check_func if base else _pending_rule_check,
        thresholds=dict(config.thresholds or {}),
        source_tables=tuple(config.source_tables or ()),
        source_fields=tuple(config.source_fields or ()),
        rule_version=config.rule_version,
        enabled=bool(config.enabled),
    )


def _rule_catalog() -> dict[str, RuleMeta]:
    """Merge code-owned checkers with durable metadata snapshots."""
    catalog = dict(AML_RULES)
    try:
        for config in RiskRuleConfigModel.load_all():
            rule = _rule_from_config(config)
            catalog[rule.rule_id] = rule
            _RULE_OVERRIDES[rule.rule_id] = rule
    except Exception as exc:
        # Read-only availability remains possible during migration/DB outage;
        # mutations below fail closed instead of pretending to persist.
        logger.warning("加载持久化风控规则失败，使用代码内置规则: %s", exc)
        catalog.update(_RULE_OVERRIDES)
    return catalog


def _persist_rule(rule: RuleMeta, updated_by: int) -> None:
    RiskRuleConfigModel.upsert_snapshot({
        "rule_id": rule.rule_id,
        "rule_name": rule.rule_name,
        "trigger_scope": rule.trigger_scope,
        "risk_level": rule.risk_level,
        "weight_tier": rule.weight_tier,
        "priority": rule.priority,
        "thresholds": rule.thresholds,
        "source_tables": list(rule.source_tables),
        "source_fields": list(rule.source_fields),
        "rule_version": rule.rule_version,
        "enabled": rule.enabled,
        "updated_by": updated_by,
    })
    _RULE_OVERRIDES[rule.rule_id] = rule


# ==================== API接口 ====================

@router.get("/rules")
def get_risk_rules(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Return code-owned rule checkers merged with durable editable metadata."""
    user = _get_current_user(credentials)
    is_risk_officer, is_admin = _check_risk_permission(user.id)
    if not is_risk_officer and not is_admin:
        raise HTTPException(status_code=403, detail="您没有查看风控规则的权限")

    rules = []
    for rule_id, rule in sorted(_rule_catalog().items(), key=lambda item: (item[1].priority, item[0])):
        rules.append({
            "rule_id": rule.rule_id,
            "rule_name": rule.rule_name,
            "trigger_scope": rule.trigger_scope,
            "risk_level": rule.risk_level,
            "priority": rule.priority,
            "rule_version": rule.rule_version,
            "enabled": rule.enabled,
            "thresholds": {key: str(value) for key, value in rule.thresholds.items()},
            "source_tables": list(rule.source_tables),
            "source_fields": list(rule.source_fields),
        })
    return HttpResponse.ok(data={"rules": rules, "total": len(rules)}, msg="规则目录查询成功")


def _require_rule_admin(credentials):
    user = _get_current_user(credentials)
    is_risk_officer, is_admin = _check_risk_permission(user.id)
    if not is_risk_officer and not is_admin:
        raise HTTPException(status_code=403, detail="您没有修改风控规则的权限")
    return user


@router.put("/rules/{rule_id}")
def update_risk_rule(rule_id: str, request: RuleChangeRequest, credentials: HTTPAuthorizationCredentials = Depends(security)):
    user = _require_rule_admin(credentials)
    current = _rule_catalog().get(rule_id)
    if current is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    changes = request.model_dump(exclude_none=True, exclude={"rule_id"})
    updated = replace(current, **changes, rule_version=_next_rule_version(current.rule_version))
    try:
        _persist_rule(updated, user.id)
    except Exception as exc:
        logger.exception("持久化风控规则失败: %s", rule_id)
        raise HTTPException(status_code=503, detail="规则持久化失败，本次修改未生效") from exc
    return HttpResponse.ok(msg="规则已更新")


@router.post("/rules")
def add_risk_rule(request: RuleChangeRequest, credentials: HTTPAuthorizationCredentials = Depends(security)):
    user = _require_rule_admin(credentials)
    if not request.rule_id or not request.rule_name or request.priority is None or not request.risk_level:
        raise HTTPException(status_code=400, detail="新增规则必须填写规则编号、名称、风险等级和优先级")
    if request.rule_id in _rule_catalog():
        raise HTTPException(status_code=409, detail="规则编号已存在")
    rule = RuleMeta(
        rule_id=request.rule_id, rule_name=request.rule_name, trigger_scope="daily",
        risk_level=request.risk_level, weight_tier=0.1, priority=request.priority,
        check_func=_pending_rule_check, thresholds={}, source_tables=(), source_fields=(),
        rule_version="draft", enabled=request.enabled if request.enabled is not None else True,
    )
    try:
        _persist_rule(rule, user.id)
    except Exception as exc:
        logger.exception("持久化新增风控规则失败: %s", request.rule_id)
        raise HTTPException(status_code=503, detail="规则持久化失败，本次新增未生效") from exc
    return HttpResponse.ok(msg="规则已添加，当前为草稿规则，需配置规则检查逻辑后启用")


@router.delete("/rules/{rule_id}")
def disable_risk_rule(rule_id: str, credentials: HTTPAuthorizationCredentials = Depends(security)):
    user = _require_rule_admin(credentials)
    current = _rule_catalog().get(rule_id)
    if current is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    disabled = replace(current, enabled=False, rule_version=_next_rule_version(current.rule_version))
    try:
        _persist_rule(disabled, user.id)
    except Exception as exc:
        logger.exception("持久化停用风控规则失败: %s", rule_id)
        raise HTTPException(status_code=503, detail="规则持久化失败，本次停用未生效") from exc
    return HttpResponse.ok(msg="规则已停用")

@router.get("/alerts")
def get_risk_alerts(
    status: Optional[str] = Query(None, description="状态筛选：待处理/处理中/已确认/误报"),
    alert_level: Optional[str] = Query(None, description="风险级别：低/中/高/严重"),
    need_override: Optional[bool] = Query(None, description="是否需要管理员裁决"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    GET /api/wealth/risk/alerts - 查询风险预警列表

    功能：
    - JWT认证
    - 根据用户角色自动筛选：
      * 风控专员：查看所有预警
      * 业务管理员：仅查看need_override=true且alert_level='高'的预警
      * 其他角色：403无权限
    - 关联交易表和用户表获取详细信息

    返回格式：
    {
        "code": 0,
        "data": {
            "alerts": [...],
            "total": 10
        },
        "msg": "查询成功"
    }
    """
    # 认证并获取用户信息
    user = _get_current_user(credentials)
    is_risk_officer, is_admin = _check_risk_permission(user.id)

    # 权限校验
    if not is_risk_officer and not is_admin:
        raise HTTPException(status_code=403, detail="您没有查看风险预警的权限")

    # 根据角色筛选条件
    if is_admin and not is_risk_officer:
        # 业务管理员只看需要裁决的高风险预警
        need_override = True
        alert_level = "高"

    # 查询预警列表
    alerts, total = RiskAlertModel.find_by_filters(
        status=status,
        severity=alert_level,
        need_override=need_override,
        limit=limit,
        offset=offset
    )

    # 构建返回数据
    result_data = []
    for alert in alerts:
        # 查询客户信息
        customer = UserModel.get_by_id(alert.customer_id)
        customer_name = customer.username if customer else "客户资料待补全"

        # 查询关联交易信息
        transaction_amount = None
        trigger_reason = alert.trigger_details.get("reason", "") if alert.trigger_details else ""

        if alert.related_transaction_id:
            transaction = TransactionModel.get_by_id(alert.related_transaction_id)
            if transaction:
                transaction_amount = float(transaction.amount)

        result_data.append({
            "id": alert.id,
            "alert_type": alert.rule_id,
            "alert_name": alert.rule_name,
            "alert_level": alert.severity,
            "customer_id": alert.customer_id,
            "customer_name": customer_name,
            "transaction_amount": transaction_amount,
            "trigger_reason": trigger_reason,
            "triggered_at": str(alert.created_at) if alert.created_at else None,
            "status": alert.status,
            "confidence": float(alert.confidence) if alert.confidence else 0.0,
            "need_override": alert.need_override,
            "handler_id": alert.handler_id,
            "handled_at": str(alert.handled_at) if alert.handled_at else None
        })

    return HttpResponse.ok(
        data={
            "alerts": result_data,
            "total": total
        },
        msg="查询成功"
    )


@router.put("/alert/{alert_id}/handle")
def handle_risk_alert(
    alert_id: int = Path(..., description="预警ID"),
    request: HandleAlertRequest = ...,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    PUT /api/wealth/risk/alert/{id}/handle - 处理风险预警

    功能：
    - JWT认证
    - 权限校验：
      * 风控专员：可执行process/confirm/mark_false
      * 业务管理员：可执行override_approve/override_reject
    - 状态机校验
    - 记录操作人和操作时间

    请求体：
    {
        "action": "process|confirm|mark_false|override_approve|override_reject",
        "remark": "处理备注"
    }
    """
    # 认证
    user = _get_current_user(credentials)
    is_risk_officer, is_admin = _check_risk_permission(user.id)

    # 查询预警
    alert = RiskAlertModel.get_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="预警不存在")

    # 根据action执行不同操作
    if request.action == "process":
        # 标记为处理中（待处理→处理中）
        if not is_risk_officer:
            raise HTTPException(status_code=403, detail="需要风控专员权限")

        if alert.status != "待处理":
            raise HTTPException(
                status_code=400,
                detail=f"只有'待处理'状态的预警才能标记为处理中，当前状态：{alert.status}"
            )

        alert.status = "处理中"
        alert.handler_id = user.id
        alert.handled_at = datetime.now()
        if request.remark:
            alert.handle_result = request.remark

        alert.save()
        return HttpResponse.ok(msg="预警已标记为处理中")

    elif request.action == "confirm":
        # 确认风险（处理中→已确认）
        if not is_risk_officer:
            raise HTTPException(status_code=403, detail="需要风控专员权限")

        if alert.status != "处理中":
            raise HTTPException(
                status_code=400,
                detail=f"只有'处理中'状态的预警才能确认，当前状态：{alert.status}"
            )

        alert.status = "已确认"
        if request.remark:
            alert.handle_result = (alert.handle_result or "") + f"\n确认：{request.remark}"

        alert.save()
        return HttpResponse.ok(msg="风险已确认")

    elif request.action == "mark_false":
        # 标记为误报（处理中→误报）
        if not is_risk_officer:
            raise HTTPException(status_code=403, detail="需要风控专员权限")

        if alert.status != "处理中":
            raise HTTPException(
                status_code=400,
                detail=f"只有'处理中'状态的预警才能标记为误报，当前状态：{alert.status}"
            )

        alert.status = "误报"
        if request.remark:
            alert.handle_result = (alert.handle_result or "") + f"\n误报：{request.remark}"

        alert.save()
        return HttpResponse.ok(msg="已标记为误报")

    elif request.action == "override_approve":
        # 管理员批准放行
        if not is_admin:
            raise HTTPException(status_code=403, detail="需要业务管理员权限（risk:override）")

        if not alert.need_override:
            raise HTTPException(status_code=400, detail="该预警不需要管理员裁决")

        alert.status = "误报"  # 批准放行，标记为误报
        alert.handler_id = user.id
        alert.handled_at = datetime.now()
        alert.handle_result = (alert.handle_result or "") + f"\n管理员批准放行：{request.remark or '无备注'}"

        alert.save()
        return HttpResponse.ok(msg="管理员已批准放行")

    elif request.action == "override_reject":
        # 管理员确认拦截
        if not is_admin:
            raise HTTPException(status_code=403, detail="需要业务管理员权限（risk:override）")

        if not alert.need_override:
            raise HTTPException(status_code=400, detail="该预警不需要管理员裁决")

        alert.status = "已确认"  # 确认拦截
        alert.handler_id = user.id
        alert.handled_at = datetime.now()
        alert.handle_result = (alert.handle_result or "") + f"\n管理员确认拦截：{request.remark or '无备注'}"

        alert.save()
        return HttpResponse.ok(msg="管理员已确认拦截")

    else:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的操作：{request.action}，支持的操作：process/confirm/mark_false/override_approve/override_reject"
        )


@router.get("/alert/{alert_id}")
def get_risk_alert_detail(
    alert_id: int = Path(..., description="预警ID"),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    GET /api/wealth/risk/alert/{id} - 查询单个预警详情

    功能：
    - JWT认证
    - 返回预警完整信息，包括关联的交易列表
    """
    # 认证
    user = _get_current_user(credentials)
    is_risk_officer, is_admin = _check_risk_permission(user.id)

    # 权限校验
    if not is_risk_officer and not is_admin:
        raise HTTPException(status_code=403, detail="您没有查看风险预警的权限")

    # 查询预警
    alert = RiskAlertModel.get_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="预警不存在")

    # 查询客户信息
    customer = UserModel.get_by_id(alert.customer_id)
    customer_name = customer.username if customer else "客户资料待补全"

    # 查询关联交易信息
    transaction_info = None
    if alert.related_transaction_id:
        transaction = TransactionModel.get_by_id(alert.related_transaction_id)
        if transaction:
            transaction_info = {
                "id": transaction.id,
                "transaction_type": transaction.transaction_type,
                "amount": float(transaction.amount),
                "transaction_time": str(transaction.transaction_time) if transaction.transaction_time else None,
                "counterparty_account": transaction.counterparty_account,
                "counterparty_name": transaction.counterparty_name,
                "status": transaction.status
            }

    # 查询处理人信息
    handler_name = None
    if alert.handler_id:
        handler = UserModel.get_by_id(alert.handler_id)
        handler_name = handler.username if handler else f"用户ID:{alert.handler_id}"

    # 构建返回数据
    result = {
        "id": alert.id,
        "alert_type": alert.rule_id,
        "alert_name": alert.rule_name,
        "alert_level": alert.severity,
        "customer_id": alert.customer_id,
        "customer_name": customer_name,
        "trigger_reason": alert.trigger_details.get("reason", "") if alert.trigger_details else "",
        "trigger_details": alert.trigger_details,
        "triggered_at": str(alert.created_at) if alert.created_at else None,
        "status": alert.status,
        "confidence": float(alert.confidence) if alert.confidence else 0.0,
        "need_override": alert.need_override,
        "handler_id": alert.handler_id,
        "handler_name": handler_name,
        "handled_at": str(alert.handled_at) if alert.handled_at else None,
        "handle_result": alert.handle_result,
        "related_transaction": transaction_info
    }

    return HttpResponse.ok(data=result, msg="查询成功")


@router.get("/stats")
def get_risk_stats(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    GET /api/wealth/risk/stats - 风险统计数据

    功能：
    - 为统计卡片提供数据
    - 返回今日预警总数、待处理数量、误报率、已上报数量

    返回格式：
    {
        "code": 0,
        "data": {
            "today_total": 12,
            "pending_count": 5,
            "false_positive_rate": 15.5,
            "reported_count": 3
        },
        "msg": "查询成功"
    }
    """
    # 认证
    user = _get_current_user(credentials)
    is_risk_officer, is_admin = _check_risk_permission(user.id)

    # 权限校验
    if not is_risk_officer and not is_admin:
        raise HTTPException(status_code=403, detail="您没有查看风险统计的权限")

    # 查询统计数据
    db = RiskAlertModel.get_db_connection()
    if not db:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    # 今日预警总数
    today_sql = f"""SELECT COUNT(*) as cnt FROM {RiskAlertModel.table_alias}
                    WHERE DATE(created_at) = CURDATE()"""
    today_result = db.execute(today_sql)
    today_total = today_result[0]['cnt'] if today_result else 0

    # 待处理数量
    pending_sql = f"""SELECT COUNT(*) as cnt FROM {RiskAlertModel.table_alias}
                      WHERE status = '待处理'"""
    pending_result = db.execute(pending_sql)
    pending_count = pending_result[0]['cnt'] if pending_result else 0

    # 误报率（近30天）
    false_positive_sql = f"""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = '误报' THEN 1 ELSE 0 END) as false_count
        FROM {RiskAlertModel.table_alias}
        WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
    """
    fp_result = db.execute(false_positive_sql)
    false_positive_rate = 0.0
    if fp_result and fp_result[0]['total'] > 0:
        false_positive_rate = round((fp_result[0]['false_count'] / fp_result[0]['total']) * 100, 1)

    # 已上报数量（已确认状态）
    reported_sql = f"""SELECT COUNT(*) as cnt FROM {RiskAlertModel.table_alias}
                       WHERE status = '已确认'"""
    reported_result = db.execute(reported_sql)
    reported_count = reported_result[0]['cnt'] if reported_result else 0

    return HttpResponse.ok(
        data={
            "today_total": today_total,
            "pending_count": pending_count,
            "false_positive_rate": false_positive_rate,
            "reported_count": reported_count
        },
        msg="查询成功"
    )


@router.get("/trend")
def get_risk_trend(
    days: int = Query(7, ge=1, le=30, description="查询天数"),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    GET /api/wealth/risk/trend - 风险趋势数据

    功能：
    - 返回最近N天的风险预警趋势
    - 包括每日预警数量、处理数量、误报数量

    返回格式：
    {
        "code": 0,
        "data": {
            "trend": [
                {
                    "date": "2026-08-10",
                    "total": 15,
                    "processed": 12,
                    "false_positive": 3
                }
            ]
        },
        "msg": "查询成功"
    }
    """
    # 认证
    user = _get_current_user(credentials)
    is_risk_officer, is_admin = _check_risk_permission(user.id)

    # 权限校验
    if not is_risk_officer and not is_admin:
        raise HTTPException(status_code=403, detail="您没有查看风险趋势的权限")

    db = RiskAlertModel.get_db_connection()
    if not db:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    # 查询最近N天的趋势数据
    trend_sql = f"""
        SELECT
            DATE(created_at) as date,
            COUNT(*) as total,
            SUM(CASE WHEN status IN ('处理中', '已确认', '误报') THEN 1 ELSE 0 END) as processed,
            SUM(CASE WHEN status = '误报' THEN 1 ELSE 0 END) as false_positive,
            SUM(CASE WHEN severity IN ('高', '严重') THEN 1 ELSE 0 END) as high,
            SUM(CASE WHEN severity = '中' THEN 1 ELSE 0 END) as medium,
            SUM(CASE WHEN severity = '低' THEN 1 ELSE 0 END) as low
        FROM {RiskAlertModel.table_alias}
        WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        GROUP BY DATE(created_at)
        ORDER BY date DESC
    """
    results = db.execute(trend_sql, (days,))

    # 构建返回数据
    trend_data = []
    for row in results:
        trend_data.append({
            "date": str(row['date']),
            "total": row['total'],
            "processed": row['processed'],
            "false_positive": row['false_positive']
            ,"high": row.get('high', 0), "medium": row.get('medium', 0), "low": row.get('low', 0)
        })

    return HttpResponse.ok(
        data={
            "trend": trend_data
        },
        msg="查询成功"
    )


@router.get("/reports")
def get_risk_reports(credentials: HTTPAuthorizationCredentials = Depends(security)):
    user = _get_current_user(credentials)
    is_risk_officer, is_admin = _check_risk_permission(user.id)
    if not is_risk_officer and not is_admin:
        raise HTTPException(status_code=403, detail="您没有查看风险报表的权限")
    db = RiskAlertModel.get_db_connection()
    if not db:
        raise HTTPException(status_code=500, detail="数据库连接失败")
    rows = db.execute(f"SELECT severity, status, COUNT(*) AS cnt FROM {RiskAlertModel.table_alias} GROUP BY severity, status")
    by_level, by_status = {}, {}
    for row in rows:
        raw_level = str(row['severity'] or '')
        level = '高' if raw_level in {'高', '高风险', 'high', 'HIGH', '严重', 'critical'} else '中' if raw_level in {'中', '中风险', '中高风险', 'medium', 'MEDIUM'} else '低'
        by_level[level] = by_level.get(level, 0) + int(row['cnt'])
        by_status[row['status']] = by_status.get(row['status'], 0) + int(row['cnt'])
    return HttpResponse.ok(data={"by_level": by_level, "by_status": by_status, "total": sum(by_level.values())}, msg="风险报表查询成功")


def register_risk_api(app):
    """注册风控API路由"""
    app.include_router(router)
