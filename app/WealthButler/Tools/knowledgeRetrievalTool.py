"""客服 RAG 知识检索工具。"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.Base.Ai.base.baseTool import BaseTool
from app.WealthButler.Service.knowledgeService import KnowledgeService


CollectionName = Literal[
    "fin_faq_collection",
    "fin_product_collection",
    "fin_policy_collection",
]


class KnowledgeRetrievalArgs(BaseModel):
    query: str = Field(..., min_length=1, description="客户问题或检索文本")
    collection: CollectionName = Field(..., description="目标知识集合")
    top_k: int = Field(default=3, ge=1, le=5, description="返回条数")


class KnowledgeRetrievalTool(BaseTool):
    """调用 KnowledgeService 检索 Milvus，不在 Tool 层处理数据库细节。"""

    name = "KnowledgeRetrieval"
    description = "检索 FAQ、产品说明或政策法规知识，并返回带来源与分数的结果。"
    args_schema = KnowledgeRetrievalArgs

    def __init__(self, service: Optional[type[KnowledgeService]] = None):
        super().__init__()
        self.service = service or KnowledgeService

    def execute(self, query: str, collection: CollectionName, top_k: int = 3) -> list[dict]:
        return self.service.retrieve(query=query, collection=collection, top_k=top_k)
