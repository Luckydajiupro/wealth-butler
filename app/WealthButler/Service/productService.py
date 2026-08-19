"""产品服务层

职责：
- 产品基础CRUD
- 按风险等级、类型筛选产品
- 产品搜索

依据：
- 需求文档 §6.1 数据实体清单
- ProductModel已提供基础查询方法，此Service封装业务逻辑
"""
from typing import List, Optional, Dict
import logging
from decimal import Decimal

from app.WealthButler.Models.productModel import ProductModel

logger = logging.getLogger(__name__)


class ProductService:
    """产品服务"""

    @classmethod
    def get_product_by_id(cls, product_id: int) -> Optional[ProductModel]:
        """根据产品ID查询

        Args:
            product_id: 产品ID

        Returns:
            Optional[ProductModel]: 产品记录
        """
        try:
            return ProductModel.get_by_id(product_id)
        except Exception as e:
            logger.error(f"查询产品失败: product_id={product_id}, error={e}", exc_info=True)
            return None

    @classmethod
    def get_product_by_code(cls, product_code: str) -> Optional[ProductModel]:
        """根据产品编码查询

        Args:
            product_code: 产品编码

        Returns:
            Optional[ProductModel]: 产品记录
        """
        try:
            return ProductModel.find_by_product_code(product_code)
        except Exception as e:
            logger.error(f"查询产品失败: product_code={product_code}, error={e}", exc_info=True)
            return None

    @classmethod
    def get_products_by_risk_level(
        cls,
        risk_level: str,
        status: str = "在售",
        limit: int = 50
    ) -> List[ProductModel]:
        """根据风险等级查询产品

        Args:
            risk_level: 风险等级（R1-R5）
            status: 产品状态，默认"在售"
            limit: 返回数量限制

        Returns:
            List[ProductModel]: 产品列表
        """
        try:
            products = ProductModel.find_by_risk_level(risk_level, status)
            return products[:limit] if products else []
        except Exception as e:
            logger.error(f"按风险等级查询产品失败: risk_level={risk_level}, error={e}", exc_info=True)
            return []

    @classmethod
    def get_products_by_type(
        cls,
        product_type: str,
        status: str = "在售",
        limit: int = 50
    ) -> List[ProductModel]:
        """根据产品类型查询

        Args:
            product_type: 产品类型（公募基金/私募基金/银行理财/保险/信托/结构性存款）
            status: 产品状态，默认"在售"
            limit: 返回数量限制

        Returns:
            List[ProductModel]: 产品列表
        """
        try:
            products = ProductModel.find_by_type(product_type, status)
            return products[:limit] if products else []
        except Exception as e:
            logger.error(f"按类型查询产品失败: product_type={product_type}, error={e}", exc_info=True)
            return []

    @classmethod
    def search_products(
        cls,
        keyword: Optional[str] = None,
        filters: Optional[Dict] = None,
        limit: int = 50
    ) -> List[ProductModel]:
        """搜索产品

        Args:
            keyword: 关键词（搜索产品名称）
            filters: 筛选条件，例如：
                {
                    "product_type": "公募基金",
                    "risk_level": "R3",
                    "min_investment_max": 10000  # 起投金额≤10000
                }
            limit: 返回数量限制

        Returns:
            List[ProductModel]: 产品列表
        """
        try:
            db = ProductModel.get_db_connection()
            if not db:
                return []

            # 构建SQL
            where_clauses = ["status = '在售'"]
            params = []

            # 关键词搜索
            if keyword:
                where_clauses.append("(product_name LIKE %s OR product_code LIKE %s)")
                keyword_pattern = f"%{keyword}%"
                params.extend([keyword_pattern, keyword_pattern])

            # 筛选条件
            if filters:
                if "product_type" in filters:
                    where_clauses.append("product_type = %s")
                    params.append(filters["product_type"])

                if "risk_level" in filters:
                    where_clauses.append("risk_level = %s")
                    params.append(filters["risk_level"])

                if "min_investment_max" in filters:
                    where_clauses.append("min_investment <= %s")
                    params.append(filters["min_investment_max"])

                if "industry" in filters:
                    where_clauses.append("industry = %s")
                    params.append(filters["industry"])

            where_sql = " AND ".join(where_clauses)
            sql = f"""SELECT * FROM fin_product
                      WHERE {where_sql}
                      ORDER BY nav_date DESC
                      LIMIT %s"""
            params.append(limit)

            results = db.execute(sql, tuple(params))
            return [ProductModel(**row) for row in results] if results else []

        except Exception as e:
            logger.error(f"搜索产品失败: keyword={keyword}, filters={filters}, error={e}", exc_info=True)
            return []

    @classmethod
    def get_suitable_products_for_customer(
        cls,
        customer_risk_level: str,
        limit: int = 20
    ) -> List[ProductModel]:
        """获取适合客户风险等级的产品

        根据适当性匹配规则筛选产品：
        - C1 → R1-R2
        - C2 → R1-R3
        - C3 → R1-R3 (R4需揭示书)
        - C4 → R1-R4 (R5需揭示书)
        - C5 → R1-R5

        Args:
            customer_risk_level: 客户风险等级（C1-C5）
            limit: 返回数量限制

        Returns:
            List[ProductModel]: 适合的产品列表
        """
        try:
            # 适当性映射
            suitability_map = {
                "C1": ["R1", "R2"],
                "C2": ["R1", "R2", "R3"],
                "C3": ["R1", "R2", "R3"],  # R4需揭示书，暂不推荐
                "C4": ["R1", "R2", "R3", "R4"],  # R5需揭示书，暂不推荐
                "C5": ["R1", "R2", "R3", "R4", "R5"]
            }

            allowed_levels = suitability_map.get(customer_risk_level, ["R1"])

            db = ProductModel.get_db_connection()
            if not db:
                return []

            # 查询符合条件的产品
            placeholders = ",".join(["%s"] * len(allowed_levels))
            sql = f"""SELECT * FROM fin_product
                      WHERE status = '在售'
                      AND risk_level IN ({placeholders})
                      ORDER BY nav_date DESC
                      LIMIT %s"""

            params = list(allowed_levels) + [limit]
            results = db.execute(sql, tuple(params))

            return [ProductModel(**row) for row in results] if results else []

        except Exception as e:
            logger.error(f"获取适合产品失败: customer_risk_level={customer_risk_level}, error={e}", exc_info=True)
            return []

    @classmethod
    def get_product_statistics(cls) -> Dict:
        """获取产品统计数据

        Returns:
            Dict: 统计信息，例如：
                {
                    "total": 100,
                    "by_type": {"公募基金": 50, "银行理财": 30, ...},
                    "by_risk": {"R1": 20, "R2": 30, ...}
                }
        """
        try:
            db = ProductModel.get_db_connection()
            if not db:
                return {}

            # 总数
            total_result = db.execute("SELECT COUNT(*) as cnt FROM fin_product WHERE status='在售'")
            total = total_result[0]['cnt'] if total_result else 0

            # 按类型统计
            type_result = db.execute("""
                SELECT product_type, COUNT(*) as cnt
                FROM fin_product
                WHERE status='在售'
                GROUP BY product_type
            """)
            by_type = {row['product_type']: row['cnt'] for row in type_result} if type_result else {}

            # 按风险等级统计
            risk_result = db.execute("""
                SELECT risk_level, COUNT(*) as cnt
                FROM fin_product
                WHERE status='在售'
                GROUP BY risk_level
            """)
            by_risk = {row['risk_level']: row['cnt'] for row in risk_result} if risk_result else {}

            return {
                "total": total,
                "by_type": by_type,
                "by_risk": by_risk
            }

        except Exception as e:
            logger.error(f"获取产品统计失败: {e}", exc_info=True)
            return {}

    @classmethod
    def check_product_purchasable(
        cls,
        product_id: int,
        customer_risk_level: str,
        investment_amount: Decimal
    ) -> Dict[str, any]:
        """检查产品是否可购买

        Args:
            product_id: 产品ID
            customer_risk_level: 客户风险等级
            investment_amount: 投资金额

        Returns:
            Dict: {
                "purchasable": bool,
                "reason": str,  # 不可购买的原因
                "warnings": List[str]  # 警告信息
            }
        """
        try:
            product = cls.get_product_by_id(product_id)
            if not product:
                return {
                    "purchasable": False,
                    "reason": "产品不存在",
                    "warnings": []
                }

            if product.status != "在售":
                return {
                    "purchasable": False,
                    "reason": f"产品状态为{product.status}，不可购买",
                    "warnings": []
                }

            # 检查起投金额
            if product.min_investment and investment_amount < product.min_investment:
                return {
                    "purchasable": False,
                    "reason": f"投资金额低于起投门槛{product.min_investment}元",
                    "warnings": []
                }

            # 检查适当性匹配
            from app.WealthButler.Service.riskAssessService import RiskAssessService
            suitability = RiskAssessService.check_suitability(customer_risk_level, product.risk_level)

            if not suitability["matched"]:
                return {
                    "purchasable": False,
                    "reason": suitability["message"],
                    "warnings": []
                }

            warnings = []
            if suitability["action"] == "disclosure":
                warnings.append(suitability["message"])

            return {
                "purchasable": True,
                "reason": "",
                "warnings": warnings
            }

        except Exception as e:
            logger.error(f"检查产品可购买性失败: {e}", exc_info=True)
            return {
                "purchasable": False,
                "reason": "系统错误",
                "warnings": []
            }
