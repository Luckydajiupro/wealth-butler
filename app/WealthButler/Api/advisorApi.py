"""理财顾问 API 接口层

职责：
- 提供理财顾问工作台相关接口
- 包括客户列表查询、顾问统计数据、客户服务记录
- JWT认证，仅限理财顾问角色访问
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.Base.RicUtils.httpUtils import HttpResponse
from app.Base.Service.authService import AuthService
from app.WealthButler.Models.workOrderModel import WorkOrderModel
from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel
from app.WealthButler.Models.productModel import ProductModel
from app.WealthButler.Models.transactionModel import TransactionModel
from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel
from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
from app.WealthButler.Models.advisorAllocationPlanModel import AdvisorAllocationPlanModel
from app.Base.Models.userModel import UserModel
from app.Base.Models.BaseLLMConversationModel import BaseLLMConversationModel


router = APIRouter(prefix="/api/wealth/advisor", tags=["理财顾问"])
security = HTTPBearer(auto_error=False)

_ADVISORY_WORKORDER_SQL = """
    (
        COALESCE(intent_summary, description, title, '') LIKE '%%产品推荐%%'
        OR COALESCE(intent_summary, description, title, '') LIKE '%%推荐产品%%'
        OR COALESCE(intent_summary, description, title, '') LIKE '%%配置方案%%'
        OR COALESCE(intent_summary, description, title, '') LIKE '%%产品配置%%'
        OR COALESCE(intent_summary, description, title, '') LIKE '%%组合诊断%%'
        OR COALESCE(intent_summary, description, title, '') LIKE '%%适当性%%'
    )
    AND COALESCE(intent_summary, description, title, '') NOT LIKE '%%申购%%'
    AND COALESCE(intent_summary, description, title, '') NOT LIKE '%%赎回%%'
    AND COALESCE(intent_summary, description, title, '') NOT LIKE '%%转账%%'
"""


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


def _get_advisor_context(credentials: HTTPAuthorizationCredentials):
    """Return the authenticated advisor and whether they may manage all customers."""
    user = _get_current_user(credentials)
    business_user = BaseUserExtModel.get_by_id(user.id)
    role_info = AuthService.get_user_role_info(
        user.id, getattr(user, "source_module", None)
    )
    is_super_admin = bool(role_info.get("is_super_admin"))
    is_advisor = (
        business_user is not None
        and business_user.user_type == "EMPLOYEE"
        and (
            getattr(business_user, "employee_role", None) == "理财顾问"
            or "advisor" in role_info.get("role_names", [])
        )
    )
    if not is_advisor and not is_super_admin:
        raise HTTPException(status_code=403, detail="该接口仅限理财顾问或超级管理员访问")
    return user, is_super_admin


def _serialize(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if hasattr(value, "model_dump"):
        return _serialize(value.model_dump())
    return value


def _require_customer_scope(advisor_id: int, customer_id: int, can_manage_all: bool) -> None:
    if can_manage_all:
        return
    from app.WealthButler.Service.advisorService import AdvisorService

    if not AdvisorService.advisor_can_access_customer(advisor_id, customer_id):
        raise HTTPException(status_code=403, detail="该客户不在当前顾问的服务范围内")


def _build_recommendation_reason(item: dict, customer_risk_level: Optional[str]) -> str:
    factors = item.get("factor_scores") or {}
    reasons = []
    product_risk = item.get("risk_level")
    if customer_risk_level and product_risk:
        reasons.append(f"客户{customer_risk_level}风险承受能力与产品{product_risk}相适配")
    if float(factors.get("preference_score", 0) or 0) >= 0.7:
        reasons.append("产品类型与客户偏好匹配")
    if float(factors.get("term_score", 0) or 0) >= 0.7:
        reasons.append("赎回周期符合客户流动性偏好")
    if float(factors.get("diversification_score", 0) or 0) >= 0.8:
        reasons.append("有助于分散现有持仓的行业集中度")
    if item.get("period_return") is not None:
        reasons.append("近期净值表现已纳入排序，但不代表未来收益")
    if len(reasons) == 1:
        reasons.append("综合风险、期限、偏好及持仓分散度后进入候选方案")
    return "；".join(reasons) + "。"


@router.get("/clients")
def get_advisor_clients(
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    GET /api/wealth/advisor/clients - 查询理财顾问的客户列表

    功能：
    - JWT认证
    - 返回客户基本信息和风险等级
    - 关联客户画像数据

    返回格式：
    {
        "code": 0,
        "data": {
            "clients": [
                {
                    "id": 1,
                    "name": "张先生",
                    "risk_level": "C3",
                    "total_assets": 500000.00
                }
            ],
            "total": 10
        },
        "msg": "查询成功"
    }
    """
    # 认证
    advisor, can_manage_all = _get_advisor_context(credentials)

    db = UserModel.get_db_connection()
    if not db:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    # 查询客户总数
    if can_manage_all:
        scope_sql = f"""
        FROM base_user u
        WHERE u.user_type = 'CUSTOMER' AND u.deleted_at IS NULL
        """
        scope_params = ()
    else:
        scope_sql = f"""
        FROM base_user u
        WHERE u.user_type = 'CUSTOMER'
          AND u.deleted_at IS NULL
          AND (
              EXISTS (
                  SELECT 1 FROM fin_customer_profile p
                  WHERE p.customer_id = u.id AND p.advisor_id = %s
              )
              OR EXISTS (
                  SELECT 1 FROM biz_work_order w
                  WHERE w.customer_id = u.id AND w.handled_by = %s
                    AND w.status IN ('处理中', '待审核')
                    AND w.deleted_at IS NULL
                    AND {_ADVISORY_WORKORDER_SQL}
              )
          )
        """
        scope_params = (advisor.id, advisor.id)
    count_sql = f"SELECT COUNT(*) AS total {scope_sql}"
    count_result = db.execute(count_sql, scope_params)
    total = count_result[0]['total'] if count_result else 0

    # 查询客户列表
    clients_sql = f"""
        SELECT u.id, u.username, u.phone, u.email, u.created_at
        {scope_sql}
        ORDER BY u.created_at DESC
        LIMIT %s OFFSET %s
    """
    clients_result = db.execute(clients_sql, scope_params + (limit, offset))

    # 构建返回数据
    clients_data = []
    for client in clients_result:
        # 工作台只展示当前有效风评，不能把画像中的历史等级当作适当性依据。
        assessment = RiskAssessmentModel.find_valid_by_customer_id(client['id'])

        clients_data.append({
            "id": client['id'],
            "name": client['username'],
            "phone": client.get('phone', 'N/A'),
            "risk_level": assessment.risk_level if assessment else None,
            "risk_score": float(assessment.total_score) if assessment else None,
            "created_at": str(client['created_at']) if client.get('created_at') else None
        })

    return HttpResponse.ok(
        data={
            "clients": clients_data,
            "total": total,
            "scope": "all" if can_manage_all else "assigned",
        },
        msg="查询成功"
    )


@router.get("/clients/{customer_id}/profile")
def get_advisor_customer_profile(
    customer_id: int,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Return the selected customer's business profile within advisor scope."""
    advisor, can_manage_all = _get_advisor_context(credentials)
    _require_customer_scope(advisor.id, customer_id, can_manage_all)

    db = UserModel.get_db_connection()
    if not db:
        raise HTTPException(status_code=500, detail="数据库连接失败")
    rows = db.execute(
        f"""
        SELECT id, username, phone, email, created_at
        FROM base_user
        WHERE id = %s AND user_type = 'CUSTOMER' AND deleted_at IS NULL
        LIMIT 1
        """,
        (customer_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="客户不存在")

    customer = rows[0]
    profile = CustomerProfileModel.find_by_customer_id(customer_id)
    assessment = RiskAssessmentModel.find_valid_by_customer_id(customer_id)
    return HttpResponse.ok(data={
        "customer": {
            "id": customer["id"],
            "name": customer["username"],
            "phone": customer.get("phone"),
            "email": customer.get("email"),
            "created_at": _serialize(customer.get("created_at")),
        },
        "profile": _serialize(profile) if profile else None,
        "assessment": _serialize(assessment) if assessment else None,
    })


@router.get("/clients/{customer_id}/analysis-records")
def get_advisor_analysis_records(
    customer_id: int,
    limit: int = Query(20, ge=1, le=50),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Return persisted AdvisorAgent conclusions for an in-scope customer."""
    advisor, can_manage_all = _get_advisor_context(credentials)
    _require_customer_scope(advisor.id, customer_id, can_manage_all)
    session_id = f"advisor_dashboard_advisor_{advisor.id}_{customer_id}"
    records = BaseLLMConversationModel.find_by(
        user_id=str(advisor.id),
        session_id=session_id,
        ai_agent="AdvisorAgent",
        status="success",
        limit=limit,
        order_by="created_at",
        order="DESC",
    )
    return HttpResponse.ok(data={
        "items": [
            {
                "id": record.id,
                "question": record.question,
                "answer": record.get_answer,
                "created_at": _serialize(record.created_at),
                "duration_ms": record.duration_ms,
            }
            for record in records
        ],
        "total": len(records),
    })


@router.post("/clients/{customer_id}/allocation-plan")
def generate_advisor_allocation_plan(
    customer_id: int,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Build a read-only product allocation proposal for an in-scope customer."""
    advisor, can_manage_all = _get_advisor_context(credentials)
    _require_customer_scope(advisor.id, customer_id, can_manage_all)

    from app.WealthButler.Service.advisorService import AdvisorService

    result = AdvisorService().recommend_products(
        customer_id,
        graph_query=None,
        vector_scores={},
        top_k=4,
    )
    recommendations = result.get("recommendations") or []
    assessment = result.get("context", {}).get("risk_assessment") or {}
    customer_risk_level = assessment.get("risk_level")
    score_total = sum(max(float(item.get("score", 0) or 0), 0.01) for item in recommendations)
    allocated = 0.0
    items = []
    for index, recommendation in enumerate(recommendations):
        item = dict(recommendation)
        if index == len(recommendations) - 1:
            allocation_percent = round(100.0 - allocated, 1)
        else:
            allocation_percent = round(
                max(float(item.get("score", 0) or 0), 0.01) / score_total * 100.0,
                1,
            )
            allocated += allocation_percent
        item["allocation_percent"] = allocation_percent
        item["recommendation_reason"] = _build_recommendation_reason(
            item, customer_risk_level
        )
        items.append(_serialize(item))

    disclaimer = "本方案仅供顾问与客户沟通，不构成收益承诺，也不会自动创建交易。"
    persisted_plan = AdvisorAllocationPlanModel(
        customer_id=customer_id,
        advisor_id=advisor.id,
        risk_level=customer_risk_level,
        products=items,
        disclaimer=disclaimer,
    )
    if persisted_plan.save() <= 0:
        raise HTTPException(status_code=500, detail="配置方案保存失败，请稍后重试")

    return HttpResponse.ok(data={
        "id": persisted_plan.id,
        "customer_id": customer_id,
        "advisor_id": advisor.id,
        "risk_level": customer_risk_level,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "products": items,
        "disclaimer": disclaimer,
    })


@router.get("/today-clients")
def get_today_service_clients(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Return customers actually served by the current advisor today."""
    advisor, _can_manage_all = _get_advisor_context(credentials)
    db = UserModel.get_db_connection()
    if not db:
        raise HTTPException(status_code=500, detail="数据库连接失败")
    rows = db.execute(
        f"""
        SELECT DISTINCT u.id, u.username, u.phone,
               MAX(activity.activity_time) AS activity_time
        FROM base_user u
        JOIN (
            SELECT customer_id, COALESCE(handled_at, updated_at) AS activity_time
            FROM biz_work_order
            WHERE handled_by = %s
              AND DATE(COALESCE(handled_at, updated_at)) = CURDATE()
              AND deleted_at IS NULL
              AND {_ADVISORY_WORKORDER_SQL}
        ) activity ON activity.customer_id = u.id
        WHERE u.user_type = 'CUSTOMER' AND u.deleted_at IS NULL
        GROUP BY u.id, u.username, u.phone
        ORDER BY activity_time DESC
        """,
        (advisor.id,),
    )
    clients = []
    for row in rows or []:
        assessment = RiskAssessmentModel.find_valid_by_customer_id(row["id"])
        clients.append({
            "id": row["id"],
            "name": row["username"],
            "phone": row.get("phone"),
            "risk_level": assessment.risk_level if assessment else None,
            "risk_score": float(assessment.total_score) if assessment else None,
            "activity_time": str(row["activity_time"]) if row.get("activity_time") else None,
        })
    return HttpResponse.ok(data={"clients": clients, "total": len(clients)}, msg="查询成功")


@router.get("/transactions")
def get_advisor_transactions(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Return this month's transactions initiated by the current advisor."""
    advisor, _can_manage_all = _get_advisor_context(credentials)
    db = TransactionModel.get_db_connection()
    if not db:
        raise HTTPException(status_code=500, detail="数据库连接失败")
    count_rows = db.execute(
        """SELECT COUNT(*) AS total FROM fin_transaction
           WHERE employee_id = %s
             AND transaction_time >= DATE_FORMAT(CURDATE(), '%%Y-%%m-01')""",
        (advisor.id,),
    )
    rows = db.execute(
        """
        SELECT t.id, t.customer_id, u.username AS customer_name,
               t.transaction_type, t.amount, t.fee, t.status,
               t.transaction_time, p.product_name, p.product_code
        FROM fin_transaction t
        LEFT JOIN base_user u ON u.id = t.customer_id
        LEFT JOIN fin_product p ON p.id = t.product_id
        WHERE t.employee_id = %s
          AND t.transaction_time >= DATE_FORMAT(CURDATE(), '%%Y-%%m-01')
        ORDER BY t.transaction_time DESC
        LIMIT %s OFFSET %s
        """,
        (advisor.id, limit, offset),
    )
    items = [{
        **row,
        "amount": float(row["amount"] or 0),
        "fee": float(row["fee"] or 0),
        "transaction_time": str(row["transaction_time"]) if row.get("transaction_time") else None,
    } for row in (rows or [])]
    total = int(count_rows[0]["total"]) if count_rows else 0
    return HttpResponse.ok(data={"items": items, "total": total, "limit": limit, "offset": offset})


@router.get("/products")
def get_advisor_products(
    keyword: Optional[str] = Query(None, max_length=100),
    product_type: Optional[str] = None,
    risk_level: Optional[str] = None,
    status: Optional[str] = "在售",
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Advisor product library backed by fin_product."""
    _get_advisor_context(credentials)
    filters = {
        key: value for key, value in {
            "product_type": product_type,
            "risk_level": risk_level,
            "status": status,
        }.items() if value
    }
    products = ProductModel.find_by(order_by="updated_at", order="DESC", **filters)
    if keyword:
        normalized = keyword.casefold()
        products = [
            product for product in products
            if normalized in f"{product.product_name} {product.product_code}".casefold()
        ]
    total = len(products)
    items = []
    for product in products[offset:offset + limit]:
        item = product.model_dump()
        for field in ("nav", "min_investment"):
            if item.get(field) is not None:
                item[field] = float(item[field])
        for field in ("nav_date", "updated_at"):
            if item.get(field) is not None:
                item[field] = str(item[field])
        items.append(item)
    return HttpResponse.ok(data={"items": items, "total": total, "limit": limit, "offset": offset})


@router.get("/stats")
def get_advisor_stats(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    GET /api/wealth/advisor/stats - 理财顾问统计数据

    功能：
    - 今日服务客户数
    - 本月完成交易笔数
    - 待处理工单数

    返回格式：
    {
        "code": 0,
        "data": {
            "today_customer_count": 5,
            "month_transaction_count": 120,
            "pending_workorder_count": 3
        },
        "msg": "查询成功"
    }
    """
    # 认证
    user, _can_manage_all = _get_advisor_context(credentials)

    db = WorkOrderModel.get_db_connection()
    if not db:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    # 今日服务客户数：只统计当前顾问实际处理的投顾类事项。
    today_sql = f"""
        SELECT COUNT(DISTINCT customer_id) AS cnt
        FROM biz_work_order
        WHERE handled_by = %s
          AND DATE(COALESCE(handled_at, updated_at)) = CURDATE()
          AND deleted_at IS NULL
          AND {_ADVISORY_WORKORDER_SQL}
    """
    today_result = db.execute(today_sql, (user.id,))
    today_customer_count = today_result[0]['cnt'] if today_result else 0

    # 本月完成投顾服务数，不把申购、赎回等运营交易计入顾问业绩。
    month_sql = f"""
        SELECT COUNT(*) as cnt
        FROM biz_work_order
        WHERE handled_by = %s
          AND status = '已完成'
          AND completed_at >= DATE_FORMAT(CURDATE(), '%%Y-%%m-01')
          AND deleted_at IS NULL
          AND {_ADVISORY_WORKORDER_SQL}
    """
    month_result = db.execute(month_sql, (user.id,))
    month_advisory_count = month_result[0]['cnt'] if month_result else 0

    # 待处理工单数
    pending_sql = f"""
        SELECT COUNT(*) as cnt
        FROM {WorkOrderModel.table_alias}
        WHERE status = '待处理'
        AND deleted_at IS NULL
        AND order_type = '客户转介'
        AND {_ADVISORY_WORKORDER_SQL}
    """
    pending_result = db.execute(pending_sql)
    pending_workorder_count = pending_result[0]['cnt'] if pending_result else 0

    return HttpResponse.ok(
        data={
            "today_customer_count": today_customer_count,
            "month_advisory_count": month_advisory_count,
            "month_transaction_count": month_advisory_count,
            "pending_workorder_count": pending_workorder_count
        },
        msg="查询成功"
    )


def register_advisor_api(app):
    """注册理财顾问API路由"""
    app.include_router(router)
