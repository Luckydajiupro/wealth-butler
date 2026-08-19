import json

from pydantic import field_validator

from app.Base.Repository.base.baseDBModel import BaseDBModel
from typing import Optional, ClassVar
from datetime import datetime
from decimal import Decimal


class CustomerProfileModel(BaseDBModel):
    """
    客户画像主表（四维度加权版）
    包含四维度打分、FM熔断标记、中期记忆单元、置信度等字段
    """

    table_alias: ClassVar[str] = "fin_customer_profile"

    create_table_sql: ClassVar[str] = f"""
    CREATE TABLE `fin_customer_profile` (
      `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
      `customer_id` INT NOT NULL COMMENT '客户ID，关联base_user.id',
      `advisor_id` INT COMMENT '负责理财顾问ID，关联base_user.id',
      `risk_level` ENUM('C1','C2','C3','C4','C5') COMMENT '客户风险分级',
      `risk_score` DECIMAL(5,2) COMMENT '综合评分0-100',
      `dimension1_score` DECIMAL(5,2) COMMENT '维度一-基础属性分（满分25）',
      `dimension2_score` DECIMAL(5,2) COMMENT '维度二-投资经验分（满分25）',
      `dimension3_score` DECIMAL(5,2) COMMENT '维度三-风险偏好分（满分30）',
      `dimension4_score` DECIMAL(5,2) COMMENT '维度四-行为异常分（满分20）',
      `fm_flags` JSON COMMENT '命中的硬性熔断标记数组（FM-01~FM-05）',
      `asset_allocation` JSON COMMENT '资产配置画像',
      `product_preference` JSON COMMENT '产品偏好画像',
      `memory_units` JSON COMMENT '中期记忆单元数组',
      `confidence_score` DECIMAL(4,3) COMMENT '画像整体置信度',
      `updated_reason` ENUM('定期','事件','行为','市场','人工触发') COMMENT '本次更新触发原因',
      `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
      `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
      PRIMARY KEY (`id`),
      UNIQUE KEY `uk_customer_id` (`customer_id`),
      KEY `idx_advisor_id` (`advisor_id`),
      KEY `idx_risk_level` (`risk_level`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='客户画像主表';
    """

    # Pydantic字段定义
    id: Optional[int] = None
    customer_id: int
    advisor_id: Optional[int] = None
    risk_level: Optional[str] = None
    risk_score: Optional[Decimal] = None
    dimension1_score: Optional[Decimal] = None
    dimension2_score: Optional[Decimal] = None
    dimension3_score: Optional[Decimal] = None
    dimension4_score: Optional[Decimal] = None
    fm_flags: Optional[list] = None
    asset_allocation: Optional[dict] = None
    product_preference: Optional[dict] = None
    memory_units: Optional[list] = None
    confidence_score: Optional[Decimal] = None
    updated_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator('fm_flags', 'memory_units', mode='before')
    @classmethod
    def parse_json_lists(cls, value):
        """将数据库 JSON 文本恢复为列表。"""
        if value is None or isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return None
            return parsed if isinstance(parsed, list) else None
        return value

    @field_validator('asset_allocation', 'product_preference', mode='before')
    @classmethod
    def parse_json_dicts(cls, value):
        """将数据库 JSON 文本恢复为字典。"""
        if value is None or isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return None
            return parsed if isinstance(parsed, dict) else None
        return value

    @classmethod
    def find_by_customer_id(cls, customer_id: int):
        """根据客户ID查询画像"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return None
        sql = f"SELECT * FROM {cls.table_alias} WHERE customer_id = %s"
        results = db.execute(sql, (customer_id,))
        return cls(**results[0]) if results else None

    @classmethod
    def find_by_risk_level(cls, risk_level: str):
        """根据风险等级查询客户列表"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"SELECT * FROM {cls.table_alias} WHERE risk_level = %s"
        results = db.execute(sql, (risk_level,))
        return [cls(**row) for row in results]
