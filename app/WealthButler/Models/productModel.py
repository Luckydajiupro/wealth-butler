from app.Base.Repository.base.baseDBModel import BaseDBModel
from typing import Optional, ClassVar
from datetime import datetime, date
from decimal import Decimal


class ProductModel(BaseDBModel):
    """
    理财产品表 Model

    职责：
    - 管理理财产品基础信息（编码、类型、风险等级、净值等）
    - 提供产品查询和筛选方法

    产品分类：
    - 公募基金、私募基金、银行理财、保险、信托、结构性存款

    风险等级：
    - R1（谨慎型）、R2（稳健型）、R3（平衡型）、R4（进取型）、R5（激进型）

    主要字段：
    - product_code: 产品编码（唯一）
    - product_name: 产品名称
    - product_type: 产品类型
    - risk_level: 风险等级
    - nav: 最新净值
    - min_investment: 起投金额
    """

    table_alias: ClassVar[str] = "fin_product"

    create_table_sql: ClassVar[str] = f"""
    CREATE TABLE `fin_product` (
      `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
      `product_code` VARCHAR(32) NOT NULL COMMENT '产品编码',
      `product_name` VARCHAR(200) NOT NULL COMMENT '产品名称',
      `product_type` ENUM('公募基金','私募基金','银行理财','保险','信托','结构性存款') NOT NULL COMMENT '产品类型',
      `risk_level` ENUM('R1','R2','R3','R4','R5') NOT NULL COMMENT '产品风险等级',
      `min_investment` DECIMAL(14,2) COMMENT '起投金额',
      `redemption_period_days` INT COMMENT '赎回到账周期（天）',
      `nav` DECIMAL(10,4) COMMENT '最新净值',
      `nav_date` DATE COMMENT '净值日期',
      `industry` VARCHAR(50) COMMENT '所属行业',
      `fund_manager` VARCHAR(100) COMMENT '基金经理/管理人',
      `status` ENUM('在售','已下架','封闭期') DEFAULT '在售' COMMENT '产品状态',
      `description` TEXT COMMENT '产品说明',
      `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
      `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
      PRIMARY KEY (`id`),
      UNIQUE KEY `uk_product_code` (`product_code`),
      KEY `idx_product_type` (`product_type`),
      KEY `idx_risk_level` (`risk_level`),
      KEY `idx_status` (`status`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='理财产品表';
    """

    # Pydantic字段定义
    id: Optional[int] = None
    product_code: str
    product_name: str
    product_type: str
    risk_level: Optional[str] = None
    redemption_period_days: Optional[int] = None
    nav: Optional[Decimal] = None
    nav_date: Optional[datetime] = None
    min_investment: Optional[Decimal] = None
    industry: Optional[str] = None
    fund_manager: Optional[str] = None
    status: str = "在售"
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def find_by_product_code(cls, product_code: str) -> Optional['ProductModel']:
        """
        根据产品编码查询

        Args:
            product_code: 产品编码

        Returns:
            Optional[ProductModel]: 产品记录，不存在则返回None
        """
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return None
        sql = f"SELECT * FROM {cls.table_alias} WHERE product_code = %s"
        results = db.execute(sql, (product_code,))
        return cls(**results[0]) if results else None

    @classmethod
    def find_by_type(cls, product_type: str, status: str = "在售") -> list['ProductModel']:
        """
        根据产品类型查询在售产品

        Args:
            product_type: 产品类型
            status: 产品状态，默认"在售"

        Returns:
            list[ProductModel]: 产品列表
        """
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"SELECT * FROM {cls.table_alias} WHERE product_type = %s AND status = %s"
        results = db.execute(sql, (product_type, status))
        return [cls(**row) for row in results]

    @classmethod
    def find_by_risk_level(cls, risk_level: str, status: str = "在售") -> list['ProductModel']:
        """
        根据风险等级查询产品

        Args:
            risk_level: 风险等级（R1-R5）
            status: 产品状态，默认"在售"

        Returns:
            list[ProductModel]: 产品列表
        """
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"SELECT * FROM {cls.table_alias} WHERE risk_level = %s AND status = %s"
        results = db.execute(sql, (risk_level, status))
        return [cls(**row) for row in results]
