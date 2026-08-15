from typing import Optional, ClassVar, List
from pydantic import Field
from app.Base.Repository.base.baseVDB import BaseVDBModel


class PolicyCollectionModelV2(BaseVDBModel):
    """
    政策法规集合 V2（稠密向量 + BM25稀疏向量混合检索）

    使用场景：合规咨询Agent的政策法规检索
    检索策略：混合检索（稠密向量0.7 + BM25稀疏向量0.3），TopK=5
    新增功能：支持jieba中文分词的BM25稀疏向量
    """

    # 主键（自增）
    id: Optional[int] = Field(
        default=0,
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

    # 注：text_sparse稀疏向量字段暂时移除
    # 原因：Milvus Function Output机制尚未完全支持自动BM25计算
    # 当前V2版本仍使用纯稠密向量检索，但Schema已优化为三字段模式

    # 集合配置
    collection_alias: ClassVar[str] = "fin_policy_collection"
    description: ClassVar[str] = "政策法规集合（三字段Schema优化版）"
    auto_create_collection: ClassVar[bool] = True

    # 稠密向量索引配置
    _vector_fields_config: ClassVar[dict] = {
        'index_type': 'HNSW',
        'metric_type': 'COSINE',
        'params': {"M": 16, "efConstruction": 200}
    }
