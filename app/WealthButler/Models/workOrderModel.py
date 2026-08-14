from Base.Repository.base.baseDBModel import BaseDBModel
from typing import Optional, ClassVar
from datetime import datetime


class WorkOrderModel(BaseDBModel):
    """
    通用业务工单表
    包含工单类型、来源、状态、优先级、处理记录等字段
    """

    table_alias: ClassVar[str] = "biz_work_order"

    create_table_sql: ClassVar[str] = f"""
    CREATE TABLE `biz_work_order` (
      `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
      `order_no` VARCHAR(32) NOT NULL COMMENT '工单编号',
      `order_type` ENUM('风控预警','投诉','咨询','账户变更','业务申请','系统故障') NOT NULL COMMENT '工单类型',
      `source` ENUM('客户提交','系统生成','转人工','主动外呼') NOT NULL COMMENT '工单来源',
      `customer_id` INT COMMENT '客户ID',
      `title` VARCHAR(200) NOT NULL COMMENT '工单标题',
      `description` TEXT COMMENT '工单描述',
      `priority` ENUM('低','中','高','紧急') DEFAULT '中' COMMENT '优先级',
      `status` ENUM('待分配','处理中','待审核','已完成','已关闭') DEFAULT '待分配' COMMENT '工单状态',
      `handler_id` INT COMMENT '当前处理人ID',
      `related_entity_type` VARCHAR(50) COMMENT '关联实体类型（transaction/alert/conversation）',
      `related_entity_id` BIGINT COMMENT '关联实体ID',
      `handle_records` JSON COMMENT '处理记录数组',
      `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
      `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
      `closed_at` DATETIME COMMENT '关闭时间',
      PRIMARY KEY (`id`),
      UNIQUE KEY `uk_order_no` (`order_no`),
      KEY `idx_customer_id` (`customer_id`),
      KEY `idx_order_type` (`order_type`),
      KEY `idx_status` (`status`),
      KEY `idx_handler_id` (`handler_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='通用业务工单表';
    """

    # Pydantic字段定义
    id: Optional[int] = None
    order_no: str
    order_type: str
    source: str
    customer_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    priority: str = "中"
    status: str = "待分配"
    handler_id: Optional[int] = None
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[int] = None
    handle_records: Optional[list] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    @classmethod
    def find_by_order_no(cls, order_no: str):
        """根据工单编号查询"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return None
        sql = f"SELECT * FROM {cls.table_alias} WHERE order_no = %s"
        results = db.execute(sql, (order_no,))
        return cls(**results[0]) if results else None

    @classmethod
    def find_pending(cls, order_type: str = None, limit: int = 100):
        """查询待处理工单"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        if order_type:
            sql = f"""SELECT * FROM {cls.table_alias}
                      WHERE status IN ('待分配', '处理中')
                      AND order_type = %s
                      ORDER BY priority DESC, created_at ASC
                      LIMIT %s"""
            results = db.execute(sql, (order_type, limit))
        else:
            sql = f"""SELECT * FROM {cls.table_alias}
                      WHERE status IN ('待分配', '处理中')
                      ORDER BY priority DESC, created_at ASC
                      LIMIT %s"""
            results = db.execute(sql, (limit,))
        return [cls(**row) for row in results]

    @classmethod
    def find_by_customer_id(cls, customer_id: int, limit: int = 50):
        """查询客户的工单历史"""
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
