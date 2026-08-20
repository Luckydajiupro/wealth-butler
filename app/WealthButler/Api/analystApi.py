"""数据分析师 API 接口层

职责：
- 提供数据分析师工作台相关接口
- 包括查询历史记录、数据分析相关功能
- JWT认证,仅限数据分析师角色访问
"""
from typing import Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta
from pydantic import BaseModel

from app.Base.Models.roleModel import Permission
from app.Base.RicUtils.httpUtils import HttpResponse
from app.Base.Service.authService import AuthService
from app.WealthButler.Models.conversationArchiveModel import ConversationArchiveModel
from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel
from app.WealthButler.Models.transactionModel import TransactionModel
from app.WealthButler.Models.holdingsModel import HoldingsModel


router = APIRouter(prefix="/api/wealth/analyst", tags=["数据分析师"])
security = HTTPBearer(auto_error=False)


class RiskAssessmentSubmit(BaseModel):
    """风险评估提交请求体"""
    customer_id: int
    answers: Dict[str, str]


def _get_current_user(credentials: HTTPAuthorizationCredentials):
    """获取业务管理员，并同时校验数据分析权限。"""
    if not credentials:
        raise HTTPException(status_code=401, detail="缺少认证信息")
    user = AuthService.get_current_user(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账户已被禁用")
    source_module = getattr(user, "source_module", None)
    role_info = AuthService.get_user_role_info(user.id, source_module)
    role_names = role_info.get("role_names", []) if isinstance(role_info, dict) else []
    if "business_admin" not in role_names:
        raise HTTPException(status_code=403, detail="仅限业务管理员访问")
    if not AuthService.has_permission(user.id, Permission.DATA_NL2SQL_QUERY, source_module):
        raise HTTPException(status_code=403, detail=f"缺少权限: {Permission.DATA_NL2SQL_QUERY}")
    return user


@router.get("/query-history")
def get_query_history(
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    GET /api/wealth/analyst/query-history - 查询历史记录

    功能：
    - 返回用户的历史查询记录
    - 按时间倒序排列
    - 包含查询类型、查询内容、查询时间

    返回格式：
    {
        "code": 0,
        "data": {
            "queries": [
                {
                    "id": 1,
                    "query_type": "客户画像",
                    "query_content": "查询客户ID 123的风险等级",
                    "result_summary": "客户风险等级：C3",
                    "created_at": "2026-08-16 10:30:00"
                }
            ],
            "total": 50
        },
        "msg": "查询成功"
    }
    """
    # 认证
    user = _get_current_user(credentials)

    # 查询会话归档表获取历史记录
    db = ConversationArchiveModel.get_db_connection()
    if not db:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    # 查询总数
    count_sql = f"""
        SELECT COUNT(*) as total
        FROM {ConversationArchiveModel.table_alias}
        WHERE customer_id = %s AND role = 'user'
    """
    count_result = db.execute(count_sql, (user.id,))
    total = count_result[0]['total'] if count_result else 0

    # 查询历史记录
    query_sql = f"""
        SELECT
            id,
            session_id,
            agent_type,
            content,
            created_at
        FROM {ConversationArchiveModel.table_alias}
        WHERE customer_id = %s AND role = 'user'
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """
    results = db.execute(query_sql, (user.id, limit, offset))

    # 构建返回数据
    queries_data = []
    for row in results:
        # 根据agent_type映射查询类型
        query_type_map = {
            'analyst': '数据分析',
            'advisor': '投顾咨询',
            'risk': '风险监控',
            'operator': '业务操作',
            'customer_service': '客户服务'
        }
        query_type = query_type_map.get(row.get('agent_type'), '未知类型')

        # 提取查询内容
        query_content = row.get('content', '')[:100]  # 截取前100字符
        result_summary = '已处理'  # 简化版不返回详细响应

        queries_data.append({
            "id": row['id'],
            "session_id": row.get('session_id'),
            "query_type": query_type,
            "query_content": query_content,
            "result_summary": result_summary,
            "created_at": str(row['created_at']) if row.get('created_at') else None
        })

    return HttpResponse.ok(
        data={
            "queries": queries_data,
            "total": total
        },
        msg="查询成功"
    )


@router.get("/statistics")
def get_statistics(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    GET /api/wealth/analyst/statistics - 统计数据

    功能：返回数据分析工作台的统计卡片数据

    返回格式：
    {
        "code": 0,
        "data": {
            "total_customers": 1500,
            "total_aum": "5000000000.00",
            "total_transactions_today": 120,
            "total_alerts_pending": 15
        },
        "msg": "查询成功"
    }
    """
    user = _get_current_user(credentials)

    try:
        db = CustomerProfileModel.get_db_connection()
        if not db:
            raise HTTPException(status_code=500, detail="数据库连接失败")

        # 统计客户总数 (base_user表没有role和status字段，使用user_type)
        customer_count_sql = "SELECT COUNT(*) as total FROM base_user WHERE user_type = 'CUSTOMER'"
        customer_result = db.execute(customer_count_sql, operation_type="query")
        total_customers = customer_result[0]['total'] if customer_result else 0

        # 统计总资产（AUM） - fin_customer_profile表没有total_assets字段，暂时返回0
        total_aum = "0"

        # 统计今日交易数
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        transaction_sql = """
            SELECT COUNT(*) as total
            FROM fin_transaction
            WHERE transaction_time >= %s
        """
        trans_result = db.execute(transaction_sql, (today_start,), operation_type="query")
        total_transactions_today = trans_result[0]['total'] if trans_result else 0

        alert_result = db.execute("SELECT COUNT(*) AS total, SUM(CASE WHEN status <> '待处理' THEN 1 ELSE 0 END) AS handled FROM fin_risk_alert", operation_type="query")
        total_alerts = int(alert_result[0]['total'] or 0) if alert_result else 0
        handled_alerts = int(alert_result[0]['handled'] or 0) if alert_result else 0
        total_alerts_pending = total_alerts - handled_alerts
        alert_processing_rate = round((handled_alerts / total_alerts) * 100, 1) if total_alerts else 0

        return HttpResponse.ok(
            data={
                "total_customers": total_customers,
                "total_aum": total_aum,
                "total_transactions_today": total_transactions_today,
                "total_alerts_pending": total_alerts_pending,
                "total_alerts": total_alerts,
                "handled_alerts": handled_alerts,
                "alert_processing_rate": alert_processing_rate,
                "system_status": "正常"
            },
            msg="查询成功"
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"查询统计数据失败: {str(e)}")


@router.get("/transactions/today")
def get_today_transactions(
    limit: int = Query(50, ge=1, le=100),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """返回业务管理员今日交易明细，用于统计卡片下钻。"""
    _get_current_user(credentials)
    db = TransactionModel.get_db_connection()
    if not db:
        raise HTTPException(status_code=500, detail="数据库连接失败")
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.execute(
        "SELECT t.id, t.transaction_type, t.amount, t.status, t.channel, "
        "t.transaction_time, t.customer_id, c.username AS customer_name, "
        "p.product_name, e.username AS employee_name "
        "FROM fin_transaction t "
        "LEFT JOIN base_user c ON c.id = t.customer_id "
        "LEFT JOIN base_user e ON e.id = t.employee_id "
        "LEFT JOIN fin_product p ON p.id = t.product_id "
        "WHERE t.transaction_time >= %s "
        "ORDER BY t.transaction_time DESC LIMIT %s",
        (today_start, limit),
        operation_type="query",
    )
    items = [{
        "交易编号": row.get("id"),
        "客户": row.get("customer_name") or f"客户{row.get('customer_id')}",
        "交易类型": row.get("transaction_type"),
        "产品": row.get("product_name") or "非产品交易",
        "金额": float(row.get("amount") or 0),
        "状态": row.get("status"),
        "渠道": row.get("channel") or "未记录",
        "办理员工": row.get("employee_name") or "系统",
        "交易时间": str(row.get("transaction_time") or ""),
    } for row in rows]
    return HttpResponse.ok(data={"items": items, "total": len(items)}, msg="今日交易明细查询成功")


@router.get("/customers/summary")
def get_customer_summary(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """返回与客户总数卡片一致的客户结构统计。"""
    _get_current_user(credentials)
    db = CustomerProfileModel.get_db_connection()
    if not db:
        raise HTTPException(status_code=500, detail="数据库连接失败")
    total_rows = db.execute("SELECT COUNT(*) AS total FROM base_user WHERE user_type = 'CUSTOMER'", operation_type="query")
    active_rows = db.execute("SELECT COUNT(DISTINCT customer_id) AS total FROM fin_transaction WHERE transaction_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)", operation_type="query")
    profile_rows = db.execute("SELECT COUNT(*) AS total FROM fin_customer_profile", operation_type="query")
    risk_rows = db.execute("SELECT COALESCE(risk_level, '未评级') AS risk_level, COUNT(*) AS total FROM fin_customer_profile GROUP BY risk_level ORDER BY risk_level", operation_type="query")
    total = int(total_rows[0].get("total") or 0) if total_rows else 0
    active = int(active_rows[0].get("total") or 0) if active_rows else 0
    profiled = int(profile_rows[0].get("total") or 0) if profile_rows else 0
    items = [
        {"指标": "客户总数", "数量": total, "口径": "所有 CUSTOMER 账户"},
        {"指标": "近30日有交易客户", "数量": active, "口径": "近30日存在交易流水的去重客户"},
        {"指标": "已建立客户画像", "数量": profiled, "口径": "存在客户画像记录"},
        {"指标": "客户画像覆盖率", "数量": f"{round(profiled / total * 100, 1) if total else 0}%", "口径": "画像客户数 / 客户总数"},
    ]
    items.extend({"指标": f"风险等级 {row.get('risk_level')}", "数量": int(row.get("total") or 0), "口径": "客户画像风险等级"} for row in risk_rows)
    return HttpResponse.ok(data={"items": items, "total": total}, msg="客户结构统计查询成功")


@router.get("/reports/{report_type}")
def get_admin_report(
    report_type: str,
    limit: int = Query(10, ge=1, le=50),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """业务管理员预置报表，提供稳定、可审计的常用分析结果。"""
    _get_current_user(credentials)
    db = TransactionModel.get_db_connection()
    if not db:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    if report_type == "monthly-new-customers":
        rows = db.execute(
            "SELECT DATE(created_at) AS report_date, COUNT(*) AS customer_count "
            "FROM base_user WHERE user_type = 'CUSTOMER' "
            "AND created_at >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01') "
            "GROUP BY DATE(created_at) ORDER BY report_date",
            operation_type="query",
        )
        items = [{"日期": str(row.get("report_date")), "新增客户数": int(row.get("customer_count") or 0)} for row in rows]
        return HttpResponse.ok(data={"items": items, "total": sum(item["新增客户数"] for item in items), "title": "本月新增客户"})

    if report_type == "top-products":
        rows = db.execute(
            "SELECT COALESCE(p.product_name, '非产品交易') AS product_name, "
            "COUNT(*) AS transaction_count, COALESCE(SUM(t.amount), 0) AS transaction_amount "
            "FROM fin_transaction t LEFT JOIN fin_product p ON p.id = t.product_id "
            "WHERE t.status = '成交' GROUP BY t.product_id, p.product_name "
            "ORDER BY transaction_amount DESC LIMIT %s",
            (limit,), operation_type="query",
        )
        items = [{"产品": row.get("product_name"), "成交笔数": int(row.get("transaction_count") or 0), "成交金额": float(row.get("transaction_amount") or 0)} for row in rows]
        return HttpResponse.ok(data={"items": items, "total": len(items), "title": "交易金额最高的产品"})

    if report_type == "risk-trend":
        rows = db.execute(
            "SELECT DATE(created_at) AS report_date, COUNT(*) AS alert_count, "
            "SUM(CASE WHEN status = '待处理' THEN 1 ELSE 0 END) AS pending_count "
            "FROM fin_risk_alert WHERE created_at >= DATE_SUB(CURRENT_DATE, INTERVAL 29 DAY) "
            "GROUP BY DATE(created_at) ORDER BY report_date",
            operation_type="query",
        )
        items = [{"日期": str(row.get("report_date")), "预警数量": int(row.get("alert_count") or 0), "待处理数量": int(row.get("pending_count") or 0)} for row in rows]
        return HttpResponse.ok(data={"items": items, "total": sum(item["预警数量"] for item in items), "title": "近30日风险预警趋势"})

    if report_type == "top-customers":
        rows = db.execute(
            "SELECT t.customer_id, COALESCE(c.username, CONCAT('客户', t.customer_id)) AS customer_name, "
            "COUNT(*) AS transaction_count, COALESCE(SUM(t.amount), 0) AS transaction_amount "
            "FROM fin_transaction t LEFT JOIN base_user c ON c.id = t.customer_id "
            "WHERE t.status = '成交' GROUP BY t.customer_id, c.username "
            "ORDER BY transaction_amount DESC LIMIT %s",
            (limit,), operation_type="query",
        )
        items = [{"客户": row.get("customer_name"), "成交笔数": int(row.get("transaction_count") or 0), "累计成交金额": float(row.get("transaction_amount") or 0)} for row in rows]
        return HttpResponse.ok(data={"items": items, "total": len(items), "title": "累计成交金额最高的客户"})

    raise HTTPException(status_code=404, detail="不支持的管理员报表类型")


@router.get("/history")
def get_history(
    limit: int = Query(10, ge=1, le=50),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    GET /api/wealth/analyst/history - 查询历史（简化版）

    返回最近的NL2SQL查询历史，用于前端页面快速访问
    """
    user = _get_current_user(credentials)

    try:
        db = ConversationArchiveModel.get_db_connection()
        if not db:
            raise HTTPException(status_code=500, detail="数据库连接失败")

        query_sql = f"""
            SELECT
                id,
                session_id,
                content,
                created_at
            FROM {ConversationArchiveModel.table_alias}
            WHERE customer_id = %s AND agent_type = 'analyst' AND role = 'user'
            ORDER BY created_at DESC
            LIMIT %s
        """
        results = db.execute(query_sql, (user.id, limit), operation_type="query")

        history_data = []
        for row in results:
            history_data.append({
                "id": row['id'],
                "query": row.get('content', ''),
                "response": '',  # 简化版不返回response
                "timestamp": str(row['created_at']) if row.get('created_at') else None
            })

        return HttpResponse.ok(
            data={"history": history_data},
            msg="查询成功"
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"查询历史记录失败: {str(e)}")


@router.get("/profile/{customer_id}")
def get_customer_profile(
    customer_id: int,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    GET /api/wealth/analyst/profile/{customer_id} - 客户画像

    功能：查询指定客户的详细画像信息

    返回格式：
    {
        "code": 0,
        "data": {
            "customer_id": 1001,
            "username": "customer_zhang",
            "risk_level": "C3",
            "total_assets": "1000000.00",
            "available_balance": "500000.00",
            "last_assessment_date": "2026-07-15",
            "created_at": "2025-01-10"
        },
        "msg": "查询成功"
    }
    """
    user = _get_current_user(credentials)

    try:
        db = CustomerProfileModel.get_db_connection()
        if not db:
            raise HTTPException(status_code=500, detail="数据库连接失败")

        # 联表查询客户基本信息和画像
        profile_sql = """
            SELECT
                u.id as customer_id,
                u.username,
                u.created_at as user_created_at,
                p.risk_level,
                p.risk_score,
                p.created_at as profile_created_at,
                p.updated_at
            FROM base_user u
            LEFT JOIN fin_customer_profile p ON u.id = p.customer_id
            WHERE u.id = %s AND u.user_type = 'CUSTOMER'
        """
        result = db.execute(profile_sql, (customer_id,), operation_type="query")

        if not result:
            raise HTTPException(status_code=404, detail="客户不存在")

        row = result[0]
        profile_data = {
            "customer_id": row['customer_id'],
            "username": row['username'],
            "risk_level": row.get('risk_level'),
            "risk_score": str(row.get('risk_score') or 0),
            "total_assets": "0",  # fin_customer_profile表中没有此字段
            "available_balance": "0",  # fin_customer_profile表中没有此字段
            "last_assessment_date": str(row['updated_at']) if row.get('updated_at') else None,
            "created_at": str(row['user_created_at']) if row.get('user_created_at') else None
        }

        return HttpResponse.ok(data=profile_data, msg="查询成功")
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"查询客户画像失败: {str(e)}")


@router.get("/risk-assessment/questionnaire")
def get_risk_questionnaire(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    GET /api/wealth/analyst/risk-assessment/questionnaire - 风险评估问卷

    功能：返回标准风险评估问卷题目

    返回格式：
    {
        "code": 0,
        "data": {
            "questions": [
                {
                    "id": 1,
                    "question": "您的年龄范围是？",
                    "options": [
                        {"value": "A", "label": "18-30岁", "score": 5},
                        {"value": "B", "label": "31-50岁", "score": 3},
                        {"value": "C", "label": "51岁以上", "score": 1}
                    ]
                }
            ]
        },
        "msg": "查询成功"
    }
    """
    user = _get_current_user(credentials)

    # 标准风险评估问卷（固定5题）
    questionnaire = {
        "questions": [
            {
                "id": 1,
                "question": "您的年龄范围是？",
                "options": [
                    {"value": "A", "label": "18-30岁", "score": 5},
                    {"value": "B", "label": "31-50岁", "score": 3},
                    {"value": "C", "label": "51岁以上", "score": 1}
                ]
            },
            {
                "id": 2,
                "question": "您的投资经验如何？",
                "options": [
                    {"value": "A", "label": "无投资经验", "score": 1},
                    {"value": "B", "label": "1-3年投资经验", "score": 3},
                    {"value": "C", "label": "3年以上投资经验", "score": 5}
                ]
            },
            {
                "id": 3,
                "question": "您能承受的最大投资损失是多少？",
                "options": [
                    {"value": "A", "label": "不能承受任何损失", "score": 1},
                    {"value": "B", "label": "可承受10%以内损失", "score": 3},
                    {"value": "C", "label": "可承受20%以上损失", "score": 5}
                ]
            },
            {
                "id": 4,
                "question": "您的投资目标是什么？",
                "options": [
                    {"value": "A", "label": "保本为主", "score": 1},
                    {"value": "B", "label": "稳健增值", "score": 3},
                    {"value": "C", "label": "追求高收益", "score": 5}
                ]
            },
            {
                "id": 5,
                "question": "您的家庭年收入范围是？",
                "options": [
                    {"value": "A", "label": "10万以下", "score": 1},
                    {"value": "B", "label": "10-50万", "score": 3},
                    {"value": "C", "label": "50万以上", "score": 5}
                ]
            }
        ]
    }

    return HttpResponse.ok(
        data=questionnaire,
        msg="查询成功"
    )


@router.post("/risk-assessment/submit")
def submit_risk_assessment(
    request: RiskAssessmentSubmit,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    POST /api/wealth/analyst/risk-assessment/submit - 提交风险评估

    功能：提交客户的风险评估问卷答案，计算风险等级

    请求体：
    {
        "customer_id": 1001,
        "answers": {
            "1": "A",
            "2": "B",
            "3": "A",
            "4": "B",
            "5": "C"
        }
    }

    返回格式：
    {
        "code": 0,
        "data": {
            "customer_id": 1001,
            "risk_level": "C2",
            "total_score": 12,
            "assessment_date": "2026-08-16"
        },
        "msg": "风险评估提交成功"
    }
    """
    user = _get_current_user(credentials)

    try:
        # 计算总分（简化逻辑：A=1分，B=3分，C=5分）
        score_map = {"A": 1, "B": 3, "C": 5}
        total_score = sum(score_map.get(answer, 0) for answer in request.answers.values())

        # 根据总分确定风险等级
        # C1(保守型): 5-10分, C2(稳健型): 11-17分, C3(平衡型): 18-20分,
        # C4(进取型): 21-23分, C5(激进型): 24-25分
        if total_score <= 10:
            risk_level = "C1"
        elif total_score <= 17:
            risk_level = "C2"
        elif total_score <= 20:
            risk_level = "C3"
        elif total_score <= 23:
            risk_level = "C4"
        else:
            risk_level = "C5"

        # 写入数据库
        db = RiskAssessmentModel.get_db_connection()
        if not db:
            raise HTTPException(status_code=500, detail="数据库连接失败")

        assessment_date = datetime.now()

        # 插入风险评估记录
        insert_sql = f"""
            INSERT INTO {RiskAssessmentModel.table_alias}
            (customer_id, risk_level, assessment_score, assessment_date, expires_at, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        expires_at = assessment_date + timedelta(days=365)  # 有效期1年

        db.execute(insert_sql, (
            request.customer_id,
            risk_level,
            total_score,
            assessment_date,
            expires_at,
            'valid',
            assessment_date
        ), operation_type="insert")

        # 更新客户画像表的风险等级
        update_profile_sql = """
            UPDATE fin_customer_profile
            SET risk_level = %s, last_assessment_date = %s
            WHERE customer_id = %s
        """
        db.execute(update_profile_sql, (risk_level, assessment_date, request.customer_id), operation_type="update")

        return HttpResponse.ok(
            data={
                "customer_id": request.customer_id,
                "risk_level": risk_level,
                "total_score": total_score,
                "assessment_date": str(assessment_date.date())
            },
            msg="风险评估提交成功"
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"提交风险评估失败: {str(e)}")


def register_analyst_api(app):
    """注册数据分析师API路由"""
    app.include_router(router)
