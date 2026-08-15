"""FAQ集合V2模型（三字段Schema）

将FAQ的question/answer/source等字段整合到metadata JSON中
统一使用 id + text + metadata + embedding 的标准Schema
"""
from typing import Optional, ClassVar, List
from pydantic import Field
from app.Base.Repository.base.baseVDB import BaseVDBModel


class FaqCollectionModelV2(BaseVDBModel):
    """
    FAQ问答集合V2（三字段Schema优化版）
    使用场景：客服Agent高频问题匹配
    检索策略：TopK=3, 阈值=0.75
    """

    # 主键（自增）
    id: Optional[int] = Field(
        default=0,
        json_schema_extra={
            'is_primary': True,
            'auto_id': True
        }
    )

    # 全文文本（用于BM25全文检索，当前用于存储Q+A组合文本）
    text: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 65535,
            'enable_analyzer': True,
            'enable_match': True,
            'analyzer_params': {
                'type': 'standard'  # 标准分词器
            }
        }
    )

    # 元数据JSON（存储业务字段）
    # 包含: question, answer, source, category, updated_at
    metadata: Optional[str] = Field(
        default="{}",
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

    # 集合配置
    collection_alias: ClassVar[str] = "fin_faq_collection"
    description: ClassVar[str] = "FAQ问答集合（三字段Schema优化版）"
    auto_create_collection: ClassVar[bool] = True

    # 稠密向量索引配置
    _vector_fields_config: ClassVar[dict] = {
        'index_type': 'HNSW',
        'metric_type': 'COSINE',
        'params': {"M": 16, "efConstruction": 200}
    }
