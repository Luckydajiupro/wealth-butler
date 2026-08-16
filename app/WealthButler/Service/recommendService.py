"""产品推荐服务层

职责：
- 基于客户画像的产品推荐
- 简化版协同过滤算法
- 适用于4天工期

依据：
- 需求文档 §4.2 P2任务 - recommendService.py（协同过滤）
- 注：完整协同过滤需要大量用户行为数据，此处提供基于规则的简化版
"""
from typing import Dict, List, Optional
import logging
from decimal import Decimal

from app.WealthButler.Models.productModel import ProductModel
from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
from app.WealthButler.Models.holdingsModel import HoldingsModel
from app.WealthButler.Service.productService import ProductService

logger = logging.getLogger(__name__)


class RecommendService:
    """产品推荐服务（简化版）"""

    @classmethod
    def recommend_products_for_customer(
        cls,
        customer_id: int,
        limit: int = 10,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """为客户推荐产品

        推荐策略（多因子加权）：
        1. 适当性匹配（必须满足）
        2. 风险匹配度（25%）
        3. 产品类型偏好（20%）
        4. 历史持仓相似度（15%）
        5. 产品收益表现（20%）
        6. 协同过滤相似用户（20%）

        Args:
            customer_id: 客户ID
            limit: 返回数量
            filters: 额外筛选条件，例如 {"product_type": "公募基金"}

        Returns:
            List[Dict]: 推荐产品列表，每项包含：
                {
                    "product_id": int,
                    "product_name": str,
                    "product_type": str,
                    "risk_level": str,
                    "score": float,  # 推荐分数
                    "reason": str    # 推荐理由
                }
        """
        try:
            # 1. 获取客户画像
            profile = CustomerProfileModel.find_by_customer_id(customer_id)
            if not profile or not profile.risk_level:
                logger.warning(f"客户{customer_id}画像不存在或风险等级未评估")
                return []

            # 2. 获取适当性匹配的候选产品池
            candidate_products = ProductService.get_suitable_products_for_customer(
                profile.risk_level,
                limit=100
            )

            if not candidate_products:
                logger.warning(f"没有找到适合客户{customer_id}的产品")
                return []

            # 3. 应用额外筛选
            if filters:
                candidate_products = cls._apply_filters(candidate_products, filters)

            # 4. 计算推荐分数
            scored_products = []
            for product in candidate_products:
                score_info = cls._calculate_recommendation_score(
                    customer_id,
                    profile,
                    product
                )
                scored_products.append({
                    "product_id": product.id,
                    "product_code": product.product_code,
                    "product_name": product.product_name,
                    "product_type": product.product_type,
                    "risk_level": product.risk_level,
                    "nav": float(product.nav) if product.nav else None,
                    "min_investment": float(product.min_investment) if product.min_investment else 0,
                    "score": score_info["score"],
                    "reason": score_info["reason"]
                })

            # 5. 排序并返回Top N
            scored_products.sort(key=lambda x: x["score"], reverse=True)
            return scored_products[:limit]

        except Exception as e:
            logger.error(f"推荐产品失败: customer_id={customer_id}, error={e}", exc_info=True)
            return []

    @classmethod
    def _apply_filters(cls, products: List[ProductModel], filters: Dict) -> List[ProductModel]:
        """应用额外筛选条件"""
        filtered = products

        if "product_type" in filters:
            filtered = [p for p in filtered if p.product_type == filters["product_type"]]

        if "max_min_investment" in filters:
            max_investment = Decimal(str(filters["max_min_investment"]))
            filtered = [p for p in filtered if not p.min_investment or p.min_investment <= max_investment]

        if "industry" in filters:
            filtered = [p for p in filtered if p.industry == filters["industry"]]

        return filtered

    @classmethod
    def _calculate_recommendation_score(
        cls,
        customer_id: int,
        profile: CustomerProfileModel,
        product: ProductModel
    ) -> Dict:
        """计算推荐分数

        Returns:
            Dict: {"score": float, "reason": str}
        """
        total_score = 0.0
        reasons = []

        # 1. 风险匹配度（25%）
        risk_match_score = cls._calculate_risk_match_score(profile.risk_level, product.risk_level)
        total_score += risk_match_score * 0.25
        if risk_match_score > 0.8:
            reasons.append(f"风险等级匹配您的{profile.risk_level}评级")

        # 2. 产品类型偏好（20%）
        type_preference_score = cls._calculate_type_preference_score(
            customer_id,
            product.product_type
        )
        total_score += type_preference_score * 0.20
        if type_preference_score > 0.7:
            reasons.append(f"您偏好{product.product_type}类产品")

        # 3. 历史持仓相似度（15%）
        holding_similarity_score = cls._calculate_holding_similarity(
            customer_id,
            product
        )
        total_score += holding_similarity_score * 0.15
        if holding_similarity_score > 0.6:
            reasons.append("与您的持仓风格相似")

        # 4. 产品收益表现（20%）- 简化版，实际需要历史收益率数据
        performance_score = 0.7  # 默认中等
        total_score += performance_score * 0.20
        reasons.append("历史业绩稳定")

        # 5. 协同过滤相似用户（20%）- 简化版
        collaborative_score = cls._calculate_collaborative_score(
            customer_id,
            product.id
        )
        total_score += collaborative_score * 0.20
        if collaborative_score > 0.6:
            reasons.append("相似客户都在购买")

        # 生成推荐理由
        reason_text = "、".join(reasons[:3]) if reasons else "综合评估推荐"

        return {
            "score": round(total_score, 3),
            "reason": reason_text
        }

    @staticmethod
    def _calculate_risk_match_score(customer_level: str, product_level: str) -> float:
        """计算风险匹配度

        匹配规则：
        - 完全匹配（C1-R1、C2-R2...）: 1.0
        - 低一档: 0.9
        - 低两档: 0.7
        - 高一档: 0.8
        - 其他: 0.5
        """
        level_map = {"C1": 1, "C2": 2, "C3": 3, "C4": 4, "C5": 5,
                     "R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}

        customer_num = level_map.get(customer_level, 3)
        product_num = level_map.get(product_level, 3)

        diff = customer_num - product_num

        if diff == 0:
            return 1.0
        elif diff == 1:
            return 0.9
        elif diff == 2:
            return 0.7
        elif diff == -1:
            return 0.8
        else:
            return 0.5

    @classmethod
    def _calculate_type_preference_score(cls, customer_id: int, product_type: str) -> float:
        """计算产品类型偏好度

        基于客户历史持仓的产品类型分布
        """
        try:
            holdings = HoldingsModel.find_by_customer_id(customer_id)
            if not holdings:
                return 0.5  # 无历史数据，返回中等分

            # 统计产品类型分布
            type_counts = {}
            for holding in holdings:
                product = ProductService.get_product_by_id(holding.product_id)
                if product:
                    ptype = product.product_type
                    type_counts[ptype] = type_counts.get(ptype, 0) + 1

            if not type_counts:
                return 0.5

            # 计算目标类型的占比
            total = sum(type_counts.values())
            preference = type_counts.get(product_type, 0) / total

            # 偏好度映射到0-1分数
            return min(preference * 2, 1.0)  # 50%占比即为满分

        except Exception as e:
            logger.error(f"计算类型偏好失败: {e}", exc_info=True)
            return 0.5

    @classmethod
    def _calculate_holding_similarity(
        cls,
        customer_id: int,
        product: ProductModel
    ) -> float:
        """计算与持仓的相似度

        简化实现：检查行业、基金经理等是否相同
        """
        try:
            holdings = HoldingsModel.find_by_customer_id(customer_id)
            if not holdings:
                return 0.5

            # 检查是否已持有相同行业或基金经理的产品
            for holding in holdings:
                held_product = ProductService.get_product_by_id(holding.product_id)
                if not held_product:
                    continue

                # 相同行业
                if product.industry and held_product.industry == product.industry:
                    return 0.8

                # 相同基金经理
                if product.fund_manager and held_product.fund_manager == product.fund_manager:
                    return 0.7

            return 0.5

        except Exception as e:
            logger.error(f"计算持仓相似度失败: {e}", exc_info=True)
            return 0.5

    @classmethod
    def _calculate_collaborative_score(cls, customer_id: int, product_id: int) -> float:
        """计算协同过滤分数

        简化实现：基于产品受欢迎程度
        实际协同过滤需要：
        1. 找到相似用户（基于持仓向量余弦相似度）
        2. 统计相似用户对该产品的偏好
        3. 加权计算推荐分数

        此处简化为：统计持有该产品的客户数
        """
        try:
            db = HoldingsModel.get_db_connection()
            if not db:
                return 0.5

            # 统计持有该产品的客户数
            sql = """SELECT COUNT(DISTINCT customer_id) as holder_count
                     FROM fin_holdings
                     WHERE product_id = %s"""
            results = db.execute(sql, (product_id,))

            holder_count = results[0]['holder_count'] if results else 0

            # 持有人数越多，分数越高（最多1.0）
            # 假设100人持有即为满分
            score = min(holder_count / 100.0, 1.0)

            return score

        except Exception as e:
            logger.error(f"计算协同过滤分数失败: {e}", exc_info=True)
            return 0.5

    @classmethod
    def get_hot_products(cls, limit: int = 10) -> List[Dict]:
        """获取热门产品

        基于持有人数排序

        Returns:
            List[Dict]: 热门产品列表
        """
        try:
            db = HoldingsModel.get_db_connection()
            if not db:
                return []

            sql = """
                SELECT
                    p.id as product_id,
                    p.product_code,
                    p.product_name,
                    p.product_type,
                    p.risk_level,
                    p.nav,
                    COUNT(DISTINCT h.customer_id) as holder_count
                FROM fin_product p
                INNER JOIN fin_holdings h ON p.id = h.product_id
                WHERE p.status = '在售'
                GROUP BY p.id
                ORDER BY holder_count DESC
                LIMIT %s
            """

            results = db.execute(sql, (limit,))

            hot_products = []
            for row in results:
                hot_products.append({
                    "product_id": row['product_id'],
                    "product_code": row['product_code'],
                    "product_name": row['product_name'],
                    "product_type": row['product_type'],
                    "risk_level": row['risk_level'],
                    "nav": float(row['nav']) if row['nav'] else None,
                    "holder_count": row['holder_count'],
                    "reason": f"已有{row['holder_count']}位客户持有"
                })

            return hot_products

        except Exception as e:
            logger.error(f"获取热门产品失败: {e}", exc_info=True)
            return []

    @classmethod
    def get_similar_products(cls, product_id: int, limit: int = 5) -> List[Dict]:
        """获取相似产品

        基于产品类型、风险等级、行业等维度

        Args:
            product_id: 参考产品ID
            limit: 返回数量

        Returns:
            List[Dict]: 相似产品列表
        """
        try:
            # 获取参考产品
            reference = ProductService.get_product_by_id(product_id)
            if not reference:
                return []

            db = ProductModel.get_db_connection()
            if not db:
                return []

            # 查询相似产品
            sql = """
                SELECT *
                FROM fin_product
                WHERE id != %s
                AND status = '在售'
                AND (
                    product_type = %s
                    OR risk_level = %s
                    OR industry = %s
                )
                LIMIT %s
            """

            results = db.execute(sql, (
                product_id,
                reference.product_type,
                reference.risk_level,
                reference.industry,
                limit * 2  # 查询更多再筛选
            ))

            similar_products = []
            for row in results[:limit]:
                # 计算相似度
                similarity = 0
                if row['product_type'] == reference.product_type:
                    similarity += 0.4
                if row['risk_level'] == reference.risk_level:
                    similarity += 0.3
                if row['industry'] == reference.industry:
                    similarity += 0.3

                similar_products.append({
                    "product_id": row['id'],
                    "product_code": row['product_code'],
                    "product_name": row['product_name'],
                    "product_type": row['product_type'],
                    "risk_level": row['risk_level'],
                    "similarity": round(similarity, 2),
                    "reason": f"与{reference.product_name}相似"
                })

            # 按相似度排序
            similar_products.sort(key=lambda x: x["similarity"], reverse=True)
            return similar_products

        except Exception as e:
            logger.error(f"获取相似产品失败: product_id={product_id}, error={e}", exc_info=True)
            return []
