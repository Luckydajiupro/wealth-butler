from typing import Optional, ClassVar, List
from pydantic import Field
from app.Base.Repository.base.baseVDB import BaseVDBModel


class ProductCollectionModel(BaseVDBModel):
    """产品说明集合（混合检索）。"""

    id: Optional[int] = Field(
        default=0,
        json_schema_extra={"is_primary": True, "auto_id": True},
    )
    product_name: Optional[str] = Field(default="", json_schema_extra={"max_length": 200})
    product_code: Optional[str] = Field(default="", json_schema_extra={"max_length": 50})
    content: Optional[str] = Field(
        default="",
        json_schema_extra={
            "enable_match": True,
            "enable_analyzer": True,
            "max_length": 65535,
        },
    )
    product_type: Optional[str] = Field(default="", json_schema_extra={"max_length": 50})
    risk_level: Optional[str] = Field(default="", json_schema_extra={"max_length": 10})
    source: Optional[str] = Field(default="", json_schema_extra={"max_length": 200})
    updated_at: Optional[int] = Field(default=0)
    content_sparse: Optional[List[float]] = Field(
        default=[],
        json_schema_extra={
            "is_sparse_vector": True,
            "bm25_source_field": "content",
        },
    )
    embedding: Optional[List[float]] = Field(default=[], json_schema_extra={"dim": 1024})

    collection_alias: ClassVar[str] = "fin_product_collection"
    description: ClassVar[str] = "产品说明集合（混合检索）"
    auto_create_collection: ClassVar[bool] = True
    _vector_fields_config: ClassVar[dict] = {
        "index_type": "HNSW",
        "metric_type": "COSINE",
        "params": {"M": 16, "efConstruction": 200},
    }
