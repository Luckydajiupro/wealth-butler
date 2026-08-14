from Base.Repository.base.baseDBModel import BaseDBModel
from typing import Optional, ClassVar
from datetime import datetime


class KnowledgeMetaModel(BaseDBModel):
    """
    知识元数据表
    包含知识来源、类型、版本、审核状态、Milvus集合映射等字段
    """

    table_alias: ClassVar[str] = "fin_knowledge_meta"

    create_table_sql: ClassVar[str] = f"""
    CREATE TABLE `fin_knowledge_meta` (
      `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
      `knowledge_type` ENUM('FAQ','产品说明书','政策法规','培训资料') NOT NULL COMMENT '知识类型',
      `collection_name` VARCHAR(50) NOT NULL COMMENT 'Milvus集合名',
      `title` VARCHAR(200) NOT NULL COMMENT '知识标题',
      `source` VARCHAR(200) COMMENT '来源',
      `version` VARCHAR(20) COMMENT '版本号',
      `file_path` VARCHAR(500) COMMENT '原始文件路径',
      `chunk_count` INT DEFAULT 0 COMMENT '切片数量',
      `status` ENUM('待审核','已上线','已下线') DEFAULT '待审核' COMMENT '审核状态',
      `approver_id` INT COMMENT '审核人ID',
      `approved_at` DATETIME COMMENT '审核时间',
      `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
      `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
      PRIMARY KEY (`id`),
      KEY `idx_knowledge_type` (`knowledge_type`),
      KEY `idx_collection_name` (`collection_name`),
      KEY `idx_status` (`status`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识元数据表';
    """

    # Pydantic字段定义
    id: Optional[int] = None
    knowledge_type: str
    collection_name: str
    title: str
    source: Optional[str] = None
    version: Optional[str] = None
    file_path: Optional[str] = None
    chunk_count: int = 0
    status: str = "待审核"
    approver_id: Optional[int] = None
    approved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def find_by_collection(cls, collection_name: str, status: str = "已上线"):
        """根据Milvus集合名查询知识列表"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"""SELECT * FROM {cls.table_alias}
                  WHERE collection_name = %s
                  AND status = %s
                  ORDER BY updated_at DESC"""
        results = db.execute(sql, (collection_name, status))
        return [cls(**row) for row in results]

    @classmethod
    def find_by_type(cls, knowledge_type: str, status: str = "已上线"):
        """根据知识类型查询"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"""SELECT * FROM {cls.table_alias}
                  WHERE knowledge_type = %s
                  AND status = %s
                  ORDER BY updated_at DESC"""
        results = db.execute(sql, (knowledge_type, status))
        return [cls(**row) for row in results]

    @classmethod
    def find_pending_approval(cls):
        """查询待审核的知识"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"""SELECT * FROM {cls.table_alias}
                  WHERE status = '待审核'
                  ORDER BY created_at ASC"""
        results = db.execute(sql)
        return [cls(**row) for row in results]
