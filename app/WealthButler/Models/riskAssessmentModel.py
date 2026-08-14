from app.Base.Repository.base.baseDBModel import BaseDBModel
from typing import Optional, ClassVar
from datetime import datetime
from decimal import Decimal


class RiskAssessmentModel(BaseDBModel):
    """
    风险评估记录表（16题问卷版）
    包含答题记录、总分、风险等级、有效期等字段
    """

    table_alias: ClassVar[str] = "fin_risk_assessment"

    create_table_sql: ClassVar[str] = f"""
    CREATE TABLE `fin_risk_assessment` (
      `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
      `customer_id` INT NOT NULL COMMENT '客户ID',
      `total_score` DECIMAL(5,2) NOT NULL COMMENT '问卷总分0-100',
      `risk_level` ENUM('C1','C2','C3','C4','C5') NOT NULL COMMENT '评估结果分级',
      `answers` JSON NOT NULL COMMENT '16题逐题作答记录',
      `is_professional_investor` TINYINT(1) DEFAULT 0 COMMENT '是否专业投资者',
      `assessment_time` DATETIME NOT NULL COMMENT '评估完成时间',
      `valid_until` DATETIME NOT NULL COMMENT '有效期至（+12个月）',
      `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
      PRIMARY KEY (`id`),
      KEY `idx_customer_id` (`customer_id`),
      KEY `idx_valid_until` (`valid_until`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='风险评估记录表';
    """

    # Pydantic字段定义
    id: Optional[int] = None
    customer_id: int
    total_score: Decimal
    risk_level: str
    answers: list
    is_professional_investor: bool = False
    assessment_time: datetime
    valid_until: datetime
    created_at: Optional[datetime] = None

    @classmethod
    def find_latest_by_customer_id(cls, customer_id: int):
        """查询客户最新的风险评估记录"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return None
        sql = f"""SELECT * FROM {cls.table_alias}
                  WHERE customer_id = %s
                  ORDER BY assessment_time DESC
                  LIMIT 1"""
        results = db.execute(sql, (customer_id,))
        return cls(**results[0]) if results else None

    @classmethod
    def find_valid_by_customer_id(cls, customer_id: int):
        """查询客户当前有效的风险评估记录（未过期）"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return None
        sql = f"""SELECT * FROM {cls.table_alias}
                  WHERE customer_id = %s
                  AND valid_until > NOW()
                  ORDER BY assessment_time DESC
                  LIMIT 1"""
        results = db.execute(sql, (customer_id,))
        return cls(**results[0]) if results else None

    @classmethod
    def check_expired(cls, customer_id: int) -> bool:
        """检查客户风险评估是否已过期（支持FM-03熔断规则）"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return True  # 无法查询则认为过期，触发熔断
        sql = f"""SELECT COUNT(*) as cnt FROM {cls.table_alias}
                  WHERE customer_id = %s
                  AND valid_until > NOW()"""
        results = db.execute(sql, (customer_id,))
        return results[0]['cnt'] == 0 if results else True
