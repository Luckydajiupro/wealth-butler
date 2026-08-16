"""客服知识检索业务服务。"""
import json

from app.WealthButler.Repository.faqCollectionModel import FaqCollectionModel
from app.WealthButler.Repository.policyCollectionModel import PolicyCollectionModel
from app.WealthButler.Repository.productCollectionModel import ProductCollectionModel
from app.WealthButler.Service.ollamaEmbeddingService import OllamaEmbeddingService


class KnowledgeService:
    """根据知识类型路由到对应 Milvus 集合。"""

    COLLECTIONS = {
        "fin_faq_collection": FaqCollectionModel,
        "fin_product_collection": ProductCollectionModel,
        "fin_policy_collection": PolicyCollectionModel,
    }

    OUTPUT_FIELDS = {
        "fin_faq_collection": ["text", "metadata"],
        "fin_product_collection": ["text", "metadata"],
        "fin_policy_collection": ["text", "metadata"],
    }

    @classmethod
    def retrieve(cls, query: str, collection: str, top_k: int) -> list[dict]:
        if collection not in cls.COLLECTIONS:
            raise ValueError(f"不支持的知识集合: {collection}")

        model = cls.COLLECTIONS[collection]
        vector = OllamaEmbeddingService.embed(query)
        fields = cls.OUTPUT_FIELDS[collection]

        # 当前重导入的三个集合统一为 text + metadata + embedding，未包含稀疏向量字段。
        raw_results = model.search(
            data=vector,
            anns_field="embedding",
            limit=top_k,
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            output_fields=fields,
        )
        raw_results = raw_results[0] if raw_results and isinstance(raw_results[0], list) else raw_results

        return [cls._normalize_hit(collection, item) for item in raw_results]

    @staticmethod
    def _normalize_hit(collection: str, hit: dict) -> dict:
        entity = hit.get("entity", hit)
        score = float(hit.get("score", hit.get("distance", 0.0)))
        text = entity.get("text", "")
        metadata = KnowledgeService._parse_metadata(entity.get("metadata"))
        if collection == "fin_faq_collection":
            title = metadata.get("question") or text or "FAQ"
            content = metadata.get("answer") or text
        elif collection == "fin_product_collection":
            title = metadata.get("product_name") or text[:100] or "产品说明"
            content = text
        else:
            title = metadata.get("title") or text[:100] or "政策法规"
            content = text
        return {
            "id": str(hit.get("id", entity.get("id", ""))),
            "title": title,
            "content": content,
            "source_file": (
                metadata.get("source")
                or metadata.get("source_file")
                or metadata.get("policy_source")
                or {
                    "fin_faq_collection": "高频问答对.txt",
                    "fin_product_collection": "个人理财产品手册.md",
                }.get(collection, "")
            ),
            "score": round(score, 4),
            "metadata": metadata,
        }

    @staticmethod
    def _parse_metadata(value) -> dict:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}
