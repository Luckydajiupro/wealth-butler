"""已核验收款方 Model：只保存 HMAC 指纹和账号后四位。"""

from datetime import datetime
from hmac import compare_digest
from typing import ClassVar, Optional

from app.Base.Repository.base.baseDBModel import BaseDBModel


class VerifiedPayeeModel(BaseDBModel):
    """转账收款方核验状态，禁止存储明文账号或收款方姓名。"""

    table_alias: ClassVar[str] = "fin_verified_payee"
    create_table_sql: ClassVar[str] = """
    CREATE TABLE `fin_verified_payee` (
      `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
      `customer_id` INT NOT NULL COMMENT '客户ID',
      `account_hmac` CHAR(64) NOT NULL COMMENT '收款账号HMAC-SHA256指纹',
      `account_last4` CHAR(4) NOT NULL COMMENT '账号后四位，仅用于用户识别',
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
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='已核验收款方指纹表';
    """

    id: Optional[int] = None
    customer_id: int
    account_hmac: str
    account_last4: str
    payee_name_hmac: str
    verification_method: str
    status: str = "PENDING"
    verified_by: Optional[int] = None
    verified_at: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    trace_id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def find_by_fingerprint(cls, customer_id: int, account_hmac: str) -> Optional["VerifiedPayeeModel"]:
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return None
        rows = db.execute(
            f"SELECT * FROM `{cls.table_alias}` "
            "WHERE `customer_id` = %s AND `account_hmac` = %s LIMIT 1",
            (customer_id, account_hmac),
        )
        return cls(**rows[0]) if rows else None

    def matches_payee_name_hmac(self, payee_name_hmac: str) -> bool:
        """收款方放行前必须同时比较账号与姓名指纹，本方法用常数时间比较姓名指纹。"""
        if not isinstance(payee_name_hmac, str):
            return False
        return compare_digest(self.payee_name_hmac, payee_name_hmac)


__all__ = ["VerifiedPayeeModel"]
