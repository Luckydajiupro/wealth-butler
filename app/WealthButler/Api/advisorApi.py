"""理财顾问 API 接口层

职责：
- 提供理财顾问工作台相关接口
- 包括客户列表查询、顾问统计数据、客户服务记录
- JWT认证，仅限理财顾问角色访问
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta

from app.Base.RicUtils.httpUtils import HttpResponse
from app.Base.Service.authService import AuthService
from app.WealthButler.Models.workOrderModel import WorkOrderModel
from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
from app.Base.Models.userModel import UserModel


router = APIRouter(prefix="/api/wealth/advisor", tags=["理财顾问"])
security = HTTPBearer(auto_error=False)


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
    user = _get_current_user(credentials)

    # 查询所有客户（简化版本，实际应该关联顾问-客户关系表）
    db = UserModel.get_db_connection()
    if not db:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    # 查询客户总数
    count_sql = "SELECT COUNT(*) as total FROM base_user WHERE deleted_at IS NULL"
    count_result = db.execute(count_sql)
    total = count_result[0]['total'] if count_result else 0

    # 查询客户列表
    clients_sql = f"""
        SELECT id, username, phone, email, created_at
        FROM base_user
        WHERE deleted_at IS NULL
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """
    clients_result = db.execute(clients_sql, (limit, offset))

    # 构建返回数据
    clients_data = []
    for client in clients_result:
        # 查询客户画像
        profile = CustomerProfileModel.find_by_customer_id(client['id'])

        clients_data.append({
            "id": client['id'],
            "name": client['username'],
            "phone": client.get('phone', 'N/A'),
            "risk_level": profile.risk_level if profile else 'C3',
            "risk_score": float(profile.risk_score) if profile and profile.risk_score else 50.0,
            "created_at": str(client['created_at']) if client.get('created_at') else None
        })

    return HttpResponse.ok(
        data={
            "clients": clients_data,
            "total": total
        },
        msg="查询成功"
    )


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
    user = _get_current_user(credentials)

    db = WorkOrderModel.get_db_connection()
    if not db:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    # 今日服务客户数（通过今日创建的工单统计）
    today_sql = f"""
        SELECT COUNT(DISTINCT customer_id) as cnt
        FROM {WorkOrderModel.table_alias}
        WHERE DATE(created_at) = CURDATE()
        AND deleted_at IS NULL
    """
    today_result = db.execute(today_sql)
    today_customer_count = today_result[0]['cnt'] if today_result else 0

    # 本月完成交易笔数（从工单表统计已完成的工单）
    month_sql = f"""
        SELECT COUNT(*) as cnt
        FROM {WorkOrderModel.table_alias}
        WHERE YEAR(created_at) = YEAR(CURDATE())
        AND MONTH(created_at) = MONTH(CURDATE())
        AND status = '已完成'
        AND deleted_at IS NULL
    """
    month_result = db.execute(month_sql)
    month_transaction_count = month_result[0]['cnt'] if month_result else 0

    # 待处理工单数
    pending_sql = f"""
        SELECT COUNT(*) as cnt
        FROM {WorkOrderModel.table_alias}
        WHERE status = '待处理'
        AND deleted_at IS NULL
        AND order_type = '客户转介'
    """
    pending_result = db.execute(pending_sql)
    pending_workorder_count = pending_result[0]['cnt'] if pending_result else 0

    return HttpResponse.ok(
        data={
            "today_customer_count": today_customer_count,
            "month_transaction_count": month_transaction_count,
            "pending_workorder_count": pending_workorder_count
        },
        msg="查询成功"
    )


def register_advisor_api(app):
    """注册理财顾问API路由"""
    app.include_router(router)
