"""投顾助手确定性业务逻辑。

这里集中处理数据读取、适当性过滤和排序，Agent 只负责对话编排与理由生成。
"""

import logging
from typing import Any, Callable, Dict, Iterable, Optional

from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
from app.WealthButler.Models.holdingsModel import HoldingsModel
from app.WealthButler.Models.productModel import ProductModel
from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel

logger = logging.getLogger(__name__)


class AdvisorService:
    """投顾推荐服务，所有数据库访问均为只读。"""

    MAX_PRODUCT_RISK = {"C1": "R2", "C2": "R3", "C3": "R4", "C4": "R5", "C5": "R5"}
    PRIVATE_PRODUCT_TYPES = {"私募基金", "私募证券投资基金", "信托", "保险", "资管计划", "专户理财"}
    FACTOR_WEIGHTS = {
        "return_score": 0.30,
        "risk_match_score": 0.25,
        "term_score": 0.15,
        "diversification_score": 0.15,
        "graph_signal": 0.15,
    }

    def __init__(
        self,
        product_loader: Optional[Callable[[], Iterable[Any]]] = None,
        assessment_loader: Optional[Callable[[int], Any]] = None,
        profile_loader: Optional[Callable[[int], Any]] = None,
        holdings_loader: Optional[Callable[[int], Iterable[Any]]] = None,
        vector_search: Optional[Callable[[str], Dict[str, float]]] = None,
    ):
        self.product_loader = product_loader or (lambda: ProductModel.get_all(limit=100, offset=0, order_by="updated_at", order="DESC"))
        self.assessment_loader = assessment_loader or RiskAssessmentModel.find_valid_by_customer_id
        self.profile_loader = profile_loader or CustomerProfileModel.find_by_customer_id
        self.holdings_loader = holdings_loader or HoldingsModel.find_by_customer_id
        self.vector_search = vector_search

    def load_customer_context(self, customer_id: int) -> Dict[str, Any]:
        """读取推荐所需上下文；画像读取失败只影响个性化，不阻塞主流程。"""
        context: Dict[str, Any] = {"customer_id": customer_id, "risk_assessment": None, "profile": {}, "holdings": []}
        try:
            assessment = self.assessment_loader(customer_id)
            context["risk_assessment"] = self._model_to_dict(assessment)
        except Exception as exc:
            logger.warning("读取客户有效风险评估失败: %s", exc)
        try:
            profile = self.profile_loader(customer_id)
            profile_data = self._model_to_dict(profile)
            # 只暴露个性化推荐相关字段，避免把评分过程和内部审计字段送给 LLM。
            context["profile"] = {
                key: profile_data.get(key)
                for key in ("asset_allocation", "product_preference", "memory_units")
                if profile_data.get(key) is not None
            }
        except Exception as exc:
            logger.info("客户画像只读上下文不可用，继续使用非画像数据: %s", exc)
        try:
            context["holdings"] = [self._model_to_dict(item) for item in (self.holdings_loader(customer_id) or [])]
        except Exception as exc:
            logger.warning("读取客户持仓失败: %s", exc)
        return context

    def load_products(self) -> list[dict]:
        """读取在售产品候选，不在此处修改产品数据。"""
        try:
            products = self.product_loader() or []
        except Exception as exc:
            logger.warning("读取产品候选失败: %s", exc)
            return []
        return [
            self._model_to_dict(product)
            for product in products
            if self._value(product, "status", "在售") == "在售"
        ]

    def filter_suitable_products(self, customer_id: int, products: Iterable[dict], assessment: Optional[dict] = None) -> list[dict]:
        """按有效风险评估过滤产品；无有效评估时不放行任何产品。"""
        if assessment is None:
            try:
                assessment = self._model_to_dict(self.assessment_loader(customer_id))
            except Exception as exc:
                logger.warning("适当性过滤读取风险评估失败: %s", exc)
                assessment = {}
        risk_level = assessment.get("risk_level") if assessment else None
        max_risk = self.MAX_PRODUCT_RISK.get(risk_level)
        result = []
        for product in products:
            product_risk = self._value(product, "risk_level")
            product_rank = self._risk_rank(product_risk)
            max_rank = self._risk_rank(max_risk)
            passed = bool(max_rank is not None and product_rank is not None and product_rank <= max_rank)
            admission_tier = "仅预约" if self._value(product, "product_type") in self.PRIVATE_PRODUCT_TYPES else "可执行"
            product = dict(product)
            product["suitability"] = {
                "passed": passed,
                "reason": f"客户{risk_level}适配产品{product_risk}" if passed else "无有效风评或风险等级不适配",
                "requires_disclosure": passed and product_risk in {"R4", "R5"},
                "admission_tier": admission_tier if passed else "不可执行",
            }
            if passed:
                result.append(product)
        return result

    def recommend_products(
        self,
        customer_id: int,
        query: str = "行业分散度和持仓关联产品",
        graph_query: Optional[Callable[..., dict]] = None,
        vector_scores: Optional[Dict[str, float]] = None,
        top_k: int = 5,
    ) -> dict:
        """提供对话入口和结构化接口共同使用的推荐管线。"""
        context = self.load_customer_context(customer_id)
        products = self.load_products()
        suitable = self.filter_suitable_products(
            customer_id,
            products,
            assessment=context.get("risk_assessment") or {},
        )
        graph_result = graph_query(customer_id=customer_id, depth=2, query_intent=query) if graph_query else {}
        if not isinstance(graph_result, dict):
            graph_result = {}
        if vector_scores is None:
            vector_scores = self.retrieve_vector_scores(query)
        ranked = self.rank_products(
            suitable,
            graph_result=graph_result,
            vector_scores=vector_scores,
            context=context,
            top_k=top_k,
        )
        return {"context": context, "graph": graph_result, "recommendations": ranked}

    def retrieve_vector_scores(self, query: str) -> Dict[str, float]:
        """调用现有 Milvus 产品集合获取向量/关键词混合检索分数。"""
        if self.vector_search is not None:
            try:
                return self.vector_search(query) or {}
            except Exception as exc:
                logger.warning("注入的产品向量检索失败: %s", exc)
                return {}
        try:
            from app.Base.Ai.llms.ollamaEmbedding import ollama_embedding
            from app.WealthButler.Repository.productCollectionModel import ProductCollectionModel

            hits = ProductCollectionModel.hybrid_search(
                dense_vector=ollama_embedding(query),
                query_text=query,
                dense_weight=0.7,
                sparse_weight=0.3,
                limit=20,
                output_fields=["product_code"],
            )
            scores: Dict[str, float] = {}
            for hit_group in hits or []:
                group = hit_group if isinstance(hit_group, list) else [hit_group]
                for hit in group:
                    if not isinstance(hit, dict):
                        continue
                    code = hit.get("product_code") or hit.get("entity", {}).get("product_code")
                    raw_score = hit.get("score", hit.get("distance", 0.0))
                    if code and raw_score is not None:
                        scores[str(code)] = self._clamp(raw_score)
            return scores
        except Exception as exc:
            # 本地 embedding 或 Milvus 不可用时，排序仍可依赖图谱和业务因子。
            logger.info("产品向量检索不可用，使用中性向量分: %s", exc)
            return {}

    def rank_products(
        self,
        products: Iterable[dict],
        graph_result: Optional[dict] = None,
        vector_scores: Optional[Dict[str, float]] = None,
        context: Optional[dict] = None,
        top_k: int = 5,
    ) -> list[dict]:
        """先做向量/图谱融合，再按五因子确定性排序。"""
        graph_result = graph_result or {}
        vector_scores = vector_scores or {}
        context = context or {}
        graph_by_product = graph_result.get("product_scores", {})
        overall_graph = float(graph_result.get("graph_score", graph_result.get("diversity_score", 0.0)) or 0.0)
        current_industries = self._holding_industries(context.get("holdings", []))
        ranked = []
        for item in products:
            product = dict(item)
            product_code = str(product.get("product_code", ""))
            product_id = str(product.get("id", ""))
            vector_score = self._clamp(vector_scores.get(product_code, vector_scores.get(product_id, product.get("vector_score", 0.5))))
            graph_score = self._clamp(graph_by_product.get(product_code, graph_by_product.get(product_id, overall_graph)))
            fusion_score = vector_score * 0.6 + graph_score * 0.4
            risk_match_score = self._risk_match_score(context.get("risk_assessment", {}).get("risk_level"), product.get("risk_level"))
            term_score = self._term_score(product.get("redemption_period_days"))
            diversification_score = 1.0 if product.get("industry") and product.get("industry") not in current_industries else 0.5
            factors = {
                "return_score": self._clamp(product.get("return_score", 0.5)),
                "risk_match_score": risk_match_score,
                "term_score": term_score,
                "diversification_score": diversification_score,
                # 融合分作为图谱信号输入，保留向量与图谱两路证据。
                "graph_signal": fusion_score,
            }
            final_score = sum(factors[name] * weight for name, weight in self.FACTOR_WEIGHTS.items())
            product.update(
                {
                    "vector_score": round(vector_score, 4),
                    "graph_score": round(graph_score, 4),
                    "fusion_score": round(fusion_score, 4),
                    "factor_scores": {key: round(value, 4) for key, value in factors.items()},
                    "score": round(final_score, 4),
                }
            )
            ranked.append(product)
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[:top_k]

    @classmethod
    def _risk_match_score(cls, customer_level: Optional[str], product_level: Optional[str]) -> float:
        if not customer_level or not product_level or customer_level not in cls.MAX_PRODUCT_RISK:
            return 0.0
        max_rank = cls._risk_rank(cls.MAX_PRODUCT_RISK[customer_level])
        product_rank = cls._risk_rank(product_level)
        if max_rank is None or product_rank is None:
            return 0.0
        distance = abs(max_rank - product_rank)
        return cls._clamp(1.0 - distance / 4.0)

    @staticmethod
    def _risk_rank(level: Any) -> Optional[int]:
        if isinstance(level, str) and len(level) == 2 and level[0] in {"C", "R"} and level[1].isdigit():
            rank = int(level[1])
            if 1 <= rank <= 5:
                return rank
        return None

    @staticmethod
    def _term_score(days: Any) -> float:
        try:
            return AdvisorService._clamp(1.0 - min(max(float(days or 0), 0.0), 365.0) / 365.0)
        except (TypeError, ValueError):
            return 0.5

    @staticmethod
    def _holding_industries(holdings: Iterable[dict]) -> set[str]:
        return {str(item.get("industry")) for item in holdings if isinstance(item, dict) and item.get("industry")}

    @staticmethod
    def _model_to_dict(value: Any) -> dict:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "model_dump"):
            return value.model_dump()
        return {key: getattr(value, key) for key in dir(value) if not key.startswith("_") and not callable(getattr(value, key))}

    @staticmethod
    def _value(value: Any, key: str, default: Any = None) -> Any:
        return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)

    @staticmethod
    def _clamp(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0
