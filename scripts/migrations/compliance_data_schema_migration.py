"""合规证据与收款方指纹表的安全幂等迁移。

默认只打印离线计划。新表同名对象若已存在，必须完整匹配预期字段和
索引，否则失败关闭，不自动修补或覆盖现有表。
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


APPLY_CONFIRMATION = "APPLY_COMPLIANCE_DATA_SCHEMA"


EVIDENCE_CREATE_SQL = """CREATE TABLE `biz_compliance_evidence` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `event_id` VARCHAR(64) NOT NULL COMMENT '每条追加事件的唯一ID',
  `evidence_id` VARCHAR(64) NOT NULL COMMENT '同一证据签发/撤销共用的稳定ID',
  `action` ENUM('ISSUED','REVOKED') NOT NULL COMMENT '证据事件类型',
  `customer_id` INT NOT NULL COMMENT '客户ID',
  `product_id` INT NULL COMMENT '产品ID，非产品证据可空',
  `evidence_type` VARCHAR(64) NOT NULL COMMENT '证据类型',
  `artifact_uri` VARCHAR(512) NULL COMMENT '合规证据对象引用',
  `artifact_sha256` CHAR(64) NULL COMMENT '证据对象SHA-256完整性摘要',
  `completed_at` DATETIME NOT NULL COMMENT '合规动作完成时间',
  `valid_until` DATETIME NULL COMMENT '证据有效期至',
  `verified_by` INT NOT NULL COMMENT '核验员工ID',
  `verification_method` VARCHAR(50) NOT NULL COMMENT '核验方式',
  `trace_id` VARCHAR(64) NOT NULL COMMENT '跨Agent业务追踪ID',
  `metadata` JSON NULL COMMENT '非敏感结构化补充元数据',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '追加入库时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_compliance_evidence_event_id` (`event_id`),
  KEY `idx_compliance_evidence_id` (`evidence_id`, `id`),
  KEY `idx_compliance_evidence_customer_product_type` (`customer_id`, `product_id`, `evidence_type`, `id`),
  KEY `idx_compliance_evidence_trace_id` (`trace_id`),
  KEY `idx_compliance_evidence_valid_until` (`valid_until`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='合规证据追加事件表'"""

PAYEE_CREATE_SQL = """CREATE TABLE `fin_verified_payee` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `customer_id` INT NOT NULL COMMENT '客户ID',
  `account_hmac` CHAR(64) NOT NULL COMMENT '收款账号HMAC-SHA256指纹',
  `account_last4` CHAR(4) NOT NULL COMMENT '账号后四位',
  `payee_name_hmac` CHAR(64) NOT NULL COMMENT '收款方姓名HMAC-SHA256指纹',
  `verification_method` VARCHAR(50) NOT NULL COMMENT '核验方式',
  `status` ENUM('PENDING','VERIFIED','REJECTED','EXPIRED','REVOKED') NOT NULL DEFAULT 'PENDING' COMMENT '核验状态',
  `verified_by` INT NULL COMMENT '核验员工ID',
  `verified_at` DATETIME NULL COMMENT '核验完成时间',
  `valid_until` DATETIME NULL COMMENT '核验有效期至',
  `trace_id` VARCHAR(64) NOT NULL COMMENT '跨Agent业务追踪ID',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_verified_payee_customer_account` (`customer_id`, `account_hmac`),
  KEY `idx_verified_payee_status_valid` (`status`, `valid_until`),
  KEY `idx_verified_payee_trace_id` (`trace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='已核验收款方指纹表'"""


@dataclass(frozen=True)
class TableSpec:
    name: str
    create_sql: str
    required_columns: frozenset[str]
    required_indexes: frozenset[str]
    forbidden_columns: frozenset[str] = frozenset()


TABLE_SPECS = (
    TableSpec(
        name="biz_compliance_evidence",
        create_sql=EVIDENCE_CREATE_SQL,
        required_columns=frozenset({
            "id", "event_id", "evidence_id", "action", "customer_id", "product_id",
            "evidence_type", "artifact_uri", "artifact_sha256", "completed_at", "valid_until",
            "verified_by", "verification_method", "trace_id", "metadata", "created_at",
        }),
        required_indexes=frozenset({
            "PRIMARY", "uk_compliance_evidence_event_id", "idx_compliance_evidence_id",
            "idx_compliance_evidence_customer_product_type", "idx_compliance_evidence_trace_id",
            "idx_compliance_evidence_valid_until",
        }),
    ),
    TableSpec(
        name="fin_verified_payee",
        create_sql=PAYEE_CREATE_SQL,
        required_columns=frozenset({
            "id", "customer_id", "account_hmac", "account_last4", "payee_name_hmac",
            "verification_method", "status", "verified_by", "verified_at", "valid_until",
            "trace_id", "created_at", "updated_at",
        }),
        required_indexes=frozenset({
            "PRIMARY", "uk_verified_payee_customer_account", "idx_verified_payee_status_valid",
            "idx_verified_payee_trace_id",
        }),
        forbidden_columns=frozenset({"account", "account_number", "payee_name", "counterparty_account"}),
    ),
)


def _table_exists(cursor: Any, table: str) -> bool:
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (table,),
    )
    return bool(cursor.fetchone()[0])


def _inspect_table(cursor: Any, spec: TableSpec) -> dict[str, Any]:
    cursor.execute(
        "SELECT `COLUMN_NAME` FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s ORDER BY `ORDINAL_POSITION`",
        (spec.name,),
    )
    columns = [row[0] for row in cursor.fetchall()]
    cursor.execute(
        "SELECT DISTINCT `INDEX_NAME` FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s ORDER BY `INDEX_NAME`",
        (spec.name,),
    )
    indexes = [row[0] for row in cursor.fetchall()]
    cursor.execute(f"SELECT COUNT(*) FROM `{spec.name}`")
    rows = int(cursor.fetchone()[0])
    return {"columns": columns, "indexes": indexes, "rows": rows}


def _validate_existing(spec: TableSpec, details: Mapping[str, Any]) -> None:
    columns = set(details["columns"])
    missing_columns = sorted(spec.required_columns - columns)
    missing_indexes = sorted(spec.required_indexes - set(details["indexes"]))
    forbidden = sorted(spec.forbidden_columns & columns)
    if missing_columns or missing_indexes or forbidden:
        raise RuntimeError(
            f"Schema conflict for {spec.name}: missing_columns={missing_columns}, "
            f"missing_indexes={missing_indexes}, forbidden_columns={forbidden}"
        )


def inspect_schema(connection: Any) -> dict[str, Any]:
    cursor = connection.cursor()
    try:
        result = {}
        for spec in TABLE_SPECS:
            exists = _table_exists(cursor, spec.name)
            details = _inspect_table(cursor, spec) if exists else {"columns": [], "indexes": [], "rows": None}
            result[spec.name] = {"exists": exists, **details}
        return result
    finally:
        cursor.close()


def execute_migration(connection: Any, *, dry_run: bool = True) -> list[dict[str, Any]]:
    """先检查同名表；仅在表不存在时创建，已存在但不兼容时立即停止。"""
    cursor = connection.cursor()
    results = []
    try:
        for spec in TABLE_SPECS:
            if _table_exists(cursor, spec.name):
                _validate_existing(spec, _inspect_table(cursor, spec))
                results.append({"table": spec.name, "status": "already_satisfied"})
                continue
            if dry_run:
                results.append({"table": spec.name, "status": "would_create"})
                continue
            cursor.execute(spec.create_sql)
            if not _table_exists(cursor, spec.name):
                raise RuntimeError(f"Schema verification failed after create: {spec.name}")
            _validate_existing(spec, _inspect_table(cursor, spec))
            results.append({"table": spec.name, "status": "created"})
        if not dry_run:
            connection.commit()
        return results
    except Exception:
        if not dry_run:
            connection.rollback()
        raise
    finally:
        cursor.close()


def render_plan() -> str:
    lines = ["-- DRY RUN ONLY: no database connection was opened."]
    for spec in TABLE_SPECS:
        lines.extend((
            "",
            f"-- CHECK information_schema.TABLES/COLUMNS/STATISTICS for {spec.name}",
            spec.create_sql + ";",
        ))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compliance data schema migration (offline dry-run by default)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--connect-dry-run", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--database")
    parser.add_argument("--user")
    parser.add_argument("--password-env", default="COMPLIANCE_MIGRATION_DB_PASSWORD")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (args.connect_dry_run or args.verify or args.apply):
        print(render_plan())
        return 0
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"--apply requires --confirm {APPLY_CONFIRMATION}")
    if not args.database or not args.user:
        raise SystemExit("connected mode requires --database and --user")
    password = os.environ.get(args.password_env)
    if password is None:
        raise SystemExit(f"password environment variable is not set: {args.password_env}")

    import pymysql

    connection = pymysql.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=password,
        database=args.database,
        charset="utf8mb4",
        autocommit=False,
    )
    try:
        if args.verify:
            print(json.dumps(inspect_schema(connection), ensure_ascii=False, sort_keys=True))
            return 0
        for item in execute_migration(connection, dry_run=args.connect_dry_run):
            print(f"{item['status']}: {item['table']}")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
