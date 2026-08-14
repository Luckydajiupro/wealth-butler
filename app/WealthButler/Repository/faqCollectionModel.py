from typing import Optional, ClassVar, List
from pydantic import Field
from app.Base.Repository.base.baseVDB import BaseVDBModel


class FaqCollectionModel(BaseVDBModel):
    """
    FAQ问答集合（纯稠密向量检索）
    使用场景：客服Agent高频问题匹配
    检索策略：TopK=3, 阈值=0.75
    """

    # 主键
    id: Optional[int] = Field(
        default=0,
        json_schema_extra={
            'is_primary': True,
            'auto_id': True
        }
    )

    # FAQ问题
    question: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 500
        }
    )

    # FAQ答案
    answer: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 2000
        }
    )

    # 来源（便于追溯）
    source: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 200
        }
    )

    # 分类标签
    category: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 100
        }
    )

    # 更新时间（时间戳）
    updated_at: Optional[int] = Field(
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
    collection_alias: ClassVar[str] = "fin_faq_collection"
    description: ClassVar[str] = "FAQ问答集合（纯稠密向量）"
    auto_create_collection: ClassVar[bool] = True

    # 向量索引配置（HNSW + COSINE）
    _vector_fields_config: ClassVar[dict] = {
        'index_type': 'HNSW',
        'metric_type': 'COSINE',
        'params': {"M": 16, "efConstruction": 200}
    }
