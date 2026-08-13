from datetime import datetime
from typing import Optional, ClassVar, List

from pydantic import Field

from Base.Repository.models.moduleDbModel import BaseModuleDBModel


class BaseKeywordModel(BaseModuleDBModel):
    """
    系统关键词/名词实体模型
    """
    table_alias: ClassVar[str] = "base_keyword"
    create_table_sql: ClassVar[str] = f"""
    CREATE TABLE `{table_alias}` (
        -- 核心主键
        `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',

        -- 关键词基本信息
        `keyword_name` VARCHAR(100) NOT NULL COMMENT '名词实体名称',
        `keyword_code` VARCHAR(50) NOT NULL COMMENT '名词实体编码',
        `keyword_desc` TEXT COMMENT '名词实体解释',
        `semantic_desc` TEXT COMMENT '语义描述',

        `keyword_synonyms` VARCHAR(100) COMMENT '同义词',

        -- 状态与类型
        `status` TINYINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '状态：0-禁用，1-可用，2-可用但禁止同步到VDB',
        `type` VARCHAR(50) DEFAULT 'COMMON' COMMENT '类型：COMMON-通用，TECH-技术，BUSINESS-业务等',
        `source` VARCHAR(50) DEFAULT 'MANUAL' COMMENT '来源：MANUAL-人工录入，IMPORT-导入，AI-自动生成',

        -- 审计字段
        `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        `created_by` BIGINT UNSIGNED DEFAULT NULL COMMENT '创建人ID',
        `updated_by` BIGINT UNSIGNED DEFAULT NULL COMMENT '更新人ID',

        -- 主键与索引
        PRIMARY KEY (`id`),
        KEY `idx_keyword_name` (`keyword_name`),
        KEY `idx_status` (`status`),
        KEY `idx_type` (`type`),
        KEY `idx_source` (`source`)

    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统关键词/名词实体表';
    """

    # 字段定义
    id: Optional[int] = Field(None, description="主键ID")
    keyword_name: str = Field(..., description="名词实体名称")
    keyword_code: str = Field(..., description="名词实体编码")
    keyword_desc: Optional[str] = Field(None, description="名词实体解释")
    semantic_desc: Optional[str] = Field(None, description="语义描述")
    keyword_synonyms: Optional[str] = Field(None, description="同义词")
    status: int = Field(1, description="状态：0-禁用，1-可用，2-可用但禁止同步到VDB")
    type: str = Field('0', description="类型：0-通用，TECH-技术，BUSINESS-业务等")
    source: str = Field('MANUAL', description="来源：MANUAL-人工录入，IMPORT-导入，AI-自动生成")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")
    created_by: Optional[int] = Field(None, description="创建人ID")
    updated_by: Optional[int] = Field(None, description="更新人ID")


    @property
    def is_active(self) -> bool:
        """
        判断关键词是否可用

        Returns:
            True-可用，False-禁用
        """
        return self.status == 1 or self.status == 2

    @property
    def can_sync_to_vdb(self) -> bool:
        """
        判断关键词是否可以同步到向量数据库

        Returns:
            True-可以同步，False-不可以同步
        """
        return self.status == 1

    @classmethod
    def get_by_keyword_code(cls, keyword_code: str):
        """
        根据关键词编码获取记录

        Args:
            keyword_code: 关键词编码

        Returns:
            关键词记录对象，未找到返回 None
        """
        try:
            cls._ensure_table_exists()
            result = cls.find_by(keyword_code=keyword_code, limit=1)
            return result[0] if result else None
        except Exception as e:
            logger = __import__('logging').getLogger(__name__)
            logger.error(f"get_by_keyword_code({keyword_code}) 失败：{str(e)}")
            return None

    @classmethod
    def get_by_type(cls, keyword_type: str, status: int = 1, limit: int = 100) -> List['BaseKeywordModel']:
        """
        根据类型获取关键词列表

        Args:
            keyword_type: 关键词类型
            status: 状态筛选（可选，默认1-可用）
            limit: 返回数量限制

        Returns:
            关键词记录列表
        """
        try:
            cls._ensure_table_exists()
            return cls.find_by(
                type=keyword_type,
                status=status,
                limit=limit,
                order_by="created_at",
                order="DESC"
            )
        except Exception as e:
            logger = __import__('logging').getLogger(__name__)
            logger.error(f"get_by_type({keyword_type}) 失败：{str(e)}")
            return []

    @classmethod
    def search_by_name(cls, keyword_name: str, limit: int = 20) -> List['BaseKeywordModel']:
        """
        根据关键词名称模糊搜索

        Args:
            keyword_name: 关键词名称（支持模糊匹配）
            limit: 返回数量限制

        Returns:
            关键词记录列表
        """
        try:
            cls._ensure_table_exists()
            db = cls.get_db_connection()
            if db is None:
                return []

            table_name = cls.get_table_name_with_db()
            sql = f"SELECT * FROM {table_name} WHERE `keyword_name` LIKE %s AND `status` != 0 ORDER BY `created_at` DESC LIMIT %s"
            results = db.execute(sql, (f"%{keyword_name}%", limit))

            return [cls(**result) for result in results] if results else []
        except Exception as e:
            logger = __import__('logging').getLogger(__name__)
            logger.error(f"search_by_name({keyword_name}) 失败：{str(e)}")
            return []

    @classmethod
    def get_all_active(cls, limit: int = 1000) -> List['BaseKeywordModel']:
        """
        获取所有可用的关键词

        Args:
            limit: 返回数量限制

        Returns:
            可用关键词记录列表
        """
        try:
            cls._ensure_table_exists()
            return cls.find_by(
                status=1,
                limit=limit,
                order_by="created_at",
                order="DESC"
            )
        except Exception as e:
            logger = __import__('logging').getLogger(__name__)
            logger.error(f"get_all_active() 失败：{str(e)}")
            return []

    @classmethod
    def get_can_sync_to_vdb(cls, limit: int = 1000) -> List['BaseKeywordModel']:
        """
        获取可以同步到VDB的关键词列表

        Args:
            limit: 返回数量限制

        Returns:
            可同步关键词记录列表
        """
        try:
            cls._ensure_table_exists()
            return cls.find_by(
                status=1,
                limit=limit,
                order_by="updated_at",
                order="DESC"
            )
        except Exception as e:
            logger = __import__('logging').getLogger(__name__)
            logger.error(f"get_can_sync_to_vdb() 失败：{str(e)}")
            return []



if __name__ == '__main__':
    # 创建表
    res = BaseKeywordModel.get_all_active()
    for i in res :
        print(i.keyword_name)
    print("✓ 表创建成功")
