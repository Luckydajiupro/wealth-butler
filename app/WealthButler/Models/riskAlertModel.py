from app.Base.Repository.base.baseDBModel import BaseDBModel
from typing import Optional, ClassVar
from datetime import datetime
from decimal import Decimal


class RiskAlertModel(BaseDBModel):
    """
    风控预警表
    包含规则ID、客户ID、触发详情、置信度、处理状态等字段
    """

    table_alias: ClassVar[str] = "fin_risk_alert"

    create_table_sql: ClassVar[str] = f"""
    CREATE TABLE `fin_risk_alert` (
      `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
      `customer_id` INT NOT NULL COMMENT '客户ID',
      `rule_id` VARCHAR(20) NOT NULL COMMENT '触发的规则ID（RW-001~RW-020）',
      `rule_name` VARCHAR(100) NOT NULL COMMENT '规则名称',
      `severity` ENUM('low','medium','high','critical') NOT NULL COMMENT '严重程度',
      `confidence` DECIMAL(4,3) NOT NULL COMMENT '置信度0-1',
      `trigger_details` JSON COMMENT '触发详情（违反条件列表）',
      `related_transaction_id` BIGINT COMMENT '关联交易ID',
      `status` ENUM('待处理','处理中','已处理','误报') DEFAULT '待处理' COMMENT '处理状态',
      `handler_id` INT COMMENT '处理人ID（员工ID）',
      `handle_result` TEXT COMMENT '处理结果记录',
      `handled_at` DATETIME COMMENT '处理完成时间',
      `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
      PRIMARY KEY (`id`),
      KEY `idx_customer_id` (`customer_id`),
      KEY `idx_rule_id` (`rule_id`),
      KEY `idx_status` (`status`),
      KEY `idx_created_at` (`created_at`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='风控预警表';
    """

    # Pydantic字段定义
    id: Optional[int] = None
    customer_id: int
    rule_id: str
    rule_name: str
    severity: str
    confidence: Decimal
    trigger_details: Optional[dict] = None
    related_transaction_id: Optional[int] = None
    status: str = "待处理"
    handler_id: Optional[int] = None
    handle_result: Optional[str] = None
    handled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    @classmethod
    def find_pending(cls, limit: int = 100):
        """查询待处理的风控预警"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"""SELECT * FROM {cls.table_alias}
                  WHERE status = '待处理'
                  ORDER BY severity DESC, created_at DESC
                  LIMIT %s"""
        results = db.execute(sql, (limit,))
        return [cls(**row) for row in results]

    @classmethod
    def find_by_customer_id(cls, customer_id: int, limit: int = 50):
        """查询指定客户的风控预警历史"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"""SELECT * FROM {cls.table_alias}
                  WHERE customer_id = %s
                  ORDER BY created_at DESC
                  LIMIT %s"""
        results = db.execute(sql, (customer_id, limit))
        return [cls(**row) for row in results]

    @classmethod
    def find_by_rule_id(cls, rule_id: str, days: int = 30):
        """查询指定规则的触发历史（支持规则效果分析）"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"""SELECT * FROM {cls.table_alias}
                  WHERE rule_id = %s
                  AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                  ORDER BY created_at DESC"""
        results = db.execute(sql, (rule_id, days))
        return [cls(**row) for row in results]
