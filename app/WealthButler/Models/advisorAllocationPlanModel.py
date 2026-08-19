from datetime import datetime
from typing import ClassVar, Optional

from pydantic import Field, field_validator

from app.Base.Repository.base.baseDBModel import BaseDBModel


class AdvisorAllocationPlanModel(BaseDBModel):
    """Persisted, read-only advisor allocation proposal shared across roles."""

    table_alias: ClassVar[str] = "fin_advisor_allocation_plan"
    create_table_sql: ClassVar[str] = f"""
    CREATE TABLE `{table_alias}` (
      `id` BIGINT NOT NULL AUTO_INCREMENT,
      `customer_id` INT NOT NULL,
      `advisor_id` INT NOT NULL,
      `risk_level` VARCHAR(8) NULL,
      `products` JSON NOT NULL,
      `disclaimer` VARCHAR(500) NULL,
      `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (`id`),
      KEY `idx_customer_created` (`customer_id`, `created_at`),
      KEY `idx_advisor_id` (`advisor_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='理财顾问资产配置方案记录';
    """

    id: Optional[int] = None
    customer_id: int
    advisor_id: int
    risk_level: Optional[str] = None
    products: list = Field(default_factory=list)
    disclaimer: Optional[str] = None
    created_at: Optional[datetime] = None

    @field_validator("products", mode="before")
    @classmethod
    def parse_products(cls, value):
        import json

        if value is None or isinstance(value, list):
            return value or []
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return []
            return parsed if isinstance(parsed, list) else []
        return []

    @classmethod
    def find_latest_by_customer_id(cls, customer_id: int):
        return cls.find_one_by(
            customer_id=customer_id,
            order_by="created_at",
            order="DESC",
        )
