"""智能客服 API。

路由未自动写入 Base/main.py，避免修改脚手架。由集成负责人调用
``register_customer_chat_router(app)`` 注册到应用。
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.Base.Api.authApi import _get_current_user, security
from app.Base.RicUtils.httpUtils import HttpResponse
from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent

router = APIRouter(prefix="/api/chat", tags=["智能客服"])
_agent = CustomerServiceAgent()


class CustomerChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    customer_id: int = Field(..., gt=0)
    session_id: Optional[str] = Field(default=None, max_length=64)
    is_stream: bool = False


@router.post("/customer")
def customer_chat(
    request: CustomerChatRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """运行真实的客服 Agent 对话。"""
    current_user = _get_current_user(credentials)
    # 仅开放客户本人调用；员工代客户需在真实 RBAC 规则落地后再开放。
    if current_user.id != request.customer_id:
        raise HTTPException(status_code=403, detail="无权代表该客户发起客服会话")
    result = _agent.run(
        request.question,
        customer_id=request.customer_id,
        session_id=request.session_id,
    )
    data = result.model_dump()
    if not request.is_stream:
        return HttpResponse.ok(data=data)

    def generate():
        yield f"data: {json.dumps({'type': 'content', 'content': result.output}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'tool_calls': result.tool_calls, 'duration_ms': result.duration_ms}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/session/{session_id}/history")
def customer_session_history(
    session_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """返回已归档的会话历史，并校验 JWT 与会话归属。"""
    current_user = _get_current_user(credentials)
    conversation = _agent.customer_service.get_conversation(session_id, current_user.id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return HttpResponse.ok(data={"items": conversation["messages"]})


def register_customer_chat_router(app) -> None:
    """由应用集成层显式调用，避免业务模块自行修改 Base 脚手架。"""
    app.include_router(router)
