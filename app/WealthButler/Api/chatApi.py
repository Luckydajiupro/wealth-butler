"""对话 API 接口层

职责：
- 提供统一入口 POST /api/chat 按 agent_type 分发
- 提供 4 个可对话 Agent 直连路由
- 提供业务操作二次确认接口
- 提供会话历史查询接口
- SSE 流式返回
- 统一响应格式包装

参考：app/Base/Api/ai/chatApi.py 的流式实现模式
"""
import json
import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.Base.Api.authApi import _get_current_user, security
from app.Base.Models.roleModel import Permission
from app.Base.RicUtils.httpUtils import HttpResponse
from app.Base.Service.authService import AuthService
from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel
from app.WealthButler.Service.chatService import ChatService
from app.WealthButler.Service.customerService import CustomerService
from app.WealthButler.Service.operatorAccessService import OperatorAccessService

logger = logging.getLogger(__name__)


# ==================== 请求模型 ====================

class ChatRequest(BaseModel):
    """统一对话请求模型"""
    message: str = Field(..., description="用户消息")
    agent_type: Optional[str] = Field(None, description="Agent类型: customer|advisor|analyst|operator（可选）")
    conversation_id: Optional[str] = Field(None, description="会话ID，不传则自动创建")
    session_id: Optional[str] = Field(None, description="会话ID（兼容旧字段）")
    customer_id: Optional[int] = Field(None, description="客户ID（投顾/业务操作必填）")
    is_stream: bool = Field(True, description="是否流式输出，默认True")


class DirectChatRequest(BaseModel):
    """直连路由请求模型（无需 agent_type）"""
    message: str = Field(..., description="用户消息")
    session_id: Optional[str] = Field(None, description="会话ID，不传则自动创建")
    customer_id: Optional[int] = Field(None, description="客户ID（投顾/业务操作必填）")
    is_stream: bool = Field(True, description="是否流式输出，默认True")


class OperatorConfirmRequest(BaseModel):
    """客户经理撤回待确认业务的请求模型。"""
    confirm_token: str = Field(..., description="待确认操作的token")
    action: str = Field(..., description="仅支持 cancel（撤回申请）")


# ==================== 路由定义 ====================

# 注意：prefix 不要重复，register 函数会添加前缀
router = APIRouter(tags=["对话接口"])
compat_router = APIRouter(tags=["对话接口"])


# ==================== 认证与 Agent 授权 ====================

_OPERATOR_ENTRY_PERMISSIONS = (
    Permission.PRODUCT_QUERY,
    Permission.OPERATION_PURCHASE,
    Permission.OPERATION_REDEEM,
    Permission.OPERATION_TRANSFER,
    Permission.CUSTOMER_INFO_UPDATE,
    Permission.WORKORDER_CREATE,
)


def get_authenticated_chat_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Any:
    """统一复用脚手架 Bearer/JWT 校验。"""
    return _get_current_user(credentials)


def _get_business_user(current_user: Any) -> BaseUserExtModel:
    """读取业务身份扩展，拒绝没有财富管家身份的脚手架账号。"""
    business_user = BaseUserExtModel.get_by_id(getattr(current_user, "id", None))
    if business_user is None:
        raise HTTPException(status_code=403, detail="当前账号没有财富管家业务身份")
    return business_user


def _require_permission(current_user: Any, permission: str) -> None:
    if not AuthService.has_permission(
        current_user.id,
        permission,
        getattr(current_user, "source_module", None),
    ):
        raise HTTPException(status_code=403, detail=f"缺少权限: {permission}")


def _require_permission_or_employee_role(
    current_user: Any,
    business_user: BaseUserExtModel,
    permission: str,
    employee_role: str,
) -> None:
    """兼容历史员工账号尚未补齐 RBAC 关联，但不向其他岗位放宽权限。"""
    if AuthService.has_permission(
        current_user.id,
        permission,
        getattr(current_user, "source_module", None),
    ):
        return
    if getattr(business_user, "employee_role", None) == employee_role:
        return
    raise HTTPException(status_code=403, detail=f"缺少权限: {permission}")


def _authorize_agent(
    agent_type: Optional[str],
    current_user: Any,
    requested_customer_id: Optional[int],
) -> tuple[str, Optional[int]]:
    """校验 Agent 服务对象，并返回可信的 agent_type/customer_id。"""
    business_user = _get_business_user(current_user)
    resolved_type = agent_type or (
        "customer" if business_user.user_type == "CUSTOMER" else "advisor"
    )

    if resolved_type == "risk":
        raise HTTPException(status_code=400, detail="风控监测 Agent 不提供对话入口")
    if resolved_type not in {"customer", "advisor", "analyst", "operator"}:
        raise HTTPException(status_code=400, detail=f"不支持的 agent_type: {resolved_type}")

    if resolved_type == "customer":
        if business_user.user_type != "CUSTOMER":
            raise HTTPException(status_code=403, detail="客服对话入口仅限客户本人访问")
        return resolved_type, current_user.id

    if business_user.user_type != "EMPLOYEE":
        raise HTTPException(status_code=403, detail="该 Agent 仅限员工访问")

    if resolved_type == "advisor":
        _require_permission_or_employee_role(
            current_user,
            business_user,
            Permission.PRODUCT_RECOMMEND,
            "理财顾问",
        )
        if requested_customer_id:
            from app.WealthButler.Service.advisorService import AdvisorService

            if not AdvisorService.advisor_can_access_customer(
                current_user.id,
                requested_customer_id,
            ):
                raise HTTPException(status_code=403, detail="该客户不在当前理财顾问的服务范围内")
    elif resolved_type == "analyst":
        # 业务管理员是管理员权限口径，兼容历史账号尚未同步 RBAC 权限的情况。
        _require_permission_or_employee_role(
            current_user,
            business_user,
            Permission.DATA_NL2SQL_QUERY,
            "业务管理员",
        )
    else:
        if getattr(business_user, "employee_role", None) not in OperatorAccessService.OPERATOR_ROLES:
            raise HTTPException(status_code=403, detail="业务操作 Agent 仅限客户经理或业务管理员访问")
        permissions = set(AuthService.get_user_permissions(
            current_user.id,
            getattr(current_user, "source_module", None),
        ))
        if permissions.isdisjoint(_OPERATOR_ENTRY_PERMISSIONS):
            raise HTTPException(status_code=403, detail="缺少业务操作 Agent 权限")
        if requested_customer_id and not OperatorAccessService.can_access_customer(
            current_user.id,
            requested_customer_id,
        ):
            raise HTTPException(status_code=403, detail="该客户不在当前客户经理的办理范围内，请先领取对应工单")

    return resolved_type, requested_customer_id


# ==================== SSE 流式包装器 ====================

async def sse_wrapper(generator):
    """
    将 Service 层返回的生成器包装为 SSE 格式

    SSE 格式：data: <content>\n\n
    """
    try:
        async for chunk in generator:
            # 如果 chunk 已经是 JSON 字典格式（如错误响应），直接序列化
            if isinstance(chunk, dict):
                sse_data = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            else:
                # 普通字符串 chunk，直接返回
                sse_data = f"data: {chunk}\n\n"

            yield sse_data.encode("utf-8")
    except Exception as e:
        logger.error("对话流式输出失败: %s", e, exc_info=True)
        error_event = f"data: {json.dumps({'type': 'error', 'content': '服务暂时不可用'}, ensure_ascii=False)}\n\n"
        yield error_event.encode("utf-8")


# ==================== 新增：前端简化入口 ====================

@compat_router.post("/wealth/chat")
async def chat_simple(
    request: ChatRequest,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    """
    POST /api/wealth/chat - 前端简化对话接口（兼容前端现有调用）

    前端调用示例：
    {
        "message": "帮我查询客户张三的持仓",
        "agent_type": "advisor",  // 可选
        "conversation_id": "advisor_dashboard_advisor"  // 可选
    }

    自动从请求中推断：
    - user_id: 从认证token解析
    - session_id: 使用conversation_id或自动生成
    - agent_type: 不传时根据 JWT 中对应的客户/员工身份推断
    """
    agent_type, customer_id = _authorize_agent(
        request.agent_type, current_user, request.customer_id
    )

    # 使用conversation_id作为session_id
    session_id = request.conversation_id or request.session_id or "default_session"

    if agent_type == "advisor" and not customer_id:
        raise HTTPException(
            status_code=400,
            detail=f"agent_type={agent_type} 需要传入 customer_id",
        )

    # 流式输出
    if request.is_stream:
        generator = ChatService.route_to_agent(
            agent_type=agent_type,
            message=request.message,
            session_id=session_id,
            user_id=current_user.id,
            customer_id=customer_id
        )
        return StreamingResponse(
            sse_wrapper(generator),
            media_type="text/event-stream"
        )

    # 非流式输出
    return HttpResponse.error("非流式输出暂不支持，请设置 is_stream=true")


# ==================== 统一入口（最高优先级）====================

@router.post("")
async def chat_unified(
    request: ChatRequest,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    """
    POST /api/chat - 统一对话入口

    按 agent_type 分发到对应 Agent：
    - customer: 智能客服（RAG + 会话记忆）
    - advisor: 投顾助手（画像 + 推荐 + 适当性）
    - analyst: 数据分析（NL2SQL）
    - operator: 业务操作（NL2API + 二次确认）
    - risk: 风控监测（无对话入口，事件驱动）

    验证逻辑：
    - advisor/operator 必须传 customer_id
    - agent_type 合法性校验在 Service 层处理

    响应：SSE 流式输出（默认）或 JSON
    """
    agent_type, customer_id = _authorize_agent(
        request.agent_type, current_user, request.customer_id
    )
    if agent_type in ["advisor", "operator"] and not customer_id:
        raise HTTPException(
            status_code=400,
            detail=f"agent_type={agent_type} 需要传入 customer_id"
        )

    # 流式输出
    if request.is_stream:
        generator = ChatService.route_to_agent(
            agent_type=agent_type,
            message=request.message,
            session_id=request.session_id or "default",
            user_id=current_user.id,
            customer_id=customer_id
        )
        return StreamingResponse(
            sse_wrapper(generator),
            media_type="text/event-stream"
        )

    # 非流式输出（暂不实现，项目要求流式为主）
    return HttpResponse.error("非流式输出暂不支持，请设置 is_stream=true")


# ==================== 直连路由（4个）====================

@router.post("/customer")
async def chat_customer(
    request: DirectChatRequest,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    """
    POST /api/chat/customer - 智能客服直连

    功能：RAG知识库检索 + 会话记忆
    权限：客户本人
    """
    _, customer_id = _authorize_agent("customer", current_user, request.customer_id)
    if request.is_stream:
        generator = ChatService.route_to_agent(
            agent_type="customer",
            message=request.message,
            session_id=request.session_id or "default",
            user_id=current_user.id,
            customer_id=customer_id
        )
        return StreamingResponse(
            sse_wrapper(generator),
            media_type="text/event-stream"
        )

    return HttpResponse.error("非流式输出暂不支持")


@router.post("/advisor")
async def chat_advisor(
    request: DirectChatRequest,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    """
    POST /api/chat/advisor - 投顾助手直连

    功能：客户画像 + 产品推荐 + 适当性匹配 + GraphRAG增强
    权限：理财顾问（product:recommend）
    customer_id：必填，用于客户画像和适当性校验
    """
    _, customer_id = _authorize_agent("advisor", current_user, request.customer_id)
    if not customer_id:
        raise HTTPException(status_code=400, detail="投顾助手需要传入 customer_id")
    if request.is_stream:
        generator = ChatService.route_to_agent(
            agent_type="advisor",
            message=request.message,
            session_id=request.session_id or "default",
            user_id=current_user.id,
            customer_id=customer_id
        )
        return StreamingResponse(
            sse_wrapper(generator),
            media_type="text/event-stream"
        )

    return HttpResponse.error("非流式输出暂不支持")


@router.post("/analyst")
async def chat_analyst(
    request: DirectChatRequest,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    """
    POST /api/chat/analyst - 数据分析直连

    功能：NL2SQL（自然语言转SQL + 安全校验）
    权限：全体员工（data:nl2sql_query）
    """
    _, customer_id = _authorize_agent("analyst", current_user, request.customer_id)
    if request.is_stream:
        generator = ChatService.route_to_agent(
            agent_type="analyst",
            message=request.message,
            session_id=request.session_id or "default",
            user_id=current_user.id,
            customer_id=customer_id
        )
        return StreamingResponse(
            sse_wrapper(generator),
            media_type="text/event-stream"
        )

    # 非流式响应：收集完整结果后返回JSON
    try:
        result_chunks = []
        generator = ChatService.route_to_agent(
            agent_type="analyst",
            message=request.message,
            session_id=request.session_id or "default",
            user_id=current_user.id,
            customer_id=customer_id
        )

        async for chunk in generator:
            result_chunks.append(chunk)

        # 拼接所有块并解析JSON
        full_response = "".join(result_chunks)

        try:
            response_data = json.loads(full_response)
            return HttpResponse.ok(data=response_data.get("data"))
        except json.JSONDecodeError:
            # 如果不是JSON格式，返回原始文本
            return HttpResponse.ok(data={"response": full_response})

    except Exception as e:
        logger.error(f"Analyst查询失败: {e}", exc_info=True)
        return HttpResponse.error(f"查询失败: {str(e)}")


@router.post("/operator")
async def chat_operator(
    request: DirectChatRequest,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    """
    POST /api/chat/operator - 业务操作直连

    功能：NL2API（意图识别 + 参数提取 + RBAC + 二次确认）
    权限：客户经理/运营（申购、赎回、转账、信息更新和产品查询）
    customer_id：必填，员工仅可代指定客户发起操作
    注意：客户不可直接访问，仅员工代客户操作
    """
    _, customer_id = _authorize_agent("operator", current_user, request.customer_id)
    if request.is_stream:
        generator = ChatService.route_to_agent(
            agent_type="operator",
            message=request.message,
            session_id=request.session_id or "default",
            user_id=current_user.id,
            customer_id=customer_id
        )
        return StreamingResponse(
            sse_wrapper(generator),
            media_type="text/event-stream"
        )

    return HttpResponse.error("非流式输出暂不支持")


@router.post("/operator/confirm")
def operator_confirm(
    request: OperatorConfirmRequest,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    """
    POST /api/chat/operator/confirm - 客户经理撤回待确认业务

    资金操作的最终确认只能由客户本人通过客户接口完成。客户经理只能撤回。
    """
    _authorize_agent("operator", current_user, None)
    if request.action != "cancel":
        raise HTTPException(status_code=409, detail="资金操作须由客户本人在客户页面确认，客户经理不能代为确认")
    runtime = ChatService._operator_runtime
    pending = runtime.service.confirmation_service.get_pending(request.confirm_token) if runtime else None
    if pending and not OperatorAccessService.can_access_customer(current_user.id, pending.customer_id):
        raise HTTPException(status_code=403, detail="该客户不在当前客户经理的办理范围内，请先领取对应工单")
    result = ChatService.confirm_operator_action(
        employee_id=current_user.id,
        confirm_token=request.confirm_token,
        action=request.action
    )

    if not result.get("success"):
        status_code = 503 if result.get("code") == "OPERATOR_RUNTIME_UNAVAILABLE" else 400
        raise HTTPException(
            status_code=status_code,
            detail=result.get("message", "确认操作失败"),
        )

    return HttpResponse.ok(data=result)


@router.get("/operator/confirmations/{confirm_token}")
def get_operator_confirmation_status(
    confirm_token: str,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    """Return customer confirmation progress to the originating operator."""
    _authorize_agent("operator", current_user, None)
    runtime = ChatService._operator_runtime
    if runtime is None:
        raise HTTPException(status_code=503, detail="业务操作运行时尚未配置")
    pending = runtime.service.confirmation_service.get_pending(confirm_token)
    if pending is None:
        raise HTTPException(status_code=404, detail="确认请求不存在或已过期")
    if not OperatorAccessService.can_access_customer(current_user.id, pending.customer_id):
        raise HTTPException(status_code=403, detail="无权查看其他客户的确认状态")
    result = pending.result.to_dict() if pending.result else None
    return HttpResponse.ok(data={"status": pending.status, "result": result})


@router.get("/operator/notifications")
def get_operator_notifications(
    limit: int = Query(50, ge=1, le=100),
    current_user: Any = Depends(get_authenticated_chat_user),
):
    """Return customer confirmation results addressed to this operator."""
    _authorize_agent("operator", current_user, None)
    try:
        from app.Base.Client.redisClient import redis_client
        values = redis_client.client.lrange(f"notifications:operator:{current_user.id}", 0, limit - 1) or []
    except Exception as exc:
        raise HTTPException(status_code=503, detail="通知服务暂时不可用") from exc
    items = []
    for value in values:
        try:
            item = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            continue
        if item.get("type") != "customer_confirmation_result" or item.get("operator_id") != current_user.id:
            continue
        items.append(item)
    return HttpResponse.ok(data={"items": items, "total": len(items)})


# ==================== 会话历史 ====================

@router.get("/session/{session_id}/history")
async def get_session_history(
    session_id: str,
    limit: int = Query(50, ge=1, le=100),
    current_user: Any = Depends(get_authenticated_chat_user),
):
    """
    GET /api/chat/session/{session_id}/history - 获取会话历史

    Args:
        session_id: 会话ID
        limit: 返回最近N条记录（默认50）

    Returns:
        会话历史消息列表
    """
    _, customer_id = _authorize_agent("customer", current_user, None)
    conversation = CustomerService().get_conversation(session_id, customer_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = conversation.get("messages", [])[-limit:]
    return HttpResponse.ok(data={"items": messages, "total": len(messages)})


# ==================== 路由注册函数 ====================

def register_wealth_chat_router(app):
    """注册财富管家对话路由到 FastAPI app"""
    app.include_router(router, prefix="/api/chat")
    app.include_router(compat_router, prefix="/api")
