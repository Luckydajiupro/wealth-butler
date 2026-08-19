"""持仓和收益查询工具

职责：
- 为CustomerServiceAgent提供持仓查询能力
- 查询今日收益、累计收益
- 查询持仓列表
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field

from app.Base.Ai.base.baseTool import BaseTool
from app.WealthButler.Models.holdingsModel import HoldingsModel
from app.WealthButler.Models.productModel import ProductModel
from decimal import Decimal


class HoldingsQueryArgs(BaseModel):
    query_type: Literal["today_profit", "holdings_list", "total_asset"] = Field(
        ...,
        description="查询类型: today_profit=今日收益, holdings_list=持仓列表, total_asset=总资产"
    )
    customer_id: int = Field(..., description="客户ID")


class HoldingsTool(BaseTool):
    """持仓和收益查询工具

    提供三种查询能力：
    1. today_profit - 今日收益和收益率
    2. holdings_list - 持仓产品列表
    3. total_asset - 总资产
    """

    name = "HoldingsQuery"
    description = (
        "查询客户的持仓和收益信息。"
        "支持查询：今日收益(today_profit)、持仓列表(holdings_list)、总资产(total_asset)。"
        "当客户询问'今日收益'、'我的持仓'、'总资产'等问题时使用此工具。"
    )
    args_schema = HoldingsQueryArgs

    def execute(self, query_type: str, customer_id: int) -> dict:
        """执行持仓查询

        Args:
            query_type: 查询类型
            customer_id: 客户ID

        Returns:
            查询结果字典
        """
        if query_type == "today_profit":
            return self._get_today_profit(customer_id)
        elif query_type == "holdings_list":
            return self._get_holdings_list(customer_id)
        elif query_type == "total_asset":
            return self._get_total_asset(customer_id)
        else:
            return {
                "success": False,
                "error": f"不支持的查询类型: {query_type}"
            }

    def _get_today_profit(self, customer_id: int) -> dict:
        """查询今日收益

        Returns:
            {
                "success": True,
                "profit_amount": 123.45,  # 今日收益金额
                "profit_ratio": 1.23,     # 今日收益率(%)
                "total_value": 10000.00,  # 当前总资产
                "message": "今日收益为+123.45元，收益率为+1.23%"
            }
        """
        from app.WealthButler.Api.holdingsApi import calculate_today_profit

        data = calculate_today_profit(customer_id)
        profit = float(data["today_profit"])
        rate = float(data["today_profit_rate"])
        source = data["calculation_source"]
        if source == "no_holdings":
            message = "您暂无持仓，今日收益为0元"
        else:
            sign = "+" if profit >= 0 else ""
            rate_sign = "+" if rate >= 0 else ""
            suffix = "（模拟）" if source == "simulated" else ""
            message = (
                f"您今日收益为{sign}{profit:.2f}元，"
                f"收益率为{rate_sign}{rate:.2f}%{suffix}"
            )
        return {
            "success": True,
            "profit_amount": profit,
            "profit_ratio": rate,
            "total_value": float(data["total_value"]),
            "calculation_source": source,
            "as_of_date": data["as_of_date"],
            "message": message,
        }

    def _get_holdings_list(self, customer_id: int) -> dict:
        """查询持仓列表

        Returns:
            {
                "success": True,
                "holdings": [
                    {
                        "product_name": "XX货币基金",
                        "product_code": "001234",
                        "shares": 10000,
                        "current_value": 10500.00,
                        "profit_loss": 500.00,
                        "profit_ratio": 5.0
                    }
                ],
                "total_value": 10500.00,
                "total_profit": 500.00,
                "message": "您持有2个产品，总市值10500.00元，总盈亏500.00元"
            }
        """
        holdings_list = HoldingsModel.find_by_customer_id(customer_id)

        if not holdings_list:
            return {
                "success": True,
                "holdings": [],
                "total_value": 0.00,
                "total_profit": 0.00,
                "message": "您暂无持仓"
            }

        # 关联产品信息
        result_holdings = []
        total_value = Decimal("0")
        total_profit = Decimal("0")

        for holding in holdings_list:
            product = ProductModel.get_by_id(holding.product_id)

            holding_data = {
                "product_id": holding.product_id,
                "product_name": product.product_name if product else f"产品ID:{holding.product_id}",
                "product_code": product.product_code if product else "N/A",
                "shares": float(holding.shares),
                "current_value": float(holding.current_value) if holding.current_value else 0.00,
                "profit_loss": float(holding.profit_loss) if holding.profit_loss else 0.00,
                "profit_ratio": float(holding.profit_ratio) if holding.profit_ratio else 0.00,
            }

            result_holdings.append(holding_data)

            if holding.current_value:
                total_value += holding.current_value
            if holding.profit_loss:
                total_profit += holding.profit_loss

        # 构建友好的返回消息
        sign = "+" if total_profit >= 0 else ""
        product_names = "、".join(item["product_name"] for item in result_holdings)
        message = (
            f"您持有{len(holdings_list)}个产品：{product_names}；"
            f"总市值{float(total_value):.2f}元，"
            f"总盈亏{sign}{float(total_profit):.2f}元"
        )

        return {
            "success": True,
            "holdings": result_holdings,
            "total_value": float(total_value),
            "total_profit": float(total_profit),
            "message": message
        }

    def _get_total_asset(self, customer_id: int) -> dict:
        """查询总资产

        Returns:
            {
                "success": True,
                "total_value": 10500.00,
                "message": "您的总资产为10500.00元"
            }
        """
        total_value = HoldingsModel.get_total_asset(customer_id)

        return {
            "success": True,
            "total_value": float(total_value),
            "message": f"您的总资产为{float(total_value):.2f}元"
        }
