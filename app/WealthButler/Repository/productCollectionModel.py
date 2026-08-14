from typing import Optional, ClassVar, List
from pydantic import Field
from Base.Repository.base.baseVDB import BaseVDBModel


class ProductCollectionModel(BaseVDBModel):
    """
    产品说明集合（混合检索：稠密向量0.7 + BM25稀疏向量0.3）
    使用场景：客服Agent/投顾Agent产品咨询
    检索策略：TopK=5, 阈值=0.7
    """

    # 主键
    id: Optional[int] = Field(
        default=0,
        json_schema_extra={
            'is_primary': True,
            'auto_id': True
        }
    )

    # 产品名称
    product_name: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 200
        }
    )

    # 产品代码
    product_code: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 50
        }
    )

    # BM25文本字段（用于生成稀疏向量）
    content: Optional[str] = Field(
        default="",
        json_schema_extra={
            'enable_match': True,
            'enable_analyzer': True,
            'max_length': 65535
        }
    )

    # 产品类型
    product_type: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 50
        }
    )

    # 风险等级
    risk_level: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 10
        }
    )

    # 来源
    source: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 200
        }
    )

    # 更新时间
    updated_at: Optional[int] = Field(
        default=0
    )

    # 稀疏向量字段（基于content字段BM25生成）
    content_sparse: Optional[List[float]] = Field(
        default=[],
        json_schema_extra={
            'is_sparse_vector': True,
            'bm25_source_field': 'content'
        }
    )

    # 稠密向量字段（本地Ollama bge-m3，1024维）
    embedding: Optional[List[float]] = Field(
        default=[],
        json_schema_extra={
            'dim': 1024
        }
    )

    # 集合配置
    collection_alias: ClassVar[str] = "fin_product_collection"
    description: ClassVar[str] = "产品说明集合（混合检索）"
    auto_create_collection: ClassVar[bool] = True

    # 向量索引配置（HNSW + COSINE）
    _vector_fields_config: ClassVar[dict] = {
        'index_type': 'HNSW',
        'metric_type': 'COSINE',
        'params': {"M": 16, "efConstruction": 200}
    }
