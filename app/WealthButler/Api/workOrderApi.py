"""工单管理 API 接口层

职责：
- 提供工单的创建、查询、领取、处理功能
- JWT认证，根据用户角色自动筛选工单
- 支持工单状态机流转（待处理→处理中→已完成/已驳回/已关闭）

接口列表：
- GET /api/wealth/workorder/list - 查询工单列表（支持筛选）
- POST /api/wealth/workorder - 创建工单
- PUT /api/wealth/workorder/{id} - 更新工单状态
- GET /api/wealth/workorder/{id} - 查询单个工单详情

角色权限：
- 理财顾问：只处理产品配置、组合诊断和适当性复核
- 客户经理/运营：处理申购、赎回、转账和账户资料业务
- 风控专员：筛选风险预警类工单
- 管理员：查看所有工单

依赖：
- AuthService: JWT认证和角色权限管理
- WorkOrderModel: 工单数据操作
- UserModel: 用户信息查询
"""
from typing import Optional, List, Dict, Any
import logging
from uuid import uuid4
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.Base.RicUtils.httpUtils import HttpResponse
from app.Base.Service.authService import AuthService
from app.WealthButler.Models.workOrderModel import WorkOrderModel
from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel
from app.Base.Models.userModel import UserModel


router = APIRouter(prefix="/api/wealth/workorder", tags=["工单管理"])
security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


RISK_ORDER_TYPES = {"风险预警", "风控预警", "风控处置"}
REFERRAL_SUBTYPES = {"申购", "追加申购", "赎回", "转账", "资料变更", "产品配置", "风险预警"}
ADVISOR_SUBTYPES = {"产品配置"}
OPERATOR_SUBTYPES = {"申购", "追加申购", "赎回", "转账", "资料变更"}


def _is_risk_workorder(order) -> bool:
    """Accept legacy stored values while exposing one role boundary."""
    return str(getattr(order, "order_type", "") or "") in RISK_ORDER_TYPES


def _business_subtype(order) -> Optional[str]:
    value = getattr(order, "business_subtype", None)
    if value:
        return str(value)
    records = getattr(order, "handle_records", None)
    if isinstance(records, dict) and records.get("business_subtype"):
        return str(records["business_subtype"])
    if (
        getattr(order, "related_entity_type", None) == "transaction"
        and getattr(order, "related_entity_id", None)
    ):
        from app.WealthButler.Models.transactionModel import TransactionModel

        transaction = TransactionModel.get_by_id(int(order.related_entity_id))
        transaction_type = getattr(transaction, "transaction_type", None) if transaction else None
        if transaction_type in {"申购", "追加申购", "赎回", "转账"}:
            return str(transaction_type)
    return None


# ==================== 请求模型 ====================

class CreateWorkOrderRequest(BaseModel):
    """创建工单请求"""
    order_type: str = Field(..., description="工单类型：客户转介/风险预警/信息变更/转账审核/其他")
    customer_id: int = Field(..., description="客户ID")
    intent_summary: str = Field(..., description="意向摘要/业务描述")
    business_subtype: Optional[str] = Field(None, description="结构化业务子类型")
    priority: str = Field("普通", description="优先级：普通/紧急")


class UpdateWorkOrderRequest(BaseModel):
    """更新工单状态请求"""
    action: str = Field(..., description="操作：claim（领取）/complete（完成）/reject（驳回）/close（关闭）")
    remark: Optional[str] = Field(None, max_length=200, description="处理备注；关闭工单时必填原因")
    related_entity_type: Optional[str] = Field(None, description="完成工单时关联实体类型")
    related_entity_id: Optional[int] = Field(None, gt=0, description="完成工单时关联实体ID")


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


def _get_user_role_type(user) -> Optional[str]:
    """
    根据用户权限判断角色类型
    返回：advisor（理财顾问）/ manager（客户经理）/ risk（风控专员）/ admin（管理员）/ None
    """
    role_info = AuthService.get_user_role_info(
        user.id,
        getattr(user, "source_module", None),
    )
    permissions = role_info.get("permissions", [])
    business_user = BaseUserExtModel.get_by_id(user.id)
    employee_role = getattr(business_user, "employee_role", None)

    # 管理员可以查看所有工单。兼容历史员工账号尚未同步管理员权限的情况，
    # 以员工角色作为后端边界的第二可信来源，不能只依赖前端工作台入口。
    if role_info.get("is_admin") or employee_role == "业务管理员":
        return "admin"

    # 根据权限判断角色
    if "product:recommend" in permissions:
        return "advisor"  # 理财顾问
    elif "customer:manage" in permissions:
        return "manager"  # 客户经理
    elif "risk:monitor" in permissions:
        return "risk"  # 风控专员

    # 兼容历史角色权限数据尚未补齐的员工账号；接口仍要求有效员工身份。
    if employee_role == "理财顾问":
        return "advisor"
    if employee_role == "客户经理":
        return "manager"
    if employee_role == "风控专员":
        return "risk"

    return None


def _filter_workorders_by_role(workorders: list, role_type: str) -> list:
    """
    根据角色筛选工单
    - 理财顾问：产品配置、组合诊断和适当性复核
    - 客户经理/运营：申购、赎回、转账和账户资料业务
    - 风控专员：筛选风险预警类工单
    - 管理员：返回所有工单
    """
    if role_type == "admin":
        return workorders

    filtered = []
    for order in workorders:
        # 风控专员只看风险预警
        if role_type == "risk":
            if _is_risk_workorder(order):
                filtered.append(order)

        # 理财顾问只看投顾分析和配置类客户转介。
        elif role_type == "advisor":
            if order.order_type == "客户转介" and _business_subtype(order) in ADVISOR_SUBTYPES:
                filtered.append(order)

        # 客户经理/运营承接需要实际办理的业务事项。
        elif role_type == "manager":
            if order.order_type == "客户转介" and _business_subtype(order) in OPERATOR_SUBTYPES:
                filtered.append(order)

    return filtered


def _workorder_summary(order) -> str:
    """Read both the current field and legacy customer-service work orders."""
    return str(
        getattr(order, "intent_summary", None)
        or getattr(order, "description", None)
        or getattr(order, "title", None)
        or ""
    )


def _is_advisor_action_request(summary: str) -> bool:
    """Only advisory analysis/configuration belongs in the advisor pool."""
    text = str(summary or "").strip()
    if not text:
        return False
    knowledge_question = any(token in text for token in (
        "风险等级", "是什么", "什么意思", "怎么理解", "费率", "净值",
        "起投", "期限", "说明书", "介绍一下", "如何理解",
    ))
    advisory_request = any(token in text for token in (
        "产品推荐", "推荐产品", "帮我配置", "配置产品", "配置方案", "产品配置",
        "组合诊断", "持仓诊断", "适当性复核", "适当性核验", "投资建议",
    ))
    operation_request = any(token in text for token in ("申购", "赎回", "转账", "买入", "卖出"))
    return advisory_request and not operation_request and not knowledge_question


def _is_operator_action_request(summary: str) -> bool:
    """Transaction and account operations belong to customer manager/operations."""
    text = str(summary or "").strip()
    if not text:
        return False
    knowledge_question = any(token in text for token in (
        "是什么", "什么意思", "怎么理解", "费率", "净值", "规则", "介绍一下",
    ))
    operation_request = any(token in text for token in (
        "申购", "赎回", "转账", "买入", "卖出", "信息更新", "修改资料", "账户变更", "资料变更",
    ))
    return operation_request and not knowledge_question


def _role_can_handle_workorder(order, role_type: Optional[str]) -> bool:
    if role_type == "admin":
        return True
    if role_type == "risk":
        return _is_risk_workorder(order)
    # Risk work orders are never claimable or processable by operators,
    # regardless of legacy order_type spelling.
    if _is_risk_workorder(order):
        return False
    if order.order_type != "客户转介":
        return False
    subtype = _business_subtype(order)
    if role_type == "advisor":
        return subtype in ADVISOR_SUBTYPES
    if role_type == "manager":
        return subtype in OPERATOR_SUBTYPES
    return False


def _publish_customer_result(workorder, handler_id: int, status: str, remark: Optional[str]) -> None:
    """Publish the human handling result without rolling back the completed work order."""
    if not workorder.customer_id:
        return
    summary = _workorder_summary(workorder)
    if status == "已完成":
        reply = remark or f"您的服务事项“{summary}”已处理完成。"
    elif status == "已关闭":
        reply = f"您的{_business_subtype(workorder) or '业务'}申请未满足办理条件，工单已关闭。关闭原因：{str(remark or '未满足办理条件').strip()}"
    else:
        reply = remark or f"您的服务事项“{summary}”暂未通过处理，请联系在线客服补充信息。"
    event_id = str(uuid4())
    trace_id = f"workorder-result-{event_id}"
    try:
        from app.WealthButler.EventBus.eventBus import EventBus

        handler_name = getattr(workorder, "handler_name", None)
        if not handler_name:
            handler = BaseUserExtModel.get_by_id(handler_id)
            handler_name = getattr(handler, "username", None) if handler else None

        payload = {
            "event_id": event_id,
            "order_id": workorder.id,
            "customer_id": workorder.customer_id,
            "business_subtype": _business_subtype(workorder),
            "session_id": getattr(workorder, "session_id", None),
            "status": status,
            "reply": reply,
            "handler_id": handler_id,
            "handler_name": handler_name,
        }
        try:
            from app.WealthButler.Service.customerNotificationService import store_work_order_result_notification

            store_work_order_result_notification(payload, trace_id)
        except Exception:
            logger.exception("客户工单结果即时通知失败，保留 Stream 补偿: order_id=%s", workorder.id)

        EventBus.publish(
            stream_key="stream:work_order_result",
            event_type="work_order_result",
            payload=payload,
            source_agent="advisor_workbench",
            trace_id=trace_id,
        )
    except Exception:
        logger.exception("工单结果回传事件发布失败: order_id=%s", workorder.id)


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
      * 理财顾问：产品配置、组合诊断和适当性复核
      * 客户经理/运营：申购、赎回、转账和账户资料业务
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
    role_type = _get_user_role_type(user)

    if not role_type:
        raise HTTPException(status_code=403, detail="您没有查看工单的权限")

    intent_keywords = None
    effective_order_type = order_type
    if role_type == "advisor":
        effective_order_type = "客户转介"
        intent_keywords = None
    elif role_type == "manager":
        effective_order_type = "客户转介"
        intent_keywords = None
    elif role_type == "risk":
        effective_order_type = "风险预警"

    # 在数据库分页前应用角色范围，避免第一页被其他类型工单占满。
    if role_type == "risk":
        # 兼容历史库中的三个风险工单字面值，业务边界仍统一为风控专员。
        workorders = []
        total = 0
        for risk_type in RISK_ORDER_TYPES:
            rows, row_total = WorkOrderModel.find_by_filters(
                order_type=risk_type,
                status=status,
                keyword=keyword,
                limit=limit,
                offset=offset,
            )
            workorders.extend(rows)
            total += row_total
    else:
        workorders, total = WorkOrderModel.find_by_filters(
            order_type=effective_order_type,
            status=status,
            keyword=keyword,
            intent_keywords=intent_keywords,
            limit=limit,
            offset=offset
        )

    # 根据角色筛选工单
    filtered_workorders = _filter_workorders_by_role(workorders, role_type)
    if role_type in {"advisor", "manager"}:
        total = len(filtered_workorders)

    # 构建返回数据
    result_data = []
    for order in filtered_workorders:
        customer_name = order.customer_name
        if not customer_name and order.customer_id:
            customer = UserModel.get_by_id(order.customer_id)
            customer_name = getattr(customer, "username", None) if customer else None
        handler_ids = {order.handled_by, getattr(order, "handler_id", None)}
        assignment_scope = (
            "owned" if user.id in handler_ids
            else "unclaimed" if not any(handler_ids) and order.status in {"待处理", "未处理"}
            else "other"
        )
        result_data.append({
            "id": order.id,
            "order_type": order.order_type,
            "business_subtype": _business_subtype(order),
            "customer_id": order.customer_id,
            "customer_name": customer_name,
            "intent_summary": _workorder_summary(order),
            "status": order.status,
            "priority": order.priority,
            "handled_by": order.handled_by,
            "handler_id": getattr(order, "handler_id", None),
            "handler_name": order.handler_name,
            "assignment_scope": assignment_scope,
            "handled_at": str(order.handled_at) if order.handled_at else None,
            "completed_at": str(order.completed_at) if order.completed_at else None,
            "remark": order.remark,
            "created_at": str(order.created_at) if order.created_at else None,
            "updated_at": str(order.updated_at) if order.updated_at else None
        })

    return HttpResponse.ok(
        data={
            "workorders": result_data,
            "total": total
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
    role_type = _get_user_role_type(user)
    if not role_type:
        raise HTTPException(status_code=403, detail="您没有创建工单的权限")

    # 验证工单类型
    valid_types = ["客户转介", "风险预警", "信息变更", "转账审核", "其他"]
    if request.order_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"工单类型不合法，必须是以下之一：{', '.join(valid_types)}"
        )
    if request.order_type == "客户转介" and request.business_subtype not in REFERRAL_SUBTYPES:
        raise HTTPException(status_code=400, detail="客户转介必须提供有效的 business_subtype，不能只使用摘要文本")

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

    # 客户经理创建业务工单也必须遵守对象级客户范围；管理员保留全量权限。
    if role_type == "manager":
        from app.WealthButler.Service.operatorAccessService import OperatorAccessService
        if not OperatorAccessService.can_access_customer(user.id, request.customer_id):
            raise HTTPException(status_code=403, detail="该客户不在当前客户经理的办理范围内，请先领取对应工单")

    # 创建工单
    workorder = WorkOrderModel(
        order_type=request.order_type,
        customer_id=request.customer_id,
        customer_name=customer.username,  # 冗余字段
        intent_summary=request.intent_summary,
        handle_records={"business_subtype": request.business_subtype, "created_by": user.id},
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
    - 支持四种操作：
      * claim: 领取工单（状态：待处理→处理中，记录handled_by）
      * complete: 完成工单（状态：处理中→已完成，记录completed_at）
      * reject: 驳回工单（状态：处理中→已驳回）
      * close: 因不满足条件关闭申购/赎回工单，并向客户回传原因
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
        role_type = _get_user_role_type(user)
        if not _role_can_handle_workorder(workorder, role_type):
            raise HTTPException(status_code=403, detail="该工单不属于当前岗位的业务范围")

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
        if request.related_entity_type and request.related_entity_id:
            workorder.related_entity_type = request.related_entity_type
            workorder.related_entity_id = request.related_entity_id
        if request.remark:
            workorder.remark = request.remark

        workorder.save()
        _publish_customer_result(workorder, user.id, "已完成", request.remark)
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
        _publish_customer_result(workorder, user.id, "已驳回", request.remark)
        return HttpResponse.ok(msg="工单已驳回")

    elif request.action == "close":
        if _get_user_role_type(user) != "manager":
            raise HTTPException(status_code=403, detail="只有客户经理可以关闭交易办理工单")
        if _business_subtype(workorder) not in {"申购", "追加申购", "赎回"}:
            raise HTTPException(status_code=400, detail="只有申购、追加申购或赎回工单可以按不符合条件关闭")
        if workorder.status not in {"处理中", "待审核"}:
            raise HTTPException(
                status_code=400,
                detail=f"只有'处理中'或'待审核'状态的工单才能关闭，当前状态：{workorder.status}",
            )
        if workorder.handled_by != user.id:
            raise HTTPException(status_code=403, detail="只能关闭自己领取的工单")
        reason = str(request.remark or "").strip()
        if not reason:
            raise HTTPException(status_code=400, detail="关闭工单必须填写原因")

        workorder.status = "已关闭"
        workorder.closed_at = datetime.now()
        workorder.remark = reason
        records = workorder.handle_records if isinstance(workorder.handle_records, dict) else {}
        workorder.handle_records = {
            **records,
            "close_record": {
                "handler_id": user.id,
                "handler_name": user.username,
                "reason": reason,
                "closed_at": workorder.closed_at.isoformat(),
            },
        }
        workorder.save()
        _publish_customer_result(workorder, user.id, "已关闭", reason)
        return HttpResponse.ok(msg="工单已关闭，关闭原因已反馈给客户")

    else:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的操作：{request.action}，支持的操作：claim/complete/reject/close"
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
    role_type = _get_user_role_type(user)
    if workorder.handled_by != user.id and not _role_can_handle_workorder(workorder, role_type):
        raise HTTPException(status_code=403, detail="该工单不属于当前岗位的业务范围")

    # 构建返回数据
    result = {
        "id": workorder.id,
        "order_type": workorder.order_type,
        "business_subtype": _business_subtype(workorder),
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
