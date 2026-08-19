"""业务操作 HTTP 接口与对话接口共用的适配函数。"""

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.Base.Api.authApi import _get_current_user, security
from app.Base.RicUtils.httpUtils import HttpResponse
from app.WealthButler.Service.chatService import ChatService
from app.WealthButler.Service.operatorAccessService import OperatorAccessService
from app.WealthButler.Service.operatorApiRuntime import (
    OperatorApiRuntime,
    to_json_safe_result,
)


def get_authenticated_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Any:
    """复用脚手架 Bearer/JWT 校验，不允许客户端传递员工身份。"""
    return _get_current_user(credentials)


def ensure_employee_user(current_user: Any) -> Any:
    """业务操作仅允许员工发起，权限字符串不能替代员工身份边界。"""
    user_type = getattr(current_user, "user_type", None)
    if user_type is None:
        # authApi 当前返回脚手架 UserModel（未声明业务扩展列），仅在此时读取扩展模型。
        # 延迟导入可避免 Fake Runtime 的离线验收触发数据库初始化。
        from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel
        user_id = getattr(current_user, "id", None)
        business_user = BaseUserExtModel.get_by_id(user_id) if isinstance(user_id, int) else None
        user_type = business_user.user_type if business_user else None
    if user_type != "EMPLOYEE":
        raise HTTPException(status_code=403, detail="业务操作仅限员工身份访问")
    if not OperatorAccessService.can_use_operator(getattr(current_user, "id", 0)):
        raise HTTPException(status_code=403, detail="业务操作仅限客户经理或业务管理员访问")
    return current_user


def get_authenticated_employee(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Any:
    """组合 JWT 与员工身份校验，供所有业务操作入口复用。"""
    return ensure_employee_user(get_authenticated_user(credentials))


def ensure_operator_runtime(runtime: Optional[OperatorApiRuntime] = None) -> OperatorApiRuntime:
    """装配指定的正式 Runtime；生产入口禁止隐式回退到 Fake。"""
    if runtime is not None:
        if runtime.runtime_mode != "real":
            raise ValueError("正式业务入口只允许装配 real OperatorApiRuntime")
        ChatService.configure_operator_runtime(runtime)
        return runtime
    if ChatService._operator_runtime is None:
        raise RuntimeError("正式业务操作运行时尚未配置")
    if ChatService._operator_runtime.runtime_mode != "real":
        raise RuntimeError("正式业务入口检测到非 real OperatorApiRuntime")
    return ChatService._operator_runtime


def execute_structured_operation(
    employee_id: int,
    customer_id: int,
    intent: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """通过既有 APIExecutor 执行结构化请求，避免 REST 入口复制业务规则。"""
    runtime = ChatService._operator_runtime
    if runtime is None:
        return {
            "success": False,
            "code": "OPERATOR_RUNTIME_UNAVAILABLE",
            "message": "业务操作运行时尚未配置",
            "data": {},
            "metadata": {},
        }
    if not OperatorAccessService.can_access_customer(employee_id, customer_id):
        return {
            "success": False,
            "code": "CUSTOMER_SCOPE_DENIED",
            "message": "该客户不在当前客户经理的办理范围内，请先领取对应工单",
            "data": {},
            "metadata": {},
        }
    return to_json_safe_result(runtime.submit(employee_id, customer_id, intent, params))


def operation_response(result: Dict[str, Any]) -> HttpResponse:
    """将确定性业务结果映射到项目统一 HTTP 范式。"""
    if result.get("success"):
        return HttpResponse.ok(data=result)

    code = result.get("code", "")
    status_code = 400
    if code in {"PERMISSION_DENIED", "CUSTOMER_SCOPE_DENIED"}:
        status_code = 403
    elif code in {"CUSTOMER_NOT_FOUND", "PRODUCT_NOT_FOUND", "CONFIRMATION_NOT_FOUND"}:
        status_code = 404
    elif code in {"OPERATOR_RUNTIME_UNAVAILABLE", "CONFIRMATION_EXECUTION_UNKNOWN"}:
        status_code = 503
    raise HTTPException(status_code=status_code, detail=result.get("message", "业务操作失败"))
