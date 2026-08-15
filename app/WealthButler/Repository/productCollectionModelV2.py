from typing import Optional, ClassVar, List
from pydantic import Field
from app.Base.Repository.base.baseVDB import BaseVDBModel


class ProductCollectionModelV2(BaseVDBModel):
    """
    产品资料集合 V2（稠密向量 + BM25稀疏向量混合检索）

    使用场景：产品咨询Agent的产品信息检索
    检索策略：混合检索（稠密向量0.7 + BM25稀疏向量0.3），TopK=5
    新增功能：支持jieba中文分词的BM25稀疏向量
    """

    # 主键（自增）
    id: Optional[int] = Field(
        default=None,
        json_schema_extra={
            'is_primary': True,
            'auto_id': True
        }
    )

    # 文本内容（用于BM25检索）
    text: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 65535,
            'enable_analyzer': True,
            'enable_match': True,
            'analyzer_params': {
                'type': 'jieba'  # 使用jieba中文分词
            }
        }
    )

    # 元数据（JSON格式存储业务字段）
    metadata: Optional[dict] = Field(
        default={},
        json_schema_extra={
            'max_length': 65535
        }
    )

    # 稠密向量字段（本地Ollama bge-m3，1024维）
    embedding: Optional[List[float]] = Field(
        default=[],
        json_schema_extra={
            'dim': 1024
        }
    )

    # BM25稀疏向量字段（通过Function自动从text生成）
    text_sparse: Optional[dict] = Field(
        default=None,
        json_schema_extra={
            'is_sparse_vector': True,
            'is_function_output': True,
            'bm25_source_field': 'text'
        }
    )

    # 集合配置
    collection_alias: ClassVar[str] = "fin_product_collection"
    description: ClassVar[str] = "产品资料集合（稠密+BM25混合检索）"
    auto_create_collection: ClassVar[bool] = True

    # 稠密向量索引配置
    _vector_fields_config: ClassVar[dict] = {
        'index_type': 'HNSW',
        'metric_type': 'COSINE',
        'params': {"M": 16, "efConstruction": 200}
    }
