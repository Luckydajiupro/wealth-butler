"""业务操作的结构化 REST API。

本层不包含交易、适当性或确认判断；所有请求均下沉到既有 APIExecutorTool，
确保与对话入口使用同一套确定性业务规则。
"""

import os
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.Base.RicUtils.httpUtils import HttpResponse
from app.WealthButler.Api.operatorApiSupport import (
    execute_structured_operation,
    get_authenticated_employee,
    operation_response,
)
from app.WealthButler.Service.operatorAccessService import OperatorAccessService


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


@router.get("/customers/{customer_id}/overview")
def customer_overview(
    customer_id: int,
    current_user: Any = Depends(get_authenticated_employee),
):
    """返回客户经理可办理客户的只读业务概览。

    客户经理只能查看自己已领取/负责的客户；业务管理员可查看全量客户。
    资金余额、持仓和交易流水均来自现有业务表，不在接口层生成模拟值。
    """
    if not OperatorAccessService.can_view_customer(current_user.id, customer_id):
        raise HTTPException(status_code=403, detail="该客户不在当前客户经理的办理范围内")

    from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel
    from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
    from app.WealthButler.Models.holdingsModel import HoldingsModel
    from app.WealthButler.Models.transactionModel import TransactionModel
    from app.WealthButler.Models.productModel import ProductModel
    from app.WealthButler.Models.advisorAllocationPlanModel import AdvisorAllocationPlanModel
    from app.WealthButler.Service.riskAssessService import RiskAssessService

    customer = BaseUserExtModel.get_by_id(customer_id)
    if customer is None or getattr(customer, "user_type", None) != "CUSTOMER":
        raise HTTPException(status_code=404, detail="客户不存在")
    profile = CustomerProfileModel.find_by_customer_id(customer_id)
    assessment = RiskAssessService.get_latest_assessment(customer_id)
    allocation = getattr(profile, "asset_allocation", None) if profile else None
    if not isinstance(allocation, dict):
        allocation = {}
    available = allocation.get("available_balance", allocation.get("cash_reserve"))
    balance_source = "customer_profile.asset_allocation" if available is not None else None
    balance_is_simulated = False
    if available is None and allocation.get("total_assets") is not None:
        # Keep read-only overview consistent with the transaction gateway when
        # legacy profiles have total assets but no explicit cash field.
        try:
            from app.WealthButler.Models.holdingsModel import HoldingsModel

            holding_total = sum(
                Decimal(str(getattr(item, "current_value", 0) or 0))
                for item in HoldingsModel.find_by_customer_id(customer_id)
            )
            available = max(Decimal("0"), Decimal(str(allocation["total_assets"])) - holding_total)
            balance_source = "customer_profile.total_assets_minus_holdings"
        except (InvalidOperation, TypeError, ValueError):
            available = None
    if available is None and os.getenv("WEALTH_BUTLER_SIMULATED_COMPLIANCE_ENABLED", "false").lower() == "true":
        # Historical demo profiles contain only allocation ratios. The real
        # operator gateway initializes these accounts from the same test cash.
        try:
            available = Decimal(os.getenv("WEALTH_BUTLER_SIMULATED_INITIAL_CASH", "100000.00"))
            balance_source = "simulated_initial_cash"
            balance_is_simulated = True
        except InvalidOperation:
            available = None
    advisor_plan = AdvisorAllocationPlanModel.find_latest_by_customer_id(customer_id)
    advisor = (
        BaseUserExtModel.get_by_id(advisor_plan.advisor_id)
        if advisor_plan is not None
        else None
    )

    def value(item: Any, field: str, default: Any = None) -> Any:
        raw = getattr(item, field, default)
        if hasattr(raw, "isoformat"):
            return raw.isoformat()
        if hasattr(raw, "quantize"):
            return float(raw)
        return raw

    holdings = []
    for holding in HoldingsModel.find_by_customer_id(customer_id):
        product = ProductModel.get_by_id(holding.product_id)
        holdings.append({
            "product_id": holding.product_id,
            "product_name": getattr(product, "product_name", None) or f"产品 {holding.product_id}",
            "product_code": getattr(product, "product_code", None),
            "risk_level": getattr(product, "risk_level", None),
            "shares": value(holding, "shares", 0),
            "cost_amount": value(holding, "cost_amount", 0),
            "current_value": value(holding, "current_value", 0),
            "profit_loss": value(holding, "profit_loss", 0),
            "profit_ratio": value(holding, "profit_ratio", 0),
        })

    transactions = []
    for transaction in TransactionModel.find_by_customer_id(customer_id, limit=20):
        product = ProductModel.get_by_id(transaction.product_id) if transaction.product_id else None
        transactions.append({
            "id": transaction.id,
            "transaction_type": transaction.transaction_type,
            "amount": value(transaction, "amount", 0),
            "shares": value(transaction, "shares"),
            "status": transaction.status,
            "transaction_time": value(transaction, "transaction_time"),
            "product_name": getattr(product, "product_name", None) or "非产品交易",
        })

    return HttpResponse.ok(data={
        "customer": {
            "id": customer.id,
            "name": customer.username,
            "phone": customer.phone,
            "email": customer.email,
            "customer_level": customer.customer_level,
        },
        "profile": {
            "risk_level": getattr(profile, "risk_level", None),
            "risk_score": value(profile, "risk_score"),
            "dimension1_score": value(profile, "dimension1_score"),
            "dimension2_score": value(profile, "dimension2_score"),
            "dimension3_score": value(profile, "dimension3_score"),
            "dimension4_score": value(profile, "dimension4_score"),
            "confidence_score": value(profile, "confidence_score"),
            "fm_flags": getattr(profile, "fm_flags", None) if profile else None,
            "updated_reason": getattr(profile, "updated_reason", None) if profile else None,
            "updated_at": value(profile, "updated_at"),
            "valid_until": value(assessment, "valid_until"),
            "asset_allocation": allocation,
            "product_preference": getattr(profile, "product_preference", None) if profile else None,
        },
        "account": {
            "available_balance": float(available) if available is not None else None,
            "balance_source": balance_source,
            "balance_is_simulated": balance_is_simulated,
        },
        "holdings": holdings,
        "transactions": transactions,
        "advisor_plan": {
            "id": advisor_plan.id,
            "advisor_id": advisor_plan.advisor_id,
            "advisor_name": getattr(advisor, "username", None),
            "risk_level": advisor_plan.risk_level,
            "products": advisor_plan.products,
            "disclaimer": advisor_plan.disclaimer,
            "created_at": value(advisor_plan, "created_at"),
        } if advisor_plan else None,
    })


def register_operator_api(app: Any) -> None:
    """注册结构化业务操作路由。"""
    app.include_router(router)
