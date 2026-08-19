"""Phase 4 种子前置补列迁移。

仅补充权威表设计已经定义、但真实库尚缺失的兼容列与索引。默认离线 dry-run；
显式 apply 前逐项查询 information_schema，且校验三张表行数不减少。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.seed_wealthbutler_business_data import _connect


APPLY_CONFIRMATION = "APPLY_PHASE4_SEED_PREREQUISITES"


@dataclass(frozen=True)
class ColumnStep:
    table: str
    column: str
    definition: str


@dataclass(frozen=True)
class IndexStep:
    table: str
    name: str
    definition: str


COLUMNS = (
    ColumnStep("fin_risk_alert", "alert_type", "VARCHAR(10) NULL COMMENT '触发规则编号RW-001~RW-020'"),
    ColumnStep("fin_risk_alert", "alert_level", "ENUM('蓝','黄','红') NULL COMMENT '预警级别'"),
    ColumnStep("fin_risk_alert", "rule_weight_tier", "ENUM('强信号','中信号','弱信号') NULL COMMENT '规则信号强度'"),
    ColumnStep("fin_risk_alert", "transaction_ids", "JSON NULL COMMENT '关联交易流水ID数组'"),
    ColumnStep("fin_risk_alert", "is_repeat", "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否重复触发'"),
    ColumnStep("fin_risk_alert", "repeat_trigger_count", "INT NOT NULL DEFAULT 0 COMMENT '重复触发次数'"),
    ColumnStep("fin_risk_alert", "is_false_positive", "TINYINT(1) NULL COMMENT '误报标记'"),
    ColumnStep("fin_risk_alert", "handle_note", "VARCHAR(500) NULL COMMENT '处理备注'"),
    ColumnStep("fin_risk_alert", "handled_by", "INT NULL COMMENT '处理人ID'"),
    ColumnStep("biz_work_order", "related_alert_id", "BIGINT NULL COMMENT '关联风控预警ID'"),
    ColumnStep("fin_knowledge_meta", "source_file", "VARCHAR(255) NULL COMMENT '原始素材文件名'"),
    ColumnStep("fin_knowledge_meta", "milvus_collection", "VARCHAR(64) NULL COMMENT 'Milvus集合名'"),
    ColumnStep("fin_knowledge_meta", "milvus_pk", "BIGINT NULL COMMENT 'Milvus主键ID'"),
    ColumnStep("fin_knowledge_meta", "minio_object_key", "VARCHAR(255) NULL COMMENT 'MinIO对象Key'"),
    ColumnStep("fin_knowledge_meta", "uploaded_by", "INT NULL COMMENT '上传人ID'"),
)

INDEXES = (
    IndexStep("fin_risk_alert", "idx_alert_type", "KEY `idx_alert_type` (`alert_type`)"),
    IndexStep("fin_risk_alert", "idx_alert_level", "KEY `idx_alert_level` (`alert_level`)"),
    IndexStep("biz_work_order", "idx_related_alert_id", "KEY `idx_related_alert_id` (`related_alert_id`)"),
    IndexStep("fin_knowledge_meta", "idx_milvus_pk", "KEY `idx_milvus_pk` (`milvus_pk`)"),
)

TABLES = tuple(dict.fromkeys(step.table for step in (*COLUMNS, *INDEXES)))


def _exists(cursor: Any, kind: str, table: str, name: str) -> bool:
    source = "COLUMNS" if kind == "column" else "STATISTICS"
    field = "COLUMN_NAME" if kind == "column" else "INDEX_NAME"
    cursor.execute(
        f"SELECT COUNT(*) AS count FROM information_schema.{source} "
        f"WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND {field}=%s", (table, name),
    )
    return bool(cursor.fetchone()["count"])


def _counts(cursor: Any) -> dict[str, int]:
    result = {}
    for table in TABLES:
        cursor.execute(f"SELECT COUNT(*) AS count FROM `{table}`")
        result[table] = int(cursor.fetchone()["count"])
    return result


def execute(connection: Any, *, dry_run: bool) -> dict[str, Any]:
    cursor = connection.cursor()
    applied = []
    before = _counts(cursor)
    try:
        for step in COLUMNS:
            if _exists(cursor, "column", step.table, step.column):
                continue
            applied.append(f"column:{step.table}.{step.column}")
            if not dry_run:
                cursor.execute(f"ALTER TABLE `{step.table}` ADD COLUMN `{step.column}` {step.definition}")
                if not _exists(cursor, "column", step.table, step.column):
                    raise RuntimeError(f"补列校验失败: {step.table}.{step.column}")
        for step in INDEXES:
            if _exists(cursor, "index", step.table, step.name):
                continue
            applied.append(f"index:{step.table}.{step.name}")
            if not dry_run:
                cursor.execute(f"ALTER TABLE `{step.table}` ADD {step.definition}")
                if not _exists(cursor, "index", step.table, step.name):
                    raise RuntimeError(f"索引校验失败: {step.table}.{step.name}")
        after = _counts(cursor)
        if any(after[table] < before[table] for table in TABLES):
            raise RuntimeError("迁移后表行数减少")
        if not dry_run:
            connection.commit()
        return {"mode": "dry-run" if dry_run else "applied", "before": before, "after": after,
                "steps": applied}
    except Exception:
        if not dry_run:
            connection.rollback()
        raise
    finally:
        cursor.close()


def render_plan() -> str:
    lines = ["DRY RUN ONLY: no database connection opened."]
    for step in COLUMNS:
        lines.append(f"CHECK column {step.table}.{step.column}; ALTER TABLE ADD COLUMN if missing")
    for step in INDEXES:
        lines.append(f"CHECK index {step.table}.{step.name}; ALTER TABLE ADD INDEX if missing")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--connect-dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    if not any((args.connect_dry_run, args.apply, args.verify)):
        print(render_plan())
        return 0
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"--apply requires --confirm {APPLY_CONFIRMATION}")
    connection = _connect()
    try:
        result = execute(connection, dry_run=not args.apply)
        if args.verify and result["steps"]:
            raise RuntimeError("Schema verify failed; missing: " + ",".join(result["steps"]))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
