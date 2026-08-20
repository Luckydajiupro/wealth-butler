"""Persisted risk-rule configuration snapshots."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, ClassVar, Optional

from pydantic import field_validator

from app.Base.Repository.base.baseDBModel import BaseDBModel


class RiskRuleConfigModel(BaseDBModel):
    """Durable editable metadata for built-in and draft risk rules.

    Executable ``check_func`` objects remain code-owned.  This table stores only
    auditable configuration and never evaluates database-provided code.
    """

    table_alias: ClassVar[str] = "fin_risk_rule_config"
    create_table_sql: ClassVar[str] = """
    CREATE TABLE `fin_risk_rule_config` (
      `id` BIGINT NOT NULL AUTO_INCREMENT,
      `rule_id` VARCHAR(32) NOT NULL,
      `rule_name` VARCHAR(200) NOT NULL,
      `trigger_scope` VARCHAR(20) NOT NULL,
      `risk_level` VARCHAR(20) NOT NULL,
      `weight_tier` DECIMAL(8,4) NOT NULL,
      `priority` INT NOT NULL,
      `thresholds` JSON NULL,
      `source_tables` JSON NULL,
      `source_fields` JSON NULL,
      `rule_version` VARCHAR(32) NOT NULL,
      `enabled` TINYINT(1) NOT NULL DEFAULT 1,
      `updated_by` INT NOT NULL,
      `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      PRIMARY KEY (`id`),
      UNIQUE KEY `uk_risk_rule_config_rule_id` (`rule_id`),
      KEY `idx_risk_rule_config_updated_at` (`updated_at`),
      KEY `idx_risk_rule_config_updated_by` (`updated_by`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='可审计风险规则配置快照';
    """

    id: Optional[int] = None
    rule_id: str
    rule_name: str
    trigger_scope: str
    risk_level: str
    weight_tier: float
    priority: int
    thresholds: dict[str, Any]
    source_tables: list[str]
    source_fields: list[str]
    rule_version: str
    enabled: bool = True
    updated_by: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("thresholds", mode="before")
    @classmethod
    def parse_json_object(cls, value):
        if value is None:
            return {}
        if isinstance(value, str):
            return json.loads(value)
        return value

    @field_validator("source_tables", "source_fields", mode="before")
    @classmethod
    def parse_json_lists(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return json.loads(value)
        return value

    @classmethod
    def load_all(cls) -> list["RiskRuleConfigModel"]:
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            raise RuntimeError("风险规则配置数据库连接不可用")
        rows = db.execute(
            f"SELECT * FROM `{cls.table_alias}` ORDER BY `priority`, `rule_id`",
            operation_type="query",
        )
        return [cls(**row) for row in (rows or [])]

    @classmethod
    def upsert_snapshot(cls, snapshot: dict[str, Any]) -> None:
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            raise RuntimeError("风险规则配置数据库连接不可用")
        json_value = lambda value: json.dumps(value, ensure_ascii=False, default=str)
        db.execute(
            f"INSERT INTO `{cls.table_alias}` "
            "(`rule_id`,`rule_name`,`trigger_scope`,`risk_level`,`weight_tier`,`priority`,"
            "`thresholds`,`source_tables`,`source_fields`,`rule_version`,`enabled`,`updated_by`) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE `rule_name`=VALUES(`rule_name`),"
            "`trigger_scope`=VALUES(`trigger_scope`),`risk_level`=VALUES(`risk_level`),"
            "`weight_tier`=VALUES(`weight_tier`),`priority`=VALUES(`priority`),"
            "`thresholds`=VALUES(`thresholds`),`source_tables`=VALUES(`source_tables`),"
            "`source_fields`=VALUES(`source_fields`),`rule_version`=VALUES(`rule_version`),"
            "`enabled`=VALUES(`enabled`),`updated_by`=VALUES(`updated_by`),"
            "`updated_at`=CURRENT_TIMESTAMP",
            (
                snapshot["rule_id"], snapshot["rule_name"], snapshot["trigger_scope"],
                snapshot["risk_level"], snapshot["weight_tier"], snapshot["priority"],
                json_value(snapshot.get("thresholds", {})),
                json_value(snapshot.get("source_tables", [])),
                json_value(snapshot.get("source_fields", [])),
                snapshot["rule_version"], bool(snapshot["enabled"]), snapshot["updated_by"],
            ),
            operation_type="insert",
        )


__all__ = ["RiskRuleConfigModel"]
