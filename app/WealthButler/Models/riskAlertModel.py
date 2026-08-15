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
      `severity` ENUM('低','中','高','严重') NOT NULL COMMENT '严重程度',
      `confidence` DECIMAL(4,3) NOT NULL COMMENT '置信度0-1',
      `trigger_details` JSON COMMENT '触发详情（违反条件列表）',
      `related_transaction_id` BIGINT COMMENT '关联交易ID',
      `status` ENUM('待处理','处理中','已确认','误报') DEFAULT '待处理' COMMENT '处理状态',
      `need_override` TINYINT(1) DEFAULT 0 COMMENT '是否需要管理员裁决',
      `handler_id` INT COMMENT '处理人ID（员工ID）',
      `handle_result` TEXT COMMENT '处理结果记录',
      `handled_at` DATETIME COMMENT '处理完成时间',
      `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
      `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
      PRIMARY KEY (`id`),
      KEY `idx_customer_id` (`customer_id`),
      KEY `idx_rule_id` (`rule_id`),
      KEY `idx_status` (`status`),
      KEY `idx_severity` (`severity`),
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
    need_override: bool = False
    handler_id: Optional[int] = None
    handle_result: Optional[str] = None
    handled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

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

    @classmethod
    def find_by_filters(
        cls,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        need_override: Optional[bool] = None,
        limit: int = 20,
        offset: int = 0
    ):
        """根据条件筛选风险预警列表"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return [], 0

        conditions = []
        params = []

        if status:
            conditions.append("status = %s")
            params.append(status)
        if severity:
            conditions.append("severity = %s")
            params.append(severity)
        if need_override is not None:
            conditions.append("need_override = %s")
            params.append(1 if need_override else 0)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 查询总数
        count_sql = f"SELECT COUNT(*) as cnt FROM {cls.table_alias} WHERE {where_clause}"
        count_result = db.execute(count_sql, tuple(params))
        total = count_result[0]['cnt'] if count_result else 0

        # 查询数据
        data_sql = f"""SELECT * FROM {cls.table_alias}
                       WHERE {where_clause}
                       ORDER BY severity DESC, created_at DESC
                       LIMIT %s OFFSET %s"""
        data_params = params + [limit, offset]
        results = db.execute(data_sql, tuple(data_params))

        return [cls(**row) for row in results], total
