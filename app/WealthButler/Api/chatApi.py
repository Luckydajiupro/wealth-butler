"""对话 API 接口层

职责：
- 提供统一入口 POST /api/chat 按 agent_type 分发
- 提供 5 个 Agent 直连路由
- 提供业务操作二次确认接口
- 提供会话历史查询接口
- SSE 流式返回
- 统一响应格式包装

参考：app/Base/Api/ai/chatApi.py 的流式实现模式
"""
import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.Base.RicUtils.httpUtils import HttpResponse
from app.WealthButler.Service.chatService import ChatService

logger = logging.getLogger(__name__)


# ==================== 请求模型 ====================

class ChatRequest(BaseModel):
    """统一对话请求模型"""
    message: str = Field(..., description="用户消息")
    agent_type: Optional[str] = Field(None, description="Agent类型: customer|advisor|analyst|operator|risk（可选，前端可不传）")
    conversation_id: Optional[str] = Field(None, description="会话ID，不传则自动创建")
    session_id: Optional[str] = Field(None, description="会话ID（兼容旧字段）")
    user_id: Optional[int] = Field(None, description="当前登录用户ID（可从token解析）")
    customer_id: Optional[int] = Field(None, description="客户ID（投顾/业务操作必填）")
    is_stream: bool = Field(True, description="是否流式输出，默认True")


class DirectChatRequest(BaseModel):
    """直连路由请求模型（无需 agent_type）"""
    message: str = Field(..., description="用户消息")
    session_id: Optional[str] = Field(None, description="会话ID，不传则自动创建")
    user_id: int = Field(..., description="当前登录用户ID")
    customer_id: Optional[int] = Field(None, description="客户ID（投顾/业务操作必填）")
    is_stream: bool = Field(True, description="是否流式输出，默认True")


class OperatorConfirmRequest(BaseModel):
    """业务操作二次确认请求模型"""
    confirm_token: str = Field(..., description="待确认操作的token")
    action: str = Field(..., description="confirm（确认执行）| cancel（取消）")


# ==================== 路由定义 ====================

# 注意：prefix 不要重复，register 函数会添加前缀
router = APIRouter(tags=["对话接口"])


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
                import json
                sse_data = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            else:
                # 普通字符串 chunk，直接返回
                sse_data = f"data: {chunk}\n\n"

            yield sse_data.encode("utf-8")
    except Exception as e:
        # 流式输出中的异常，返回错误事件
        import json
        error_event = f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
        yield error_event.encode("utf-8")


# ==================== 新增：前端简化入口 ====================

@router.post("/wealth/chat")
async def chat_simple(request: ChatRequest):
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
    - agent_type: 如果不传，默认为 advisor
    """
    # 设置默认值
    if not request.agent_type:
        request.agent_type = "advisor"

    if not request.user_id:
        # TODO: 从认证token解析user_id，暂时使用默认值
        request.user_id = 1

    # 使用conversation_id作为session_id
    session_id = request.conversation_id or request.session_id or "default_session"

    # 参数校验
    if request.agent_type in ["advisor", "operator"] and not request.customer_id:
        # advisor和operator如果没有customer_id，也允许通过（用于通用咨询）
        pass

    # 流式输出
    if request.is_stream:
        generator = ChatService.route_to_agent(
            agent_type=request.agent_type,
            message=request.message,
            session_id=session_id,
            user_id=request.user_id,
            customer_id=request.customer_id
        )
        return StreamingResponse(
            sse_wrapper(generator),
            media_type="text/event-stream"
        )

    # 非流式输出
    return HttpResponse.error("非流式输出暂不支持，请设置 is_stream=true")


# ==================== 统一入口（最高优先级）====================

@router.post("")
async def chat_unified(request: ChatRequest):
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
    # 参数校验
    if request.agent_type in ["advisor", "operator"] and not request.customer_id:
        raise HTTPException(
            status_code=400,
            detail=f"agent_type={request.agent_type} 需要传入 customer_id"
        )

    # 流式输出
    if request.is_stream:
        generator = ChatService.route_to_agent(
            agent_type=request.agent_type,
            message=request.message,
            session_id=request.session_id or "default",
            user_id=request.user_id,
            customer_id=request.customer_id
        )
        return StreamingResponse(
            sse_wrapper(generator),
            media_type="text/event-stream"
        )

    # 非流式输出（暂不实现，项目要求流式为主）
    return HttpResponse.error("非流式输出暂不支持，请设置 is_stream=true")


# ==================== 直连路由（5个）====================

@router.post("/customer")
async def chat_customer(request: DirectChatRequest):
    """
    POST /api/chat/customer - 智能客服直连

    功能：RAG知识库检索 + 会话记忆
    权限：客户本人 或 员工代客户
    """
    if request.is_stream:
        generator = ChatService.route_to_agent(
            agent_type="customer",
            message=request.message,
            session_id=request.session_id or "default",
            user_id=request.user_id,
            customer_id=request.customer_id
        )
        return StreamingResponse(
            sse_wrapper(generator),
            media_type="text/event-stream"
        )

    return HttpResponse.error("非流式输出暂不支持")


@router.post("/advisor")
async def chat_advisor(request: DirectChatRequest):
    """
    POST /api/chat/advisor - 投顾助手直连

    功能：客户画像 + 产品推荐 + 适当性匹配 + GraphRAG增强
    权限：理财顾问（product:recommend）
    必填：customer_id
    """
    if not request.customer_id:
        raise HTTPException(status_code=400, detail="投顾助手需要传入 customer_id")

    if request.is_stream:
        generator = ChatService.route_to_agent(
            agent_type="advisor",
            message=request.message,
            session_id=request.session_id or "default",
            user_id=request.user_id,
            customer_id=request.customer_id
        )
        return StreamingResponse(
            sse_wrapper(generator),
            media_type="text/event-stream"
        )

    return HttpResponse.error("非流式输出暂不支持")


@router.post("/analyst")
async def chat_analyst(request: DirectChatRequest):
    """
    POST /api/chat/analyst - 数据分析直连

    功能：NL2SQL（自然语言转SQL + 安全校验）
    权限：全体员工（data:nl2sql_query）
    """
    if request.is_stream:
        generator = ChatService.route_to_agent(
            agent_type="analyst",
            message=request.message,
            session_id=request.session_id or "default",
            user_id=request.user_id,
            customer_id=request.customer_id
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
            user_id=request.user_id,
            customer_id=request.customer_id
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
async def chat_operator(request: DirectChatRequest):
    """
    POST /api/chat/operator - 业务操作直连

    功能：NL2API（意图识别 + 参数提取 + RBAC + 二次确认）
    权限：理财顾问（申购/赎回/风评重做）+ 客户经理（转账/信息更新/工单创建）
    必填：customer_id
    注意：客户不可直接访问，仅员工代客户操作
    """
    if not request.customer_id:
        raise HTTPException(status_code=400, detail="业务操作需要传入 customer_id")

    if request.is_stream:
        generator = ChatService.route_to_agent(
            agent_type="operator",
            message=request.message,
            session_id=request.session_id or "default",
            user_id=request.user_id,
            customer_id=request.customer_id
        )
        return StreamingResponse(
            sse_wrapper(generator),
            media_type="text/event-stream"
        )

    return HttpResponse.error("非流式输出暂不支持")


@router.post("/operator/confirm")
def operator_confirm(request: OperatorConfirmRequest):
    """
    POST /api/chat/operator/confirm - 业务操作二次确认闭环

    状态机流转：
    - 待确认 --(action=confirm)--> 已确认 --(立即执行)--> 执行完成
    - 待确认 --(action=cancel)--> 已取消

    说明：
    - 申购>1万元 或 转账>5万元 需要二次确认
    - confirm_token 由 /operator 接口返回的 metadata.confirm_token 提供
    """
    result = ChatService.confirm_operator_action(
        confirm_token=request.confirm_token,
        action=request.action
    )

    if result.get("status") == "error":
        return HttpResponse.error(result.get("message"))

    return HttpResponse.ok(data=result)


# ==================== 会话历史 ====================

@router.get("/session/{session_id}/history")
async def get_session_history(session_id: str, limit: int = 50):
    """
    GET /api/chat/session/{session_id}/history - 获取会话历史

    Args:
        session_id: 会话ID
        limit: 返回最近N条记录（默认50）

    Returns:
        会话历史消息列表
    """
    history = await ChatService.get_session_history(session_id, limit)
    return HttpResponse.ok(data=history)


# ==================== 路由注册函数 ====================

def register_wealth_chat_router(app):
    """注册财富管家对话路由到 FastAPI app"""
    app.include_router(router, prefix="/api/chat")
