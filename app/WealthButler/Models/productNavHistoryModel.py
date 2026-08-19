"""产品日净值历史模型。"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar, Optional

from app.Base.Repository.base.baseDBModel import BaseDBModel


logger = logging.getLogger(__name__)


class ProductNavHistoryModel(BaseDBModel):
    """保存每日产品净值，供真实日收益计算使用。"""

    table_alias: ClassVar[str] = "fin_product_nav_history"
    create_table_sql: ClassVar[str] = """
    CREATE TABLE `fin_product_nav_history` (
      `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
      `product_id` INT NOT NULL COMMENT '产品ID',
      `nav_date` DATE NOT NULL COMMENT '净值日期',
      `nav` DECIMAL(10,4) NOT NULL COMMENT '单位净值',
      `source` VARCHAR(64) NOT NULL DEFAULT 'product_feed' COMMENT '净值数据来源',
      `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
      PRIMARY KEY (`id`),
      UNIQUE KEY `uk_product_nav_date` (`product_id`, `nav_date`),
      KEY `idx_product_nav_date` (`nav_date`, `product_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='产品日净值历史';
    """

    id: Optional[int] = None
    product_id: int
    nav_date: date
    nav: Decimal
    source: str = "product_feed"
    created_at: Optional[datetime] = None

    @classmethod
    def find_latest_before(cls, product_id: int, before_date: date):
        """查询指定日期之前最近一条真实净值。"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return None
        try:
            rows = db.execute(
                f"SELECT * FROM {cls.table_alias} "
                "WHERE product_id = %s AND nav_date < %s "
                "ORDER BY nav_date DESC LIMIT 1",
                (product_id, before_date),
            )
        except Exception as exc:
            logger.warning("查询产品净值历史失败: product_id=%s, error=%s", product_id, exc)
            return None
        return cls(**rows[0]) if rows else None

    @classmethod
    def find_recent_for_products(cls, product_ids: list[int], days: int = 90) -> dict[int, list[dict]]:
        """Batch-load recent NAV rows for deterministic advisor return scoring."""
        normalized_ids = sorted({int(product_id) for product_id in product_ids if int(product_id) > 0})
        if not normalized_ids:
            return {}
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return {}
        placeholders = ", ".join(["%s"] * len(normalized_ids))
        try:
            rows = db.execute(
                f"SELECT product_id, nav_date, nav FROM {cls.table_alias} "
                f"WHERE product_id IN ({placeholders}) "
                "AND nav_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY) "
                "ORDER BY product_id, nav_date",
                tuple(normalized_ids) + (max(1, min(int(days), 365)),),
            )
        except Exception as exc:
            logger.warning("批量查询产品净值历史失败: %s", exc)
            return {}
        grouped: dict[int, list[dict]] = {}
        for row in rows or []:
            grouped.setdefault(int(row["product_id"]), []).append(row)
        return grouped
