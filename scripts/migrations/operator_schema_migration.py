"""Operator 真实 Adapter 的 MySQL Schema 迁移工具。

默认只输出 dry-run 计划，不导入数据库驱动，也不建立连接。
只有同时传入 ``--apply`` 与明确确认口令时才会连接数据库。
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence


APPLY_CONFIRMATION = "APPLY_OPERATOR_SCHEMA"
TRANSACTION_TABLE = "fin_transaction"
AUDIT_TABLE = "biz_operation_audit"
TARGET_TRANSACTION_COLUMNS = (
    "employee_id", "trace_id", "idempotency_key", "failure_code", "failure_reason", "updated_at",
)


@dataclass(frozen=True)
class MigrationStep:
    """单个可幂等迁移步骤：check 返回 1 表示已满足。"""

    name: str
    check_sql: str
    check_params: tuple[Any, ...]
    ddl_sql: Optional[str]
    required: bool = False
    satisfied_value: int = 1
    depends_on: tuple[str, ...] = ()


def _table_exists_step(table_name: str, *, required: bool = False, ddl_sql: str | None = None) -> MigrationStep:
    return MigrationStep(
        name=f"table:{table_name}",
        check_sql=(
            "SELECT COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s"
        ),
        check_params=(table_name,),
        ddl_sql=ddl_sql,
        required=required,
    )


def _column_step(
    table_name: str,
    column_name: str,
    definition: str,
    *,
    depends_on: tuple[str, ...] = (),
) -> MigrationStep:
    return MigrationStep(
        name=f"column:{table_name}.{column_name}",
        check_sql=(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s"
        ),
        check_params=(table_name, column_name),
        ddl_sql=f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {definition}",
        depends_on=depends_on,
    )


def _index_step(
    table_name: str,
    index_name: str,
    definition: str,
    *,
    depends_on: tuple[str, ...] = (),
) -> MigrationStep:
    return MigrationStep(
        name=f"index:{table_name}.{index_name}",
        check_sql=(
            "SELECT COUNT(*) FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s"
        ),
        check_params=(table_name, index_name),
        ddl_sql=f"ALTER TABLE `{table_name}` ADD {definition}",
        depends_on=depends_on,
    )


AUDIT_CREATE_SQL = """CREATE TABLE IF NOT EXISTS `biz_operation_audit` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '审计主键',
  `audit_event_id` VARCHAR(64) NOT NULL COMMENT '审计事件幂等键',
  `trace_id` VARCHAR(64) NOT NULL COMMENT '跨Agent业务追踪ID',
  `employee_id` INT NOT NULL COMMENT '实际发起操作的员工ID',
  `customer_id` INT NULL COMMENT '业务所属客户ID',
  `intent` VARCHAR(64) NOT NULL COMMENT '操作意图',
  `parameter_names` JSON NOT NULL COMMENT '仅记录参数名，不记录敏感参数值',
  `success` TINYINT(1) NOT NULL COMMENT '操作是否成功',
  `result_code` VARCHAR(64) NOT NULL COMMENT '业务结果码',
  `failure_code` VARCHAR(64) NULL COMMENT '失败码',
  `failure_reason` VARCHAR(500) NULL COMMENT '脱敏失败原因',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '追加审计时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_operation_audit_event_id` (`audit_event_id`),
  KEY `idx_operation_audit_trace_id` (`trace_id`),
  KEY `idx_operation_audit_employee_created` (`employee_id`, `created_at`),
  KEY `idx_operation_audit_customer_created` (`customer_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Operator不可变追加式操作审计表'"""


def migration_steps() -> tuple[MigrationStep, ...]:
    """返回固定顺序的迁移计划；所有 DDL 都有对应 Schema 检查。"""
    transaction_columns = (
        _column_step(TRANSACTION_TABLE, "employee_id", "INT NULL COMMENT '实际发起操作的员工ID' AFTER `customer_id`"),
        _column_step(TRANSACTION_TABLE, "trace_id", "VARCHAR(64) NULL COMMENT '跨Agent业务追踪ID' AFTER `employee_id`"),
        _column_step(TRANSACTION_TABLE, "idempotency_key", "VARCHAR(128) NULL COMMENT '成交幂等键' AFTER `trace_id`"),
        _column_step(TRANSACTION_TABLE, "failure_code", "VARCHAR(64) NULL COMMENT '失败码' AFTER `status`"),
        _column_step(TRANSACTION_TABLE, "failure_reason", "VARCHAR(500) NULL COMMENT '脱敏失败原因' AFTER `failure_code`"),
        _column_step(
            TRANSACTION_TABLE,
            "updated_at",
            "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间' AFTER `created_at`",
        ),
    )
    idempotency_duplicate_precheck = MigrationStep(
        name="precondition:fin_transaction.idempotency_key_duplicates",
        check_sql=(
            "SELECT COUNT(*) FROM (SELECT `idempotency_key` FROM `fin_transaction` "
            "WHERE `idempotency_key` IS NOT NULL GROUP BY `idempotency_key` HAVING COUNT(*) > 1) AS duplicates"
        ),
        check_params=(),
        ddl_sql=None,
        required=True,
        satisfied_value=0,
        depends_on=("column:fin_transaction.idempotency_key",),
    )
    trace_duplicate_precheck = MigrationStep(
        name="precondition:fin_transaction.trace_id_duplicates",
        check_sql=(
            "SELECT COUNT(*) FROM (SELECT `trace_id` FROM `fin_transaction` "
            "WHERE `trace_id` IS NOT NULL GROUP BY `trace_id` HAVING COUNT(*) > 1) AS duplicates"
        ),
        check_params=(),
        ddl_sql=None,
        required=True,
        satisfied_value=0,
        depends_on=("column:fin_transaction.trace_id",),
    )
    transaction_indexes = (
        _index_step(TRANSACTION_TABLE, "idx_fin_transaction_employee_id", "KEY `idx_fin_transaction_employee_id` (`employee_id`)"),
        _index_step(
            TRANSACTION_TABLE,
            "uk_fin_transaction_trace_id",
            "UNIQUE KEY `uk_fin_transaction_trace_id` (`trace_id`)",
        ),
        _index_step(
            TRANSACTION_TABLE,
            "uk_fin_transaction_idempotency_key",
            "UNIQUE KEY `uk_fin_transaction_idempotency_key` (`idempotency_key`)",
        ),
    )
    audit_columns = (
        ("audit_event_id", "VARCHAR(64) NOT NULL COMMENT '审计事件幂等键' AFTER `id`"),
        ("trace_id", "VARCHAR(64) NOT NULL COMMENT '跨Agent业务追踪ID' AFTER `audit_event_id`"),
        ("employee_id", "INT NOT NULL COMMENT '实际发起操作的员工ID' AFTER `trace_id`"),
        ("customer_id", "INT NULL COMMENT '业务所属客户ID' AFTER `employee_id`"),
        ("intent", "VARCHAR(64) NOT NULL COMMENT '操作意图' AFTER `customer_id`"),
        ("parameter_names", "JSON NOT NULL COMMENT '仅记录参数名，不记录敏感参数值' AFTER `intent`"),
        ("success", "TINYINT(1) NOT NULL COMMENT '操作是否成功' AFTER `parameter_names`"),
        ("result_code", "VARCHAR(64) NOT NULL COMMENT '业务结果码' AFTER `success`"),
        ("failure_code", "VARCHAR(64) NULL COMMENT '失败码' AFTER `result_code`"),
        ("failure_reason", "VARCHAR(500) NULL COMMENT '脱敏失败原因' AFTER `failure_code`"),
        ("created_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '追加审计时间' AFTER `failure_reason`"),
    )
    audit_indexes = (
        ("uk_operation_audit_event_id", "UNIQUE KEY `uk_operation_audit_event_id` (`audit_event_id`)"),
        ("idx_operation_audit_trace_id", "KEY `idx_operation_audit_trace_id` (`trace_id`)"),
        ("idx_operation_audit_employee_created", "KEY `idx_operation_audit_employee_created` (`employee_id`, `created_at`)"),
        ("idx_operation_audit_customer_created", "KEY `idx_operation_audit_customer_created` (`customer_id`, `created_at`)"),
    )
    return (
        _table_exists_step(TRANSACTION_TABLE, required=True),
        *transaction_columns,
        idempotency_duplicate_precheck,
        trace_duplicate_precheck,
        *transaction_indexes,
        _table_exists_step(AUDIT_TABLE, ddl_sql=AUDIT_CREATE_SQL),
        *(
            _column_step(
                AUDIT_TABLE,
                name,
                definition,
                depends_on=(f"table:{AUDIT_TABLE}",),
            )
            for name, definition in audit_columns
        ),
        *(
            _index_step(
                AUDIT_TABLE,
                name,
                definition,
                depends_on=(f"table:{AUDIT_TABLE}",),
            )
            for name, definition in audit_indexes
        ),
    )


def render_plan(steps: Iterable[MigrationStep] | None = None) -> str:
    """生成供 DBA 审核的检查/DDL 计划，不连接数据库。"""
    lines = [
        "-- DRY RUN ONLY: no database connection was opened.",
        "-- Execute schema checks before each DDL through this migration runner.",
    ]
    for step in steps or migration_steps():
        lines.extend(("", f"-- {step.name}", f"-- CHECK: {step.check_sql} ; params={step.check_params!r}"))
        if step.ddl_sql:
            lines.append(f"{step.ddl_sql};")
        else:
            lines.append("-- PRECONDITION ONLY; no DDL")
    return "\n".join(lines)


def execute_migration(connection: Any, *, dry_run: bool = True) -> list[dict[str, Any]]:
    """使用显式注入的 DB-API 连接检查并迁移；默认不执行 DDL。"""
    results: list[dict[str, Any]] = []
    cursor = connection.cursor()
    pending_steps: set[str] = set()
    try:
        for step in migration_steps():
            blocked_by = tuple(name for name in step.depends_on if name in pending_steps)
            if dry_run and blocked_by:
                results.append(
                    {
                        "name": step.name,
                        "status": "would_check_after_dependencies",
                        "depends_on": blocked_by,
                    }
                )
                continue
            cursor.execute(step.check_sql, step.check_params)
            row = cursor.fetchone()
            actual = int(row[0] if row else 0)
            satisfied = actual == step.satisfied_value if step.required else actual > 0
            if step.required and not satisfied:
                raise RuntimeError(f"Schema precondition failed: {step.name} (actual={actual})")
            if satisfied:
                results.append({"name": step.name, "status": "already_satisfied"})
                continue
            if step.ddl_sql is None:
                raise RuntimeError(f"Migration step has no DDL: {step.name}")
            if dry_run:
                results.append({"name": step.name, "status": "would_apply", "ddl": step.ddl_sql})
                pending_steps.add(step.name)
                continue
            cursor.execute(step.ddl_sql)
            cursor.execute(step.check_sql, step.check_params)
            verified = cursor.fetchone()
            if not verified or int(verified[0]) <= 0:
                raise RuntimeError(f"Schema verification failed after DDL: {step.name}")
            results.append({"name": step.name, "status": "applied"})
        if not dry_run:
            connection.commit()
        return results
    except Exception:
        if not dry_run:
            connection.rollback()
        raise
    finally:
        cursor.close()


def inspect_operator_schema(connection: Any) -> dict[str, Any]:
    """只读返回迁移前后可对比的 Schema/数据完整性摘要。"""
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM `fin_transaction`")
        transaction_rows = int(cursor.fetchone()[0])
        placeholders = ", ".join(("%s",) * len(TARGET_TRANSACTION_COLUMNS))
        cursor.execute(
            "SELECT `COLUMN_NAME` FROM information_schema.COLUMNS "
            f"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME IN ({placeholders}) "
            "ORDER BY `COLUMN_NAME`",
            (TRANSACTION_TABLE, *TARGET_TRANSACTION_COLUMNS),
        )
        transaction_columns = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            "SELECT `INDEX_NAME`, MIN(`NON_UNIQUE`) AS non_unique, "
            "GROUP_CONCAT(`COLUMN_NAME` ORDER BY `SEQ_IN_INDEX` SEPARATOR ',') AS columns_list "
            "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
            "GROUP BY `INDEX_NAME` ORDER BY `INDEX_NAME`",
            (TRANSACTION_TABLE,),
        )
        transaction_indexes = [
            {"name": row[0], "unique": int(row[1]) == 0, "columns": row[2].split(",")}
            for row in cursor.fetchall()
        ]
        duplicate_counts: dict[str, Optional[int]] = {}
        for column in ("idempotency_key", "trace_id"):
            if column not in transaction_columns:
                duplicate_counts[column] = None
                continue
            cursor.execute(
                f"SELECT COUNT(*) FROM (SELECT `{column}` FROM `{TRANSACTION_TABLE}` "
                f"WHERE `{column}` IS NOT NULL GROUP BY `{column}` HAVING COUNT(*) > 1) AS duplicates"
            )
            duplicate_counts[column] = int(cursor.fetchone()[0])

        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
            (AUDIT_TABLE,),
        )
        audit_exists = bool(cursor.fetchone()[0])
        audit_columns: list[str] = []
        audit_indexes: list[dict[str, Any]] = []
        audit_rows: Optional[int] = None
        if audit_exists:
            cursor.execute(
                "SELECT `COLUMN_NAME` FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s ORDER BY `ORDINAL_POSITION`",
                (AUDIT_TABLE,),
            )
            audit_columns = [row[0] for row in cursor.fetchall()]
            cursor.execute(
                "SELECT `INDEX_NAME`, MIN(`NON_UNIQUE`) AS non_unique, "
                "GROUP_CONCAT(`COLUMN_NAME` ORDER BY `SEQ_IN_INDEX` SEPARATOR ',') AS columns_list "
                "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
                "GROUP BY `INDEX_NAME` ORDER BY `INDEX_NAME`",
                (AUDIT_TABLE,),
            )
            audit_indexes = [
                {"name": row[0], "unique": int(row[1]) == 0, "columns": row[2].split(",")}
                for row in cursor.fetchall()
            ]
            cursor.execute(f"SELECT COUNT(*) FROM `{AUDIT_TABLE}`")
            audit_rows = int(cursor.fetchone()[0])
        return {
            "fin_transaction_rows": transaction_rows,
            "target_transaction_columns": transaction_columns,
            "transaction_indexes": transaction_indexes,
            "duplicate_non_null_keys": duplicate_counts,
            "audit_table_exists": audit_exists,
            "audit_columns": audit_columns,
            "audit_indexes": audit_indexes,
            "audit_rows": audit_rows,
        }
    finally:
        cursor.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operator Schema migration (dry-run by default)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Explicitly connect and apply missing DDL")
    mode.add_argument(
        "--connect-dry-run",
        action="store_true",
        help="Connect and inspect the current schema without executing or committing DDL",
    )
    mode.add_argument(
        "--verify",
        action="store_true",
        help="Connect read-only and report row counts, target columns, indexes and duplicate keys",
    )
    parser.add_argument("--confirm", default="", help=f"Required with --apply: {APPLY_CONFIRMATION}")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--database")
    parser.add_argument("--user")
    parser.add_argument("--password-env", default="OPERATOR_MIGRATION_DB_PASSWORD")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.apply and not args.connect_dry_run and not args.verify:
        print(render_plan())
        return 0
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"--apply requires --confirm {APPLY_CONFIRMATION}")
    if not args.database or not args.user:
        raise SystemExit("connected mode requires --database and --user")
    password = os.environ.get(args.password_env)
    if password is None:
        raise SystemExit(f"password environment variable is not set: {args.password_env}")

    # 驱动只在显式 apply 分支导入，dry-run 绝不触发网络或配置副作用。
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
            print(json.dumps(inspect_operator_schema(connection), ensure_ascii=False, sort_keys=True))
            return 0
        for item in execute_migration(connection, dry_run=args.connect_dry_run):
            print(f"{item['status']}: {item['name']}")
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
