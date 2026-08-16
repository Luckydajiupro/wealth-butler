"""业务操作的结构化 REST API。

本层不包含交易、适当性或确认判断；所有请求均下沉到既有 APIExecutorTool，
确保与对话入口使用同一套确定性业务规则。
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.Base.RicUtils.httpUtils import HttpResponse
from app.WealthButler.Api.operatorApiSupport import (
    execute_structured_operation,
    get_authenticated_employee,
    operation_response,
)


router = APIRouter(prefix="/api/operation", tags=["业务操作"])


class _OperationRequest(BaseModel):
    """结构化操作统一拒绝未声明字段，防止受保护上下文被静默吞掉。"""

    model_config = ConfigDict(extra="forbid")


class PurchaseRequest(_OperationRequest):
    """申购请求；金额以字符串传递以保护 Decimal 精度。"""

    customer_id: int = Field(..., gt=0, description="客户ID")
    product_id: int = Field(..., gt=0, description="产品ID")
    amount: str = Field(..., min_length=1, description="申购金额，最多两位小数")


class RedeemRequest(_OperationRequest):
    """赎回请求；份额以字符串传递以避免浮点精度损失。"""

    customer_id: int = Field(..., gt=0, description="客户ID")
    product_id: int = Field(..., gt=0, description="产品ID")
    shares: str = Field(..., min_length=1, description="赎回份额")


class TransferRequest(_OperationRequest):
    """转账请求。员工身份仅从 Bearer Token 取得。"""

    customer_id: int = Field(..., gt=0, description="客户ID")
    amount: str = Field(..., min_length=1, description="转账金额，最多两位小数")
    counterparty_account: str = Field(..., min_length=1, description="收款账号")
    counterparty_name: str = Field(..., min_length=1, description="收款人名称")


class ContactUpdateRequest(_OperationRequest):
    """客户联系方式更新请求。"""

    customer_id: int = Field(..., gt=0, description="客户ID")
    phone: Optional[str] = Field(None, description="手机号")
    email: Optional[str] = Field(None, description="邮箱")


def _submit(current_user: Any, customer_id: int, intent: str, params: Dict[str, Any]) -> HttpResponse:
    """统一委派运行时，业务权限在 APIExecutor/OperationService 中动态校验。"""
    result = execute_structured_operation(
        employee_id=current_user.id,
        customer_id=customer_id,
        intent=intent,
        params=params,
    )
    return operation_response(result)


@router.post("/purchase")
def purchase(request: PurchaseRequest, current_user: Any = Depends(get_authenticated_employee)):
    """执行申购或在超过阈值时返回确认令牌。"""
    return _submit(current_user, request.customer_id, "purchase", {
        "product_id": request.product_id,
        "amount": request.amount,
    })


@router.post("/redeem")
def redeem(request: RedeemRequest, current_user: Any = Depends(get_authenticated_employee)):
    """执行赎回；可赎份额与风控校验由业务服务完成。"""
    return _submit(current_user, request.customer_id, "redeem", {
        "product_id": request.product_id,
        "shares": request.shares,
    })


@router.post("/transfer")
def transfer(request: TransferRequest, current_user: Any = Depends(get_authenticated_employee)):
    """执行转账或在超过阈值时返回确认令牌。"""
    return _submit(current_user, request.customer_id, "transfer", {
        "amount": request.amount,
        "counterparty_account": request.counterparty_account,
        "counterparty_name": request.counterparty_name,
    })


@router.put("/contact")
def update_contact(
    request: ContactUpdateRequest,
    current_user: Any = Depends(get_authenticated_employee),
):
    """更新客户联系方式，至少提交手机号或邮箱其中一项。"""
    if not (request.phone or request.email):
        raise HTTPException(status_code=400, detail="至少需要提供手机号或邮箱")
    return _submit(current_user, request.customer_id, "update_info", {
        "phone": request.phone,
        "email": request.email,
    })


def register_operator_api(app: Any) -> None:
    """注册结构化业务操作路由。"""
    app.include_router(router)
