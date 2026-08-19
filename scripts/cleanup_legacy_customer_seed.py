#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""安全清理旧财富管家客户种子数据。

默认只连接数据库并预览候选客户及各表数量。只有显式提供
``--apply --confirm CLEANUP_LEGACY_CUSTOMER_DATA`` 才会删除数据。

本脚本的删除范围严格限定为客户账号及其业务记录，绝不操作产品表、
知识库/FAQ 表、产品问答或 Milvus 集合。无法确认客户归属的孤儿工单
只会报告，不会被猜测删除。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONFIRMATION = "CLEANUP_LEGACY_CUSTOMER_DATA"
LEGACY_USERNAMES = ("customer_zhang", "customer_li")

# 顺序从引用客户的子表到客户画像/账号。只允许这些表进入 DELETE。
CUSTOMER_TABLES = (
    ("fin_verified_payee", "customer_id"),
    ("biz_compliance_evidence", "customer_id"),
    ("biz_operation_audit", "customer_id"),
    ("conversation_archive", "customer_id"),
    ("base_llm_conversation", "user_id"),
    ("base_llm_session", "user_id"),
    ("biz_work_order", "customer_id"),
    ("fin_risk_alert", "customer_id"),
    ("fin_holdings", "customer_id"),
    ("fin_transaction", "customer_id"),
    ("fin_risk_assessment", "customer_id"),
    ("fin_customer_profile", "customer_id"),
    ("base_user_role", "user_id"),
    ("base_user", "id"),
)

FORBIDDEN_TABLES = {
    "fin_product", "fin_product_nav_history", "fin_knowledge_meta",
    "fin_faq", "faq", "knowledge_meta",
}


def connect():
    load_dotenv(ROOT / ".env", override=False)
    required = ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("数据库配置缺失: " + ", ".join(missing))
    import pymysql

    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        charset=os.environ.get("DB_CHARSET", "utf8mb4"),
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=int(os.environ.get("DB_CONNECT_TIMEOUT", "10")),
    )


def table_columns(cursor: Any, table: str) -> set[str]:
    cursor.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s",
        (table,),
    )
    return {str(row["COLUMN_NAME"]) for row in cursor.fetchall()}


def resolve_customers(cursor: Any) -> list[dict[str, Any]]:
    """通过自然键和明确 seed 标记解析客户，绝不按数字 ID 猜测。"""
    cursor.execute(
        "SELECT id, username, user_type, source_module, extra_data "
        "FROM base_user WHERE deleted_at IS NULL AND user_type='CUSTOMER' "
        "AND (username IN (%s,%s) OR username LIKE 'wb_seed_customer_%%' "
        "OR username LIKE 'wb_seed_c%%' "
        "OR JSON_UNQUOTE(JSON_EXTRACT(extra_data, '$.seed_namespace')) LIKE 'WB-SEED-%%') "
        "ORDER BY id",
        LEGACY_USERNAMES,
    )
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def count_rows(cursor: Any, table: str, column: str, ids: tuple[int, ...]) -> int | None:
    columns = table_columns(cursor, table)
    if column not in columns:
        return None
    if not ids:
        return 0
    marks = ",".join(["%s"] * len(ids))
    cursor.execute(f"SELECT COUNT(*) AS count FROM `{table}` WHERE `{column}` IN ({marks})", ids)
    return int(cursor.fetchone()["count"])


def preview(connection: Any) -> dict[str, Any]:
    cursor = connection.cursor()
    try:
        customers = resolve_customers(cursor)
        ids = tuple(int(row["id"]) for row in customers)
        tables: dict[str, int | None] = {}
        for table, column in CUSTOMER_TABLES:
            tables[table] = count_rows(cursor, table, column, ids)

        orphan = None
        if "biz_work_order" in tables and "customer_id" in table_columns(cursor, "biz_work_order"):
            cursor.execute(
                "SELECT COUNT(*) AS count FROM biz_work_order w "
                "LEFT JOIN base_user u ON u.id=w.customer_id "
                "WHERE w.customer_id IS NOT NULL AND u.id IS NULL"
            )
            orphan = int(cursor.fetchone()["count"])

        protected: dict[str, int | None] = {}
        for table in sorted(FORBIDDEN_TABLES):
            if table in {str(row["TABLE_NAME"]) for row in _existing_tables(cursor)}:
                cursor.execute(f"SELECT COUNT(*) AS count FROM `{table}`")
                protected[table] = int(cursor.fetchone()["count"])

        return {
            "customers": [
                {"id": int(row["id"]), "username": str(row["username"]),
                 "source_module": row.get("source_module"), "seed_namespace": _seed_namespace(row.get("extra_data"))}
                for row in customers
            ],
            "row_counts": tables,
            "orphan_work_orders_preserved": orphan,
            "protected_table_counts": protected,
        }
    finally:
        cursor.close()


def _existing_tables(cursor: Any) -> list[dict[str, Any]]:
    cursor.execute(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE()"
    )
    return cursor.fetchall()


def _seed_namespace(raw: Any) -> str | None:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return None
    return str(value.get("seed_namespace")) if isinstance(value, dict) and value.get("seed_namespace") else None


def apply_cleanup(connection: Any, customer_ids: tuple[int, ...]) -> dict[str, int]:
    if not customer_ids:
        return {}
    cursor = connection.cursor()
    deleted: dict[str, int] = {}
    try:
        for table, column in CUSTOMER_TABLES:
            if table in FORBIDDEN_TABLES:
                raise RuntimeError(f"保护表意外进入清理列表: {table}")
            columns = table_columns(cursor, table)
            if column not in columns:
                continue
            marks = ",".join(["%s"] * len(customer_ids))
            cursor.execute(f"DELETE FROM `{table}` WHERE `{column}` IN ({marks})", customer_ids)
            deleted[table] = int(cursor.rowcount)
        connection.commit()
        return deleted
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connect-dry-run", action="store_true", help="连接数据库并输出清理预览")
    parser.add_argument("--apply", action="store_true", help="执行客户相关数据清理")
    parser.add_argument("--confirm", default="", help=f"必须为 {CONFIRMATION}")
    args = parser.parse_args(argv)
    if args.apply and args.confirm != CONFIRMATION:
        raise SystemExit(f"--apply requires --confirm {CONFIRMATION}")
    if not args.connect_dry_run and not args.apply:
        print("默认不连接数据库。使用 --connect-dry-run 预览，或使用 --apply --confirm " + CONFIRMATION + " 执行。")
        return 0

    connection = connect()
    try:
        before = preview(connection)
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", **before}, ensure_ascii=False, indent=2))
        if not args.apply:
            return 0
        ids = tuple(item["id"] for item in before["customers"])
        deleted = apply_cleanup(connection, ids)
        after = preview(connection)
        print(json.dumps({"deleted": deleted, "after": after,
                          "protected_tables_untouched": before["protected_table_counts"] == after["protected_table_counts"]},
                         ensure_ascii=False, indent=2))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
