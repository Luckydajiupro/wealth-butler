from typing import Optional, ClassVar, List
from pydantic import Field
from app.Base.Repository.base.baseVDB import BaseVDBModel


class FaqCollectionModel(BaseVDBModel):
    """FAQ问答集合（纯稠密向量检索）。"""

    id: Optional[int] = Field(
        default=0,
        json_schema_extra={"is_primary": True, "auto_id": True},
    )
    question: Optional[str] = Field(default="", json_schema_extra={"max_length": 500})
    answer: Optional[str] = Field(default="", json_schema_extra={"max_length": 2000})
    source: Optional[str] = Field(default="", json_schema_extra={"max_length": 200})
    category: Optional[str] = Field(default="", json_schema_extra={"max_length": 100})
    updated_at: Optional[int] = Field(default=0)
    embedding: Optional[List[float]] = Field(default=[], json_schema_extra={"dim": 1024})

    collection_alias: ClassVar[str] = "fin_faq_collection"
    description: ClassVar[str] = "FAQ问答集合（纯稠密向量）"
    auto_create_collection: ClassVar[bool] = True
    _vector_fields_config: ClassVar[dict] = {
        "index_type": "HNSW",
        "metric_type": "COSINE",
        "params": {"M": 16, "efConstruction": 200},
    }
