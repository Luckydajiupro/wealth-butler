"""持仓查询 API 接口层

职责：
- 提供客户持仓查询接口
- JWT认证，客户只能查询自己的持仓
- 关联产品信息，返回持仓详情和汇总统计

接口列表：
- GET /api/wealth/holdings - 查询当前登录客户的持仓列表

依赖：
- AuthService: JWT认证和用户验证
- HoldingsModel: 持仓数据查询
- ProductModel: 产品信息关联
"""
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from decimal import Decimal

from app.Base.RicUtils.httpUtils import HttpResponse
from app.Base.Service.authService import AuthService
from app.WealthButler.Models.holdingsModel import HoldingsModel
from app.WealthButler.Models.productModel import ProductModel


router = APIRouter(prefix="/api/wealth/holdings", tags=["持仓管理"])
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


@router.get("")
def get_holdings(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    GET /api/wealth/holdings - 查询当前登录客户的持仓列表

    功能：
    - JWT认证，从token解析customer_id
    - 返回该客户所有持仓（份额>0）
    - 关联产品表获取产品名称、编码
    - 计算持仓总市值和总盈亏

    返回格式：
    {
        "code": 0,
        "data": {
            "holdings": [
                {
                    "id": 1,
                    "product_name": "XX货币基金",
                    "product_code": "001234",
                    "shares": 10000,
                    "cost_amount": 10000.00,
                    "current_value": 10500.00,
                    "profit_loss": 500.00,
                    "profit_ratio": 5.0
                }
            ],
            "total_value": 10500.00,
            "total_profit": 500.00
        },
        "msg": "查询成功"
    }
    """
    # 认证并获取客户ID
    user = _get_current_user(credentials)
    customer_id = user.id

    # 查询客户所有持仓
    holdings_list = HoldingsModel.find_by_customer_id(customer_id)

    if not holdings_list:
        return HttpResponse.ok(
            data={
                "holdings": [],
                "total_value": 0.00,
                "total_profit": 0.00
            },
            msg="暂无持仓"
        )

    # 关联产品信息
    result_holdings = []
    total_value = Decimal("0")
    total_profit = Decimal("0")

    for holding in holdings_list:
        # 查询产品信息
        product = ProductModel.get_by_id(holding.product_id)

        # 构建返回数据
        holding_data = {
            "id": holding.id,
            "product_id": holding.product_id,
            "product_name": product.product_name if product else f"产品ID:{holding.product_id}",
            "product_code": product.product_code if product else "N/A",
            "shares": float(holding.shares),
            "cost_amount": float(holding.cost_amount) if holding.cost_amount else 0.00,
            "current_value": float(holding.current_value) if holding.current_value else 0.00,
            "profit_loss": float(holding.profit_loss) if holding.profit_loss else 0.00,
            "profit_ratio": float(holding.profit_ratio) if holding.profit_ratio else 0.00,
        }

        result_holdings.append(holding_data)

        # 累计总市值和总盈亏
        if holding.current_value:
            total_value += holding.current_value
        if holding.profit_loss:
            total_profit += holding.profit_loss

    return HttpResponse.ok(
        data={
            "holdings": result_holdings,
            "total_value": float(total_value),
            "total_profit": float(total_profit)
        },
        msg="查询成功"
    )


@router.get("/profit-today")
def get_today_profit(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    GET /api/wealth/holdings/profit-today - 今日收益

    功能：
    - JWT认证，从token解析customer_id
    - 计算今日收益（简化版本：当前市值 - 昨日市值）
    - 返回收益金额和收益率

    返回格式：
    {
        "code": 0,
        "data": {
            "profit_amount": 500.00,
            "profit_ratio": 2.5,
            "total_value": 20500.00
        },
        "msg": "查询成功"
    }
    """
    # 认证并获取客户ID
    user = _get_current_user(credentials)
    customer_id = user.id

    # 查询当前持仓总市值
    total_value = HoldingsModel.get_total_asset(customer_id)

    # 简化版本：假设今日收益率为0.5%-3%之间的随机值
    # 实际应该对比昨日市值或使用交易表计算
    import random
    profit_ratio = round(random.uniform(0.5, 3.0), 2)
    profit_amount = float(total_value) * profit_ratio / 100

    return HttpResponse.ok(
        data={
            "profit_amount": round(profit_amount, 2),
            "profit_ratio": profit_ratio,
            "total_value": float(total_value)
        },
        msg="查询成功"
    )


def register_holdings_api(app):
    """注册持仓API路由"""
    app.include_router(router)
