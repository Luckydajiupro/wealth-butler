"""适当性合规证据追加事件 Model。"""

import json
from datetime import datetime
from typing import Any, ClassVar, Optional

from pydantic import field_validator

from app.Base.Repository.base.baseDBModel import BaseDBModel


class ComplianceEvidenceModel(BaseDBModel):
    """以 ISSUED/REVOKED 事件保留证据全部历史，不覆盖原记录。"""

    table_alias: ClassVar[str] = "biz_compliance_evidence"
    create_table_sql: ClassVar[str] = """
    CREATE TABLE `biz_compliance_evidence` (
      `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
      `event_id` VARCHAR(64) NOT NULL COMMENT '每条追加事件的唯一ID',
      `evidence_id` VARCHAR(64) NOT NULL COMMENT '同一证据签发/撤销共用的稳定ID',
      `action` ENUM('ISSUED','REVOKED') NOT NULL COMMENT '证据事件类型',
      `customer_id` INT NOT NULL COMMENT '客户ID',
      `product_id` INT NULL COMMENT '产品ID，非产品证据可空',
      `evidence_type` VARCHAR(64) NOT NULL COMMENT '证据类型',
      `artifact_uri` VARCHAR(512) NULL COMMENT '录音录像/签署文件对象引用，不存文件本体',
      `artifact_sha256` CHAR(64) NULL COMMENT '证据对象SHA-256完整性摘要',
      `completed_at` DATETIME NOT NULL COMMENT '合规动作完成时间',
      `valid_until` DATETIME NULL COMMENT '证据有效期至，长期有效可空',
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
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='合规证据追加事件表';
    """

    id: Optional[int] = None
    event_id: str
    evidence_id: str
    action: str
    customer_id: int
    product_id: Optional[int] = None
    evidence_type: str
    artifact_uri: Optional[str] = None
    artifact_sha256: Optional[str] = None
    completed_at: datetime
    valid_until: Optional[datetime] = None
    verified_by: int
    verification_method: str
    trace_id: str
    metadata: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None

    @field_validator("metadata", mode="before")
    @classmethod
    def parse_metadata(cls, value):
        """将数据库 JSON 文本恢复为字典，模型实例始终保留结构化值。"""
        if value is None or isinstance(value, dict):
            return value
        if isinstance(value, str):
            return json.loads(value)
        return value

    def model_dump(self, **kwargs):
        """写库前序列化 JSON 字段，避免将 dict 直接交给 PyMySQL。"""
        data = super().model_dump(**kwargs)
        if "metadata" in data and isinstance(data["metadata"], (dict, list)):
            data["metadata"] = json.dumps(data["metadata"], ensure_ascii=False)
        return data

    @classmethod
    def find_latest_by_evidence_id(cls, evidence_id: str) -> Optional["ComplianceEvidenceModel"]:
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return None
        rows = db.execute(
            f"SELECT * FROM `{cls.table_alias}` WHERE `evidence_id` = %s "
            "ORDER BY `id` DESC LIMIT 1",
            (evidence_id,),
        )
        return cls(**rows[0]) if rows else None

    @classmethod
    def find_latest_by_customer_product_type(
        cls,
        customer_id: int,
        product_id: Optional[int],
        evidence_type: str,
    ) -> Optional["ComplianceEvidenceModel"]:
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return None
        product_clause = "`product_id` IS NULL" if product_id is None else "`product_id` = %s"
        params = (customer_id, evidence_type) if product_id is None else (customer_id, product_id, evidence_type)
        rows = db.execute(
            f"SELECT * FROM `{cls.table_alias}` WHERE `customer_id` = %s "
            f"AND {product_clause} AND `evidence_type` = %s "
            "ORDER BY `id` DESC LIMIT 1",
            params,
        )
        return cls(**rows[0]) if rows else None


__all__ = ["ComplianceEvidenceModel"]
