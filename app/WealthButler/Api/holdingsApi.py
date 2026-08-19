"""持仓查询 API 接口层

职责：
- 提供客户持仓查询接口
- JWT认证，客户只能查询自己的持仓
- 关联产品信息，返回持仓详情和汇总统计

接口列表：
- GET /api/wealth/holdings - 查询当前登录客户的持仓列表

依赖：
- AuthService: JWT认证和用户验证
- HoldingsModel: 持仓数据查询
- ProductModel: 产品信息关联
"""
from datetime import date, datetime
import hashlib
import json
import logging
from typing import Optional, Dict, Any, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from decimal import Decimal
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from app.Base.RicUtils.httpUtils import HttpResponse
from app.Base.Service.authService import AuthService
from app.WealthButler.Models.holdingsModel import HoldingsModel
from app.WealthButler.Models.productModel import ProductModel
from app.WealthButler.Models.productNavHistoryModel import ProductNavHistoryModel
from app.WealthButler.Models.transactionModel import TransactionModel
from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel
from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel
from app.WealthButler.Service.productService import ProductService


router = APIRouter(prefix="/api/wealth/holdings", tags=["持仓管理"])
customer_router = APIRouter(prefix="/api/wealth/customer", tags=["客户工作台"])
security = HTTPBearer(auto_error=False)


class CustomerOperationConfirmRequest(BaseModel):
    action: Literal["confirm", "cancel"]


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


def _get_customer(credentials: HTTPAuthorizationCredentials):
    user = _get_current_user(credentials)
    business_user = BaseUserExtModel.get_by_id(user.id)
    if business_user is None or business_user.user_type != "CUSTOMER":
        raise HTTPException(status_code=403, detail="该接口仅限客户本人访问")
    return user


def _as_date(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _simulated_daily_rate(customer_id: int, product, as_of_date: date) -> Decimal:
    """Generate a stable daily percentage within a product-appropriate range."""
    product_type = str(getattr(product, "product_type", "") or "")
    product_name = str(getattr(product, "product_name", "") or "")
    product_category = f"{product_type} {product_name}"
    risk_level = str(getattr(product, "risk_level", "R3") or "R3").upper()
    if "货币" in product_category:
        low, high = Decimal("0.0100"), Decimal("0.0200")
    elif "保险" in product_category:
        low, high = Decimal("0.0100"), Decimal("0.0200")
    else:
        low, high = {
            "R1": (Decimal("-0.0500"), Decimal("0.0800")),
            "R2": (Decimal("-0.1500"), Decimal("0.2000")),
            "R3": (Decimal("-0.5000"), Decimal("0.6000")),
            "R4": (Decimal("-1.2000"), Decimal("1.4000")),
            "R5": (Decimal("-2.0000"), Decimal("2.3000")),
        }.get(risk_level, (Decimal("-0.5000"), Decimal("0.6000")))
    seed = f"{as_of_date.isoformat()}:{customer_id}:{getattr(product, 'id', 0)}"
    sample = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:8], "big")
    fraction = Decimal(sample) / Decimal(2**64 - 1)
    return (low + (high - low) * fraction).quantize(Decimal("0.01"))


def _simulate_portfolio_profit(customer_id: int, holdings, products, as_of_date: date):
    total_value = Decimal("0")
    total_profit = Decimal("0")
    for holding, product in zip(holdings, products):
        holding_value = getattr(holding, "current_value", None)
        if holding_value is None:
            holding_value = Decimal(holding.shares or 0) * Decimal(getattr(product, "nav", 0) or 0)
        holding_value = Decimal(holding_value or 0)
        rate = _simulated_daily_rate(customer_id, product, as_of_date)
        total_value += holding_value
        total_profit += holding_value * rate / Decimal("100")
    portfolio_rate = total_profit / total_value * Decimal("100") if total_value else Decimal("0")
    return total_profit, portfolio_rate, total_value


@router.get("")
def get_holdings(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    GET /api/wealth/holdings - 查询当前登录客户的持仓列表

    功能：
    - JWT认证，从token解析customer_id
    - 返回该客户所有持仓（份额>0）
    - 关联产品表获取产品名称、编码
    - 计算持仓总市值和总盈亏

    返回格式：
    {
        "code": 0,
        "data": {
            "holdings": [
                {
                    "id": 1,
                    "product_name": "XX货币基金",
                    "product_code": "001234",
                    "shares": 10000,
                    "cost_amount": 10000.00,
                    "current_value": 10500.00,
                    "profit_loss": 500.00,
                    "profit_ratio": 5.0
                }
            ],
            "total_value": 10500.00,
            "total_profit": 500.00
        },
        "msg": "查询成功"
    }
    """
    # 认证并获取客户ID
    user = _get_current_user(credentials)
    customer_id = user.id

    # 查询客户所有持仓
    holdings_list = HoldingsModel.find_by_customer_id(customer_id)

    if not holdings_list:
        return HttpResponse.ok(
            data={
                "holdings": [],
                "total_value": 0.00,
                "total_profit": 0.00
            },
            msg="暂无持仓"
        )

    # 关联产品信息
    result_holdings = []
    total_value = Decimal("0")
    total_profit = Decimal("0")

    for holding in holdings_list:
        # 查询产品信息
        product = ProductModel.get_by_id(holding.product_id)

        # 构建返回数据
        holding_data = {
            "id": holding.id,
            "product_id": holding.product_id,
            "product_name": product.product_name if product else f"产品ID:{holding.product_id}",
            "product_code": product.product_code if product else "N/A",
            "product_type": product.product_type if product else "其他",
            "risk_level": product.risk_level if product else None,
            "shares": float(holding.shares),
            "cost_amount": float(holding.cost_amount) if holding.cost_amount else 0.00,
            "current_value": float(holding.current_value) if holding.current_value else 0.00,
            "profit_loss": float(holding.profit_loss) if holding.profit_loss else 0.00,
            "profit_ratio": float(holding.profit_ratio) if holding.profit_ratio else 0.00,
        }

        result_holdings.append(holding_data)

        # 累计总市值和总盈亏
        if holding.current_value:
            total_value += holding.current_value
        if holding.profit_loss:
            total_profit += holding.profit_loss

    return HttpResponse.ok(
        data={
            "holdings": result_holdings,
            "total_value": float(total_value),
            "total_profit": float(total_profit)
        },
        msg="查询成功"
    )


def calculate_today_profit(customer_id: int) -> dict:
    """Calculate the customer daily profit for both REST and Agent callers."""
    holdings = HoldingsModel.find_by_customer_id(customer_id)
    if not holdings:
        return {
            "today_profit": 0.0,
            "today_profit_rate": 0.0,
            "total_value": 0.0,
            "as_of_date": date.today().isoformat(),
            "calculation_source": "no_holdings",
            "estimated_product_ids": [],
        }

    today = date.today()
    total_profit = Decimal("0")
    opening_value = Decimal("0")
    missing_products = []
    products = []
    for holding in holdings:
        product = ProductModel.get_by_id(holding.product_id)
        products.append(product)
        current_date = _as_date(product.nav_date) if product else None
        if product is None or product.nav is None or current_date != today:
            missing_products.append(holding.product_id)
            continue
        previous = ProductNavHistoryModel.find_latest_before(holding.product_id, today)
        if previous is None:
            missing_products.append(holding.product_id)
            continue
        shares = Decimal(holding.shares or 0)
        total_profit += shares * (Decimal(product.nav) - Decimal(previous.nav))
        opening_value += shares * Decimal(previous.nav)

    if missing_products:
        total_profit, rate, total_value = _simulate_portfolio_profit(
            customer_id, holdings, products, today
        )
        return {
            "today_profit": float(total_profit.quantize(Decimal("0.01"))),
            "today_profit_rate": float(rate.quantize(Decimal("0.01"))),
            "total_value": float(total_value.quantize(Decimal("0.01"))),
            "as_of_date": today.isoformat(),
            "calculation_source": "simulated",
            "estimated_product_ids": sorted(set(missing_products)),
        }

    rate = (total_profit / opening_value * Decimal("100")) if opening_value else Decimal("0")
    return {
        "today_profit": float(total_profit.quantize(Decimal("0.01"))),
        "today_profit_rate": float(rate.quantize(Decimal("0.01"))),
        "total_value": float((opening_value + total_profit).quantize(Decimal("0.01"))),
        "as_of_date": today.isoformat(),
        "calculation_source": "market_nav",
        "estimated_product_ids": [],
    }


@router.get("/profit-today")
def get_today_profit(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Return the authenticated customer's daily profit."""
    user = _get_customer(credentials)
    data = calculate_today_profit(user.id)
    message = (
        "净值数据未齐，已按产品风险生成当日模拟收益"
        if data["calculation_source"] == "simulated"
        else "查询成功"
    )
    return HttpResponse.ok(data=data, msg=message)


@customer_router.get("/transactions")
def get_customer_transactions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """查询当前客户自己的真实交易流水。"""
    user = _get_customer(credentials)
    db = TransactionModel.get_db_connection()
    if db is None:
        raise HTTPException(status_code=500, detail="数据库连接失败")
    rows = db.execute(
        "SELECT t.id, t.transaction_type, t.amount, t.shares, t.nav, t.fee, "
        "t.channel, t.status, t.transaction_time, t.employee_id, "
        "p.product_name, p.product_code, e.username AS employee_name "
        "FROM fin_transaction t LEFT JOIN fin_product p ON p.id = t.product_id "
        "LEFT JOIN base_user e ON e.id = t.employee_id "
        "WHERE t.customer_id = %s ORDER BY t.transaction_time DESC LIMIT %s OFFSET %s",
        (user.id, limit, offset),
    )
    count_rows = db.execute(
        "SELECT COUNT(*) AS total FROM fin_transaction WHERE customer_id = %s",
        (user.id,),
    )
    items = []
    for row in rows:
        items.append({
            "id": row["id"],
            "transaction_type": row["transaction_type"],
            "amount": float(row["amount"]),
            "shares": float(row["shares"]) if row.get("shares") is not None else None,
            "nav": float(row["nav"]) if row.get("nav") is not None else None,
            "fee": float(row.get("fee") or 0),
            "channel": row.get("channel"),
            "employee_id": row.get("employee_id"),
            "employee_name": row.get("employee_name"),
            "status": row["status"],
            "transaction_time": str(row["transaction_time"]),
            "product_name": row.get("product_name") or "非产品交易",
            "product_code": row.get("product_code"),
        })
    total = int(count_rows[0]["total"]) if count_rows else 0
    return HttpResponse.ok(data={"items": items, "total": total, "limit": limit, "offset": offset})


@customer_router.get("/products")
def get_customer_products(
    limit: int = Query(50, ge=1, le=100),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """返回与当前客户风险等级匹配的真实在售产品。"""
    user = _get_customer(credentials)
    assessment = RiskAssessmentModel.find_valid_by_customer_id(user.id)
    if assessment is None:
        raise HTTPException(status_code=409, detail="请先完成有效的风险测评后查看适配产品")
    customer_risk = assessment.risk_level
    products = ProductService.get_suitable_products_for_customer(customer_risk, limit=limit)
    items = [{
        "id": product.id,
        "product_code": product.product_code,
        "product_name": product.product_name,
        "product_type": product.product_type,
        "risk_level": product.risk_level,
        "nav": float(product.nav) if product.nav is not None else None,
        "nav_date": _as_date(product.nav_date).isoformat() if _as_date(product.nav_date) else None,
        "min_investment": float(product.min_investment) if product.min_investment is not None else None,
        "redemption_period_days": product.redemption_period_days,
        "status": product.status,
    } for product in products]
    return HttpResponse.ok(data={"items": items, "total": len(items), "customer_risk_level": customer_risk})


@customer_router.get("/risk-assessment/status")
def get_customer_risk_assessment_status(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Return whether the authenticated customer has a current suitability assessment."""
    user = _get_customer(credentials)
    current = RiskAssessmentModel.find_valid_by_customer_id(user.id)
    latest = current or RiskAssessmentModel.find_latest_by_customer_id(user.id)
    status = "valid" if current else ("expired" if latest else "missing")
    return HttpResponse.ok(data={
        "status": status,
        "required": current is None,
        "risk_level": current.risk_level if current else None,
        "total_score": float(current.total_score) if current else None,
        "assessment_time": str(latest.assessment_time) if latest else None,
        "valid_until": str(latest.valid_until) if latest else None,
    })


@customer_router.get("/notifications")
def get_customer_notifications(
    limit: int = Query(50, ge=1, le=100),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Return asynchronous Agent results addressed to the authenticated customer."""
    user = _get_customer(credentials)
    try:
        from app.Base.Client.redisClient import redis_client

        values = redis_client.client.lrange(f"notifications:user:{user.id}", 0, limit - 1)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="通知服务暂时不可用") from exc

    items = []
    notification_key = f"notifications:user:{user.id}"
    from app.WealthButler.Service.chatService import ChatService
    operator_runtime = ChatService._operator_runtime
    for value in values or []:
        try:
            notification = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            continue
        notification_type = notification.get("type")
        if notification_type not in {"work_order_result", "operation_confirmation", "compliance_evidence"} or notification.get("customer_id") != user.id:
            continue
        if notification_type == "operation_confirmation":
            confirm_token = notification.get("confirm_token")
            # Redis notifications are durable, while confirmation records are
            # consumed/expired in the runtime store. Do not expose a stale
            # confirmation card after a page refresh.
            pending = None
            if operator_runtime is not None and confirm_token:
                try:
                    pending = operator_runtime.service.confirmation_service.get_pending(confirm_token)
                except Exception:
                    logger.exception("确认状态读取失败: customer_id=%s", user.id)
            if pending is None or pending.status != "待确认":
                try:
                    redis_client.client.lrem(notification_key, 0, value)
                except Exception:
                    logger.exception("过期确认通知清理失败: customer_id=%s", user.id)
                continue
            items.append({
                "id": str(notification.get("id") or ""),
                "type": "operation_confirmation",
                "confirm_token": confirm_token,
                "operation_intent": notification.get("operation_intent"),
                "operation_params": notification.get("operation_params") or {},
                "operator_id": notification.get("operator_id"),
                "status": notification.get("status") or "待确认",
                "message": str(notification.get("message") or ""),
                "created_at": notification.get("created_at"),
                "expires_at": notification.get("expires_at"),
            })
            continue
        if notification_type == "compliance_evidence":
            items.append({
                "id": str(notification.get("id") or ""),
                "type": "compliance_evidence",
                "workorder_id": notification.get("workorder_id"),
                "product_id": notification.get("product_id"),
                "evidence_type": notification.get("evidence_type"),
                "status": notification.get("status") or "已完成",
                "operator_id": notification.get("operator_id"),
                "operator_name": notification.get("operator_name"),
                "message": str(notification.get("message") or ""),
                "created_at": notification.get("created_at"),
            })
            continue
        items.append({
            "id": str(notification.get("event_id") or notification.get("id") or ""),
            "event_id": str(notification.get("event_id") or notification.get("id") or ""),
            "type": "work_order_result",
            "order_id": notification.get("order_id"),
            "business_subtype": notification.get("business_subtype"),
            "session_id": notification.get("session_id"),
            "handler_id": notification.get("handler_id"),
            "handler_name": notification.get("handler_name"),
            "trace_id": notification.get("trace_id"),
            "status": notification.get("status"),
            "message": str(notification.get("message") or ""),
            "created_at": notification.get("created_at"),
        })
    return HttpResponse.ok(data={"items": items, "total": len(items)})


@customer_router.post("/operation-confirmations/{confirm_token}")
def confirm_customer_operation(
    confirm_token: str,
    request: CustomerOperationConfirmRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Confirm or cancel an operator draft as the authenticated customer."""
    user = _get_customer(credentials)
    from app.WealthButler.Service.chatService import ChatService

    runtime = ChatService._operator_runtime
    if runtime is None:
        raise HTTPException(status_code=503, detail="业务操作运行时尚未配置")
    pending = runtime.service.confirmation_service.get_pending(confirm_token)
    if pending is None:
        raise HTTPException(status_code=404, detail="确认请求不存在或已过期")
    if pending.customer_id != user.id:
        raise HTTPException(status_code=403, detail="无权确认其他客户的业务操作")

    result = runtime.confirm(pending.employee_id, confirm_token, request.action)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message") or "确认操作失败")
    try:
        from app.Base.Client.redisClient import redis_client
        operator_notification = {
            "id": f"customer-confirmation-result:{confirm_token}:{request.action}",
            "type": "customer_confirmation_result",
            "operator_id": pending.employee_id,
            "customer_id": user.id,
            "customer_name": getattr(user, "username", None),
            "confirm_token": confirm_token,
            "action": request.action,
            "status": "已确认" if request.action == "confirm" else "已取消",
            "result": result,
            "created_at": datetime.now().isoformat(),
        }
        operator_key = f"notifications:operator:{pending.employee_id}"
        redis_client.client.lpush(operator_key, json.dumps(operator_notification, ensure_ascii=False, default=str))
        redis_client.client.ltrim(operator_key, 0, 199)
    except Exception:
        logger.exception("客户确认结果通知客户经理失败: operator_id=%s", pending.employee_id)
    try:
        from app.Base.Client.redisClient import redis_client
        key = f"notifications:user:{user.id}"
        values = redis_client.client.lrange(key, 0, -1) or []
        for value in values:
            try:
                item = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                continue
            if item.get("type") == "operation_confirmation" and item.get("confirm_token") == confirm_token:
                redis_client.client.lrem(key, 0, value)
                break
    except Exception:
        logger.exception("确认通知消费失败: customer_id=%s", user.id)
    return HttpResponse.ok(data=result)


def register_holdings_api(app):
    """注册持仓API路由"""
    app.include_router(router)
    app.include_router(customer_router)
