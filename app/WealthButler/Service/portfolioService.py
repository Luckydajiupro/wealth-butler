"""资产配置服务层

职责：
- 基于现代投资组合理论（MPT）的资产配置建议
- 简化版实现，适用于4天工期

依据：
- 需求文档 §4.2 P1任务 - portfolioService.py（MPT算法）
- 注：完整MPT需要历史收益率、协方差矩阵等数据，此处提供简化版
"""
from typing import Dict, List, Optional
import logging
from decimal import Decimal

from app.WealthButler.Models.holdingsModel import HoldingsModel
from app.WealthButler.Models.productModel import ProductModel
from app.WealthButler.Service.productService import ProductService

logger = logging.getLogger(__name__)


class PortfolioService:
    """资产配置服务（简化版）"""

    # 风险等级对应的标准配置建议
    STANDARD_ALLOCATION = {
        "C1": {  # 保守型
            "R1": 0.70,  # 低风险70%
            "R2": 0.30,  # 中低风险30%
            "R3": 0.00,
            "R4": 0.00,
            "R5": 0.00
        },
        "C2": {  # 稳健型
            "R1": 0.40,
            "R2": 0.40,
            "R3": 0.20,
            "R4": 0.00,
            "R5": 0.00
        },
        "C3": {  # 平衡型
            "R1": 0.20,
            "R2": 0.30,
            "R3": 0.40,
            "R4": 0.10,
            "R5": 0.00
        },
        "C4": {  # 进取型
            "R1": 0.10,
            "R2": 0.20,
            "R3": 0.30,
            "R4": 0.30,
            "R5": 0.10
        },
        "C5": {  # 激进型
            "R1": 0.05,
            "R2": 0.10,
            "R3": 0.25,
            "R4": 0.40,
            "R5": 0.20
        }
    }

    @classmethod
    def get_allocation_suggestion(
        cls,
        customer_id: int,
        customer_risk_level: str,
        target_amount: Decimal
    ) -> Dict:
        """获取资产配置建议

        Args:
            customer_id: 客户ID
            customer_risk_level: 客户风险等级（C1-C5）
            target_amount: 目标投资金额

        Returns:
            Dict: {
                "allocation": {  # 配置比例
                    "R1": {"ratio": 0.40, "amount": 40000},
                    "R2": {"ratio": 0.40, "amount": 40000},
                    ...
                },
                "current_allocation": {  # 当前配置
                    "R1": {"ratio": 0.50, "amount": 50000},
                    ...
                },
                "suggestions": [  # 调整建议
                    "建议增加R2类产品配置...",
                    "建议减少R1类产品配置..."
                ],
                "recommended_products": [  # 推荐产品
                    {"product_id": 1, "product_name": "...", "amount": 20000},
                    ...
                ]
            }
        """
        try:
            # 1. 获取标准配置比例
            standard_allocation = cls.STANDARD_ALLOCATION.get(customer_risk_level, cls.STANDARD_ALLOCATION["C1"])

            # 2. 计算各风险等级的目标金额
            target_allocation = {}
            for risk_level, ratio in standard_allocation.items():
                if ratio > 0:
                    target_allocation[risk_level] = {
                        "ratio": ratio,
                        "amount": float(target_amount * Decimal(str(ratio)))
                    }

            # 3. 获取客户当前持仓配置
            current_allocation = cls._analyze_current_allocation(customer_id)

            # 4. 生成调整建议
            suggestions = cls._generate_adjustment_suggestions(
                current_allocation,
                target_allocation,
                customer_risk_level
            )

            # 5. 推荐具体产品
            recommended_products = cls._recommend_products(
                target_allocation,
                customer_risk_level
            )

            return {
                "allocation": target_allocation,
                "current_allocation": current_allocation,
                "suggestions": suggestions,
                "recommended_products": recommended_products
            }

        except Exception as e:
            logger.error(f"生成资产配置建议失败: {e}", exc_info=True)
            return {
                "allocation": {},
                "current_allocation": {},
                "suggestions": ["系统错误，无法生成配置建议"],
                "recommended_products": []
            }

    @classmethod
    def _analyze_current_allocation(cls, customer_id: int) -> Dict:
        """分析客户当前资产配置

        Returns:
            Dict: {
                "R1": {"ratio": 0.50, "amount": 50000},
                "R2": {"ratio": 0.30, "amount": 30000},
                ...
            }
        """
        try:
            holdings = HoldingsModel.find_by_customer_id(customer_id)
            if not holdings:
                return {}

            # 按风险等级汇总
            risk_level_amounts = {}
            total_amount = Decimal("0")

            for holding in holdings:
                product = ProductService.get_product_by_id(holding.product_id)
                if not product:
                    continue

                risk_level = product.risk_level
                amount = holding.current_value or Decimal("0")

                if risk_level not in risk_level_amounts:
                    risk_level_amounts[risk_level] = Decimal("0")

                risk_level_amounts[risk_level] += amount
                total_amount += amount

            # 计算比例
            allocation = {}
            if total_amount > 0:
                for risk_level, amount in risk_level_amounts.items():
                    ratio = float(amount / total_amount)
                    allocation[risk_level] = {
                        "ratio": round(ratio, 2),
                        "amount": float(amount)
                    }

            return allocation

        except Exception as e:
            logger.error(f"分析当前配置失败: {e}", exc_info=True)
            return {}

    @classmethod
    def _generate_adjustment_suggestions(
        cls,
        current: Dict,
        target: Dict,
        customer_risk_level: str
    ) -> List[str]:
        """生成调整建议"""
        suggestions = []

        try:
            # 比较当前配置与目标配置
            all_risk_levels = set(current.keys()) | set(target.keys())

            for risk_level in sorted(all_risk_levels):
                current_ratio = current.get(risk_level, {}).get("ratio", 0)
                target_ratio = target.get(risk_level, {}).get("ratio", 0)

                diff = target_ratio - current_ratio

                if abs(diff) > 0.05:  # 差异大于5%才提示
                    if diff > 0:
                        suggestions.append(
                            f"建议增加{risk_level}类产品配置，当前{current_ratio*100:.0f}%，建议{target_ratio*100:.0f}%"
                        )
                    else:
                        suggestions.append(
                            f"建议减少{risk_level}类产品配置，当前{current_ratio*100:.0f}%，建议{target_ratio*100:.0f}%"
                        )

            if not suggestions:
                suggestions.append(f"当前资产配置符合{customer_risk_level}风险等级标准，无需大幅调整")

            # 添加分散化建议
            if len(current) < 3:
                suggestions.append("建议增加产品种类，提高组合分散度")

        except Exception as e:
            logger.error(f"生成调整建议失败: {e}", exc_info=True)
            suggestions.append("无法生成调整建议")

        return suggestions

    @classmethod
    def _recommend_products(
        cls,
        target_allocation: Dict,
        customer_risk_level: str
    ) -> List[Dict]:
        """推荐具体产品"""
        recommended = []

        try:
            for risk_level, allocation_info in target_allocation.items():
                target_amount = allocation_info["amount"]

                if target_amount < 1000:  # 金额太小不推荐
                    continue

                # 查询该风险等级的产品
                products = ProductService.get_products_by_risk_level(risk_level, limit=3)

                for product in products[:2]:  # 每个风险等级推荐2个产品
                    recommended.append({
                        "product_id": product.id,
                        "product_code": product.product_code,
                        "product_name": product.product_name,
                        "product_type": product.product_type,
                        "risk_level": product.risk_level,
                        "suggested_amount": target_amount / 2,  # 平均分配
                        "min_investment": float(product.min_investment) if product.min_investment else 0
                    })

        except Exception as e:
            logger.error(f"推荐产品失败: {e}", exc_info=True)

        return recommended

    @classmethod
    def calculate_portfolio_metrics(cls, customer_id: int) -> Dict:
        """计算投资组合指标（简化版）

        Returns:
            Dict: {
                "total_value": 总市值,
                "total_cost": 总成本,
                "profit": 总收益,
                "profit_ratio": 收益率,
                "risk_score": 风险评分（0-100）
            }
        """
        try:
            holdings = HoldingsModel.find_by_customer_id(customer_id)
            if not holdings:
                return {
                    "total_value": 0,
                    "total_cost": 0,
                    "profit": 0,
                    "profit_ratio": 0,
                    "risk_score": 0
                }

            total_value = Decimal("0")
            total_cost = Decimal("0")
            risk_weights = []

            for holding in holdings:
                value = holding.current_value or Decimal("0")
                cost = holding.cost or Decimal("0")

                total_value += value
                total_cost += cost

                # 获取产品风险等级
                product = ProductService.get_product_by_id(holding.product_id)
                if product and value > 0:
                    risk_level_score = {"R1": 10, "R2": 30, "R3": 50, "R4": 70, "R5": 90}.get(product.risk_level, 50)
                    weight = float(value / total_value) if total_value > 0 else 0
                    risk_weights.append((risk_level_score, weight))

            profit = total_value - total_cost
            profit_ratio = float(profit / total_cost) if total_cost > 0 else 0

            # 计算加权风险评分
            risk_score = sum(score * weight for score, weight in risk_weights) if risk_weights else 0

            return {
                "total_value": float(total_value),
                "total_cost": float(total_cost),
                "profit": float(profit),
                "profit_ratio": round(profit_ratio * 100, 2),
                "risk_score": round(risk_score, 1)
            }

        except Exception as e:
            logger.error(f"计算组合指标失败: {e}", exc_info=True)
            return {
                "total_value": 0,
                "total_cost": 0,
                "profit": 0,
                "profit_ratio": 0,
                "risk_score": 0
            }
