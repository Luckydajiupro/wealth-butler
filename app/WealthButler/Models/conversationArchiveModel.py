from app.Base.Repository.base.baseDBModel import BaseDBModel
from typing import Optional, ClassVar
from datetime import datetime


class ConversationArchiveModel(BaseDBModel):
    """
    会话归档表
    包含完整会话记录、摘要、情感标签、归档原因等字段
    """

    table_alias: ClassVar[str] = "conversation_archive"

    create_table_sql: ClassVar[str] = f"""
    CREATE TABLE `conversation_archive` (
      `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
      `session_id` VARCHAR(64) NOT NULL COMMENT '会话ID',
      `customer_id` INT NOT NULL COMMENT '客户ID',
      `agent_type` ENUM('customer_service','advisor','analyst','operator','risk') NOT NULL COMMENT 'Agent类型',
      `message_count` INT NOT NULL DEFAULT 0 COMMENT '消息轮次',
      `messages` JSON NOT NULL COMMENT '完整消息记录数组',
      `summary` TEXT COMMENT '会话摘要',
      `sentiment` ENUM('positive','neutral','negative') COMMENT '情感标签',
      `resolved` TINYINT(1) DEFAULT 0 COMMENT '问题是否解决',
      `transferred_to_human` TINYINT(1) DEFAULT 0 COMMENT '是否转人工',
      `archive_reason` ENUM('会话结束','超时','转人工','用户主动关闭') NOT NULL COMMENT '归档原因',
      `start_time` DATETIME NOT NULL COMMENT '会话开始时间',
      `end_time` DATETIME NOT NULL COMMENT '会话结束时间',
      `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
      PRIMARY KEY (`id`),
      KEY `idx_session_id` (`session_id`),
      KEY `idx_customer_id` (`customer_id`),
      KEY `idx_agent_type` (`agent_type`),
      KEY `idx_start_time` (`start_time`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话归档表';
    """

    # Pydantic字段定义
    id: Optional[int] = None
    session_id: str
    customer_id: int
    agent_type: str
    message_count: int = 0
    messages: list
    summary: Optional[str] = None
    sentiment: Optional[str] = None
    resolved: bool = False
    transferred_to_human: bool = False
    archive_reason: str
    start_time: datetime
    end_time: datetime
    created_at: Optional[datetime] = None

    @classmethod
    def find_by_session_id(cls, session_id: str):
        """根据会话ID查询归档记录"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return None
        sql = f"SELECT * FROM {cls.table_alias} WHERE session_id = %s"
        results = db.execute(sql, (session_id,))
        return cls(**results[0]) if results else None

    @classmethod
    def find_by_customer_id(cls, customer_id: int, limit: int = 50):
        """查询客户的会话历史"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"""SELECT * FROM {cls.table_alias}
                  WHERE customer_id = %s
                  ORDER BY start_time DESC
                  LIMIT %s"""
        results = db.execute(sql, (customer_id, limit))
        return [cls(**row) for row in results]

    @classmethod
    def find_unresolved(cls, agent_type: str = None, days: int = 7):
        """查询未解决的会话（质量监控用）"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        if agent_type:
            sql = f"""SELECT * FROM {cls.table_alias}
                      WHERE resolved = 0
                      AND agent_type = %s
                      AND start_time >= DATE_SUB(NOW(), INTERVAL %s DAY)
                      ORDER BY start_time DESC"""
            results = db.execute(sql, (agent_type, days))
        else:
            sql = f"""SELECT * FROM {cls.table_alias}
                      WHERE resolved = 0
                      AND start_time >= DATE_SUB(NOW(), INTERVAL %s DAY)
                      ORDER BY start_time DESC"""
            results = db.execute(sql, (days,))
        return [cls(**row) for row in results]
