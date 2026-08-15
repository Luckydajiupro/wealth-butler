from app.Base.Repository.base.baseDBModel import BaseDBModel
from typing import Optional, ClassVar
from datetime import datetime
import json


class WorkOrderModel(BaseDBModel):
    """
    业务工单表
    支持客户转介、风险预警、信息变更、转账审核等工单类型
    """

    table_alias: ClassVar[str] = "biz_work_order"

    create_table_sql: ClassVar[str] = f"""
    CREATE TABLE `biz_work_order` (
      `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
      `order_no` VARCHAR(32) NOT NULL COMMENT '工单编号',
      `order_type` ENUM('风控预警','投诉','咨询','账户变更','业务申请','系统故障','客户转介') NOT NULL COMMENT '工单类型',
      `source` ENUM('客户提交','系统生成','转介工单','其他来源') NOT NULL COMMENT '工单来源',
      `customer_id` INT COMMENT '客户ID，关联base_user表',
      `customer_name` VARCHAR(100) COMMENT '客户姓名（冗余字段，避免JOIN）',
      `title` VARCHAR(200) NOT NULL COMMENT '工单标题',
      `description` TEXT COMMENT '工单描述',
      `intent_summary` TEXT COMMENT '意向摘要/业务描述',
      `status` ENUM('待处理','处理中','待审核','已完成','已驳回','未处理','已关闭') DEFAULT '待处理' COMMENT '工单状态',
      `priority` ENUM('低','中','高','紧急') DEFAULT '中' COMMENT '优先级',
      `handled_by` INT COMMENT '处理人ID，关联base_user表',
      `handler_id` INT COMMENT '当前处理人ID',
      `handler_name` VARCHAR(100) COMMENT '处理人姓名（冗余字段）',
      `handled_at` DATETIME COMMENT '领取时间',
      `completed_at` DATETIME COMMENT '完成时间',
      `closed_at` DATETIME COMMENT '关闭时间',
      `related_entity_type` VARCHAR(50) COMMENT '关联实体类型',
      `related_entity_id` BIGINT COMMENT '关联实体ID',
      `handle_records` JSON COMMENT '处理记录（数组）',
      `remark` TEXT COMMENT '备注',
      `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
      `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
      `deleted_at` DATETIME COMMENT '软删除时间',
      PRIMARY KEY (`id`),
      UNIQUE KEY `uk_order_no` (`order_no`),
      KEY `idx_customer_id` (`customer_id`),
      KEY `idx_status` (`status`),
      KEY `idx_order_type` (`order_type`),
      KEY `idx_handled_by` (`handled_by`),
      KEY `idx_handler_id` (`handler_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='通用业务工单表';
    """

    # Pydantic字段定义
    id: Optional[int] = None
    order_no: str
    order_type: str
    source: str = "客户提交"
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    title: str
    description: Optional[str] = None
    intent_summary: Optional[str] = None
    status: str = "待处理"
    priority: str = "中"
    handled_by: Optional[int] = None
    handler_id: Optional[int] = None
    handler_name: Optional[str] = None
    handled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[int] = None
    handle_records: Optional[dict] = None
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    def model_dump(self, **kwargs):
        """重写model_dump，序列化JSON字段"""
        data = super().model_dump(**kwargs)
        if 'handle_records' in data and isinstance(data['handle_records'], (dict, list)):
            data['handle_records'] = json.dumps(data['handle_records'], ensure_ascii=False)
        return data

    @classmethod
    def find_by_filters(
        cls,
        order_type: Optional[str] = None,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
        handled_by: Optional[int] = None,
        limit: int = 20,
        offset: int = 0
    ):
        """根据筛选条件查询工单列表"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return [], 0

        # 构建WHERE条件
        conditions = ["deleted_at IS NULL"]
        params = []

        if order_type:
            conditions.append("order_type = %s")
            params.append(order_type)
        if status:
            conditions.append("status = %s")
            params.append(status)
        if handled_by:
            conditions.append("handled_by = %s")
            params.append(handled_by)
        if keyword:
            conditions.append("intent_summary LIKE %s")
            params.append(f"%{keyword}%")

        where_clause = " AND ".join(conditions)

        # 查询总数
        count_sql = f"SELECT COUNT(*) as total FROM {cls.table_alias} WHERE {where_clause}"
        count_result = db.execute(count_sql, tuple(params))
        total = count_result[0]["total"] if count_result else 0

        # 查询数据
        data_sql = f"""
            SELECT * FROM {cls.table_alias}
            WHERE {where_clause}
            ORDER BY
                CASE priority WHEN '紧急' THEN 1 ELSE 2 END,
                created_at DESC
            LIMIT %s OFFSET %s
        """
        data_params = params + [limit, offset]
        results = db.execute(data_sql, tuple(data_params))

        workorders = [cls(**row) for row in results]
        return workorders, total

    @classmethod
    def find_by_customer_id(cls, customer_id: int, limit: int = 50):
        """查询客户的工单历史"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"""
            SELECT * FROM {cls.table_alias}
            WHERE customer_id = %s AND deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT %s
        """
        results = db.execute(sql, (customer_id, limit))
        return [cls(**row) for row in results]
