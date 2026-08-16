"""工单管理 API 接口层

职责：
- 提供工单的创建、查询、领取、处理功能
- JWT认证，根据用户角色自动筛选工单
- 支持工单状态机流转（待处理→处理中→已完成/已驳回）

接口列表：
- GET /api/wealth/workorder/list - 查询工单列表（支持筛选）
- POST /api/wealth/workorder - 创建工单
- PUT /api/wealth/workorder/{id} - 更新工单状态
- GET /api/wealth/workorder/{id} - 查询单个工单详情

角色权限：
- 理财顾问：筛选包含"申购/赎回/产品推荐"的客户转介工单
- 客户经理：筛选包含"转账/信息更新/工单"的客户转介工单
- 风控专员：筛选风险预警类工单
- 管理员：查看所有工单

依赖：
- AuthService: JWT认证和角色权限管理
- WorkOrderModel: 工单数据操作
- UserModel: 用户信息查询
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.Base.RicUtils.httpUtils import HttpResponse
from app.Base.Service.authService import AuthService
from app.WealthButler.Models.workOrderModel import WorkOrderModel
from app.Base.Models.userModel import UserModel


router = APIRouter(prefix="/api/wealth/workorder", tags=["工单管理"])
security = HTTPBearer(auto_error=False)


# ==================== 请求模型 ====================

class CreateWorkOrderRequest(BaseModel):
    """创建工单请求"""
    order_type: str = Field(..., description="工单类型：客户转介/风险预警/信息变更/转账审核/其他")
    customer_id: int = Field(..., description="客户ID")
    intent_summary: str = Field(..., description="意向摘要/业务描述")
    priority: str = Field("普通", description="优先级：普通/紧急")


class UpdateWorkOrderRequest(BaseModel):
    """更新工单状态请求"""
    action: str = Field(..., description="操作：claim（领取）/complete（完成）/reject（驳回）")
    remark: Optional[str] = Field(None, description="处理备注")


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


def _get_user_role_type(user_id: int) -> Optional[str]:
    """
    根据用户权限判断角色类型
    返回：advisor（理财顾问）/ manager（客户经理）/ risk（风控专员）/ admin（管理员）/ None
    """
    role_info = AuthService.get_user_role_info(user_id)
    permissions = role_info.get("permissions", [])

    # 管理员可以查看所有工单
    if role_info.get("is_admin"):
        return "admin"

    # 根据权限判断角色
    if "product:recommend" in permissions:
        return "advisor"  # 理财顾问
    elif "customer:manage" in permissions:
        return "manager"  # 客户经理
    elif "risk:monitor" in permissions:
        return "risk"  # 风控专员

    return None


def _filter_workorders_by_role(workorders: list, role_type: str) -> list:
    """
    根据角色筛选工单
    - 理财顾问：筛选包含"申购/赎回/产品推荐"的客户转介工单
    - 客户经理：筛选包含"转账/信息更新/工单"的客户转介工单
    - 风控专员：筛选风险预警类工单
    - 管理员：返回所有工单
    """
    if role_type == "admin":
        return workorders

    filtered = []
    for order in workorders:
        # 风控专员只看风险预警
        if role_type == "risk":
            if order.order_type == "风险预警":
                filtered.append(order)

        # 理财顾问看包含特定关键词的客户转介
        elif role_type == "advisor":
            if order.order_type == "客户转介" and order.intent_summary:
                keywords = ["申购", "赎回", "产品推荐", "产品咨询", "理财"]
                if any(kw in order.intent_summary for kw in keywords):
                    filtered.append(order)

        # 客户经理看包含特定关键词的客户转介
        elif role_type == "manager":
            if order.order_type == "客户转介" and order.intent_summary:
                keywords = ["转账", "信息更新", "工单", "账户", "资料"]
                if any(kw in order.intent_summary for kw in keywords):
                    filtered.append(order)

    return filtered


# ==================== API接口 ====================

@router.get("/list")
def get_workorder_list(
    order_type: Optional[str] = Query(None, description="工单类型"),
    status: Optional[str] = Query(None, description="状态"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    GET /api/wealth/workorder/list - 查询工单列表（支持筛选）

    功能：
    - JWT认证
    - 根据用户角色自动筛选工单：
      * 理财顾问：筛选包含"申购/赎回/产品推荐"的客户转介工单
      * 客户经理：筛选包含"转账/信息更新/工单"的客户转介工单
      * 风控专员：筛选风险预警类工单
      * 管理员：查看所有工单
    - 支持按类型、状态、关键词筛选

    返回格式：
    {
        "code": 0,
        "data": {
            "workorders": [...],
            "total": 10
        },
        "msg": "查询成功"
    }
    """
    # 认证并获取用户信息
    user = _get_current_user(credentials)
    role_type = _get_user_role_type(user.id)

    if not role_type:
        raise HTTPException(status_code=403, detail="您没有查看工单的权限")

    # 查询工单
    workorders, total = WorkOrderModel.find_by_filters(
        order_type=order_type,
        status=status,
        keyword=keyword,
        limit=limit,
        offset=offset
    )

    # 根据角色筛选工单
    filtered_workorders = _filter_workorders_by_role(workorders, role_type)

    # 构建返回数据
    result_data = []
    for order in filtered_workorders:
        result_data.append({
            "id": order.id,
            "order_type": order.order_type,
            "customer_id": order.customer_id,
            "customer_name": order.customer_name,
            "intent_summary": order.intent_summary,
            "status": order.status,
            "priority": order.priority,
            "handled_by": order.handled_by,
            "handler_name": order.handler_name,
            "handled_at": str(order.handled_at) if order.handled_at else None,
            "completed_at": str(order.completed_at) if order.completed_at else None,
            "remark": order.remark,
            "created_at": str(order.created_at) if order.created_at else None,
            "updated_at": str(order.updated_at) if order.updated_at else None
        })

    return HttpResponse.ok(
        data={
            "workorders": result_data,
            "total": len(filtered_workorders)
        },
        msg="查询成功"
    )


@router.post("")
def create_workorder(
    request: CreateWorkOrderRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    POST /api/wealth/workorder - 创建工单

    功能：
    - JWT认证
    - 自动填充customer_name（从base_user表查询）
    - 创建新工单

    请求体：
    {
        "order_type": "客户转介",
        "customer_id": 123,
        "intent_summary": "申购XX产品，意向金额约10万",
        "priority": "普通"
    }
    """
    # 认证
    user = _get_current_user(credentials)

    # 验证工单类型
    valid_types = ["客户转介", "风险预警", "信息变更", "转账审核", "其他"]
    if request.order_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"工单类型不合法，必须是以下之一：{', '.join(valid_types)}"
        )

    # 验证优先级
    valid_priorities = ["普通", "紧急"]
    if request.priority not in valid_priorities:
        raise HTTPException(
            status_code=400,
            detail=f"优先级不合法，必须是以下之一：{', '.join(valid_priorities)}"
        )

    # 查询客户信息
    customer = UserModel.get_by_id(request.customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")

    # 创建工单
    workorder = WorkOrderModel(
        order_type=request.order_type,
        customer_id=request.customer_id,
        customer_name=customer.username,  # 冗余字段
        intent_summary=request.intent_summary,
        priority=request.priority,
        status="待处理"
    )

    workorder_id = workorder.save()

    if workorder_id <= 0:
        raise HTTPException(status_code=500, detail="工单创建失败")

    return HttpResponse.ok(
        data={"id": workorder_id},
        msg="工单创建成功"
    )


@router.put("/{workorder_id}")
def update_workorder(
    workorder_id: int,
    request: UpdateWorkOrderRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    PUT /api/wealth/workorder/{id} - 更新工单状态

    功能：
    - JWT认证
    - 支持三种操作：
      * claim: 领取工单（状态：待处理→处理中，记录handled_by）
      * complete: 完成工单（状态：处理中→已完成，记录completed_at）
      * reject: 驳回工单（状态：处理中→已驳回）
    - 状态机校验：不能跳跃状态

    请求体：
    {
        "action": "claim",
        "remark": "处理备注"
    }
    """
    # 认证
    user = _get_current_user(credentials)

    # 查询工单
    workorder = WorkOrderModel.get_by_id(workorder_id)
    if not workorder or workorder.deleted_at:
        raise HTTPException(status_code=404, detail="工单不存在")

    # 根据action执行不同操作
    if request.action == "claim":
        # 领取工单：待处理 → 处理中
        if workorder.status != "待处理":
            raise HTTPException(
                status_code=400,
                detail=f"只有'待处理'状态的工单才能领取，当前状态：{workorder.status}"
            )

        # 检查是否已被他人领取
        if workorder.handled_by and workorder.handled_by != user.id:
            raise HTTPException(
                status_code=400,
                detail=f"工单已被 {workorder.handler_name} 领取"
            )

        # 更新工单
        workorder.status = "处理中"
        workorder.handled_by = user.id
        workorder.handler_name = user.username
        workorder.handled_at = datetime.now()
        if request.remark:
            workorder.remark = request.remark

        workorder.save()
        return HttpResponse.ok(msg="工单领取成功")

    elif request.action == "complete":
        # 完成工单：处理中 → 已完成
        if workorder.status != "处理中":
            raise HTTPException(
                status_code=400,
                detail=f"只有'处理中'状态的工单才能完成，当前状态：{workorder.status}"
            )

        # 检查是否是本人领取的工单
        if workorder.handled_by != user.id:
            raise HTTPException(
                status_code=403,
                detail="只能完成自己领取的工单"
            )

        # 更新工单
        workorder.status = "已完成"
        workorder.completed_at = datetime.now()
        if request.remark:
            workorder.remark = request.remark

        workorder.save()
        return HttpResponse.ok(msg="工单已完成")

    elif request.action == "reject":
        # 驳回工单：处理中 → 已驳回
        if workorder.status != "处理中":
            raise HTTPException(
                status_code=400,
                detail=f"只有'处理中'状态的工单才能驳回，当前状态：{workorder.status}"
            )

        # 检查是否是本人领取的工单
        if workorder.handled_by != user.id:
            raise HTTPException(
                status_code=403,
                detail="只能驳回自己领取的工单"
            )

        # 更新工单
        workorder.status = "已驳回"
        if request.remark:
            workorder.remark = request.remark

        workorder.save()
        return HttpResponse.ok(msg="工单已驳回")

    else:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的操作：{request.action}，支持的操作：claim/complete/reject"
        )


@router.get("/{workorder_id}")
def get_workorder_detail(
    workorder_id: int,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    GET /api/wealth/workorder/{id} - 查询单个工单详情

    功能：
    - JWT认证
    - 返回工单完整信息
    """
    # 认证
    user = _get_current_user(credentials)

    # 查询工单
    workorder = WorkOrderModel.get_by_id(workorder_id)
    if not workorder or workorder.deleted_at:
        raise HTTPException(status_code=404, detail="工单不存在")

    # 构建返回数据
    result = {
        "id": workorder.id,
        "order_type": workorder.order_type,
        "customer_id": workorder.customer_id,
        "customer_name": workorder.customer_name,
        "intent_summary": workorder.intent_summary,
        "status": workorder.status,
        "priority": workorder.priority,
        "handled_by": workorder.handled_by,
        "handler_name": workorder.handler_name,
        "handled_at": str(workorder.handled_at) if workorder.handled_at else None,
        "completed_at": str(workorder.completed_at) if workorder.completed_at else None,
        "remark": workorder.remark,
        "created_at": str(workorder.created_at) if workorder.created_at else None,
        "updated_at": str(workorder.updated_at) if workorder.updated_at else None
    }

    return HttpResponse.ok(data=result, msg="查询成功")


# ==================== 路由注册函数 ====================

def register_workorder_api(app):
    """注册工单API路由到 FastAPI app"""
    app.include_router(router)
