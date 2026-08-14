from typing import Optional, ClassVar, List
from pydantic import Field
from app.Base.Repository.base.baseVDB import BaseVDBModel


class CustomerMemoryCollectionModel(BaseVDBModel):
    """
    客户长期记忆集合（纯稠密向量语义检索）
    使用场景：所有Agent的长期记忆召回
    检索策略：TopK=5, 阈值=0.6
    """

    # 主键
    id: Optional[int] = Field(
        default=0,
        json_schema_extra={
            'is_primary': True,
            'auto_id': True

            
        }
    )

    # 客户ID
    customer_id: Optional[int] = Field(
        default=0
    )

    # 记忆类型
    memory_type: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 50
        }
    )

    # 记忆内容
    content: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 2000
        }
    )

    # 来源会话ID
    session_id: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 64
        }
    )

    # 来源Agent类型
    agent_type: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 50
        }
    )

    # 重要性评分（0-1）
    importance: Optional[float] = Field(
        default=0.5
    )

    # 创建时间戳
    created_at: Optional[int] = Field(
        default=0
    )

    # 最后访问时间戳
    last_accessed_at: Optional[int] = Field(
        default=0
    )

    # 访问次数
    access_count: Optional[int] = Field(
        default=0
    )

    # 稠密向量字段（本地Ollama bge-m3，1024维）
    embedding: Optional[List[float]] = Field(
        default=[],
        json_schema_extra={
            'dim': 1024
        }
    )

    # 集合配置
    collection_alias: ClassVar[str] = "fin_customer_memory_collection"
    description: ClassVar[str] = "客户长期记忆集合（纯稠密向量）"
    auto_create_collection: ClassVar[bool] = True

    # 向量索引配置（HNSW + COSINE）
    _vector_fields_config: ClassVar[dict] = {
        'index_type': 'HNSW',
        'metric_type': 'COSINE',
        'params': {"M": 16, "efConstruction": 200}
    }
