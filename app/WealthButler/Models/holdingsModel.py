from app.Base.Repository.base.baseDBModel import BaseDBModel
from typing import Optional, ClassVar
from datetime import datetime
from decimal import Decimal


class HoldingsModel(BaseDBModel):
    """
    持仓表 Model

    职责：
    - 管理客户产品持仓数据（份额、成本、市值、盈亏）
    - 提供持仓查询和统计方法

    关联表：
    - fin_product: 产品信息
    - base_user: 客户信息

    主要字段：
    - customer_id: 客户ID
    - product_id: 产品ID
    - shares: 持有份额
    - cost_amount: 累计成本金额
    - current_value: 当前市值
    - profit_loss: 浮动盈亏
    - profit_ratio: 盈亏比例
    """

    table_alias: ClassVar[str] = "fin_holdings"

    create_table_sql: ClassVar[str] = f"""
    CREATE TABLE `fin_holdings` (
      `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
      `customer_id` INT NOT NULL COMMENT '客户ID',
      `product_id` INT NOT NULL COMMENT '产品ID',
      `shares` DECIMAL(14,4) NOT NULL DEFAULT 0 COMMENT '持有份额',
      `cost_amount` DECIMAL(14,2) COMMENT '累计成本金额',
      `current_value` DECIMAL(14,2) COMMENT '当前市值',
      `profit_loss` DECIMAL(14,2) COMMENT '浮动盈亏',
      `profit_ratio` DECIMAL(6,4) COMMENT '盈亏比例',
      `purchase_date` DATETIME COMMENT '首次购买日期',
      `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
      `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
      `deleted_at` DATETIME COMMENT '软删除时间',
      PRIMARY KEY (`id`),
      UNIQUE KEY `uk_customer_product` (`customer_id`, `product_id`),
      KEY `idx_customer_id` (`customer_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='持仓表';
    """

    # Pydantic字段定义
    id: Optional[int] = None
    customer_id: int
    product_id: int
    shares: Decimal = Decimal("0")
    cost_amount: Optional[Decimal] = None
    current_value: Optional[Decimal] = None
    profit_loss: Optional[Decimal] = None
    profit_ratio: Optional[Decimal] = None
    purchase_date: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    @classmethod
    def find_by_customer_id(cls, customer_id: int) -> list['HoldingsModel']:
        """
        根据客户ID查询所有持仓（排除软删除记录）

        Args:
            customer_id: 客户ID

        Returns:
            list[HoldingsModel]: 持仓列表
        """
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"SELECT * FROM {cls.table_alias} WHERE customer_id = %s AND shares > 0 AND deleted_at IS NULL"
        results = db.execute(sql, (customer_id,))
        return [cls(**row) for row in results]

    @classmethod
    def find_by_customer_and_product(cls, customer_id: int, product_id: int) -> Optional['HoldingsModel']:
        """
        根据客户ID和产品ID查询持仓

        Args:
            customer_id: 客户ID
            product_id: 产品ID

        Returns:
            Optional[HoldingsModel]: 持仓记录，不存在则返回None
        """
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return None
        sql = f"SELECT * FROM {cls.table_alias} WHERE customer_id = %s AND product_id = %s"
        results = db.execute(sql, (customer_id, product_id))
        return cls(**results[0]) if results else None

    @classmethod
    def get_total_asset(cls, customer_id: int) -> Decimal:
        """
        计算客户总资产（支持FM-05熔断规则）

        Args:
            customer_id: 客户ID

        Returns:
            Decimal: 总资产金额
        """
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return Decimal("0")
        sql = f"SELECT SUM(current_value) as total FROM {cls.table_alias} WHERE customer_id = %s"
        results = db.execute(sql, (customer_id,))
        return results[0]['total'] if results and results[0]['total'] else Decimal("0")
