"""产品净值历史表的安全幂等迁移与现有净值回填。"""

from __future__ import annotations

import argparse
import os


APPLY_CONFIRMATION = "APPLY_PRODUCT_NAV_HISTORY"
CREATE_SQL = """CREATE TABLE `fin_product_nav_history` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `product_id` INT NOT NULL COMMENT '产品ID',
  `nav_date` DATE NOT NULL COMMENT '净值日期',
  `nav` DECIMAL(10,4) NOT NULL COMMENT '单位净值',
  `source` VARCHAR(64) NOT NULL DEFAULT 'product_feed' COMMENT '净值数据来源',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_product_nav_date` (`product_id`, `nav_date`),
  KEY `idx_product_nav_date` (`nav_date`, `product_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='产品日净值历史'"""
BACKFILL_SQL = """INSERT INTO `fin_product_nav_history`
  (`product_id`, `nav_date`, `nav`, `source`)
SELECT `id`, `nav_date`, `nav`, 'fin_product_backfill'
FROM `fin_product`
WHERE `nav` IS NOT NULL AND `nav_date` IS NOT NULL
ON DUPLICATE KEY UPDATE `nav`=VALUES(`nav`), `source`=VALUES(`source`)"""
REQUIRED_COLUMNS = {"id", "product_id", "nav_date", "nav", "source", "created_at"}
REQUIRED_INDEXES = {"PRIMARY", "uk_product_nav_date", "idx_product_nav_date"}


def _exists(cursor) -> bool:
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='fin_product_nav_history'"
    )
    return bool(cursor.fetchone()[0])


def _validate(cursor) -> None:
    cursor.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='fin_product_nav_history'"
    )
    columns = {row[0] for row in cursor.fetchall()}
    cursor.execute(
        "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='fin_product_nav_history'"
    )
    indexes = {row[0] for row in cursor.fetchall()}
    if REQUIRED_COLUMNS - columns or REQUIRED_INDEXES - indexes:
        raise RuntimeError(
            "fin_product_nav_history schema conflict: "
            f"missing_columns={sorted(REQUIRED_COLUMNS - columns)}, "
            f"missing_indexes={sorted(REQUIRED_INDEXES - indexes)}"
        )


def execute_migration(connection, *, dry_run: bool = True) -> dict:
    cursor = connection.cursor()
    try:
        existed = _exists(cursor)
        if existed:
            _validate(cursor)
        elif dry_run:
            return {"status": "would_create_and_backfill"}
        else:
            cursor.execute(CREATE_SQL)
            _validate(cursor)
        if dry_run:
            return {"status": "would_backfill"}
        affected = cursor.execute(BACKFILL_SQL)
        connection.commit()
        return {"status": "applied", "table_created": not existed, "backfill_affected": affected}
    except Exception:
        if not dry_run:
            connection.rollback()
        raise
    finally:
        cursor.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if not args.apply:
        print(CREATE_SQL + ";\n" + BACKFILL_SQL + ";")
        return 0
    if args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"--apply requires --confirm {APPLY_CONFIRMATION}")
    from dotenv import load_dotenv
    import pymysql

    load_dotenv()
    connection = pymysql.connect(
        host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"]),
        user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"], charset="utf8mb4", autocommit=False,
    )
    try:
        print(execute_migration(connection, dry_run=False))
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
