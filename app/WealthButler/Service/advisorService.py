"""投顾助手确定性业务逻辑。

这里集中处理数据读取、适当性过滤和排序，Agent 只负责对话编排与理由生成。
"""

import logging
from typing import Any, Callable, Dict, Iterable, Optional

from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
from app.WealthButler.Models.holdingsModel import HoldingsModel
from app.WealthButler.Models.productModel import ProductModel
from app.WealthButler.Models.productNavHistoryModel import ProductNavHistoryModel
from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel

logger = logging.getLogger(__name__)


class AdvisorService:
    """投顾推荐服务，所有数据库访问均为只读。"""

    MAX_PRODUCT_RISK = {"C1": "R2", "C2": "R3", "C3": "R4", "C4": "R5", "C5": "R5"}
    PRIVATE_PRODUCT_TYPES = {"私募基金", "私募证券投资基金", "信托", "保险", "资管计划", "专户理财"}
    FACTOR_WEIGHTS = {
        "return_score": 0.20,
        "risk_match_score": 0.25,
        "term_score": 0.15,
        "diversification_score": 0.15,
        "graph_signal": 0.15,
        "preference_score": 0.10,
    }

    def __init__(
        self,
        product_loader: Optional[Callable[[], Iterable[Any]]] = None,
        assessment_loader: Optional[Callable[[int], Any]] = None,
        profile_loader: Optional[Callable[[int], Any]] = None,
        holdings_loader: Optional[Callable[[int], Iterable[Any]]] = None,
        vector_search: Optional[Callable[[str], Dict[str, float]]] = None,
        nav_history_loader: Optional[Callable[[list[int]], Dict[int, list[dict]]]] = None,
    ):
        self.product_loader = product_loader or (lambda: ProductModel.get_all(limit=100, offset=0, order_by="updated_at", order="DESC"))
        self.assessment_loader = assessment_loader or RiskAssessmentModel.find_valid_by_customer_id
        self.profile_loader = profile_loader or CustomerProfileModel.find_by_customer_id
        self.holdings_loader = holdings_loader or HoldingsModel.find_by_customer_id
        self.vector_search = vector_search
        self.nav_history_loader = nav_history_loader or ProductNavHistoryModel.find_recent_for_products

    @staticmethod
    def advisor_can_access_customer(advisor_id: int, customer_id: int) -> bool:
        """Allow assigned customers or referrals already claimed by this advisor."""
        if advisor_id <= 0 or customer_id <= 0:
            return False
        db = CustomerProfileModel.get_db_connection()
        if db is None:
            return False
        try:
            rows = db.execute(
                """
                SELECT 1 AS allowed
                FROM fin_customer_profile p
                WHERE p.customer_id = %s AND p.advisor_id = %s
                UNION ALL
                SELECT 1 AS allowed
                FROM biz_work_order w
                WHERE w.customer_id = %s AND w.handled_by = %s
                  AND w.status IN ('处理中', '待审核')
                  AND w.deleted_at IS NULL
                  AND (
                      COALESCE(w.intent_summary, w.description, w.title, '') LIKE '%%产品推荐%%'
                      OR COALESCE(w.intent_summary, w.description, w.title, '') LIKE '%%推荐产品%%'
                      OR COALESCE(w.intent_summary, w.description, w.title, '') LIKE '%%配置方案%%'
                      OR COALESCE(w.intent_summary, w.description, w.title, '') LIKE '%%产品配置%%'
                      OR COALESCE(w.intent_summary, w.description, w.title, '') LIKE '%%组合诊断%%'
                      OR COALESCE(w.intent_summary, w.description, w.title, '') LIKE '%%适当性%%'
                  )
                  AND COALESCE(w.intent_summary, w.description, w.title, '') NOT LIKE '%%申购%%'
                  AND COALESCE(w.intent_summary, w.description, w.title, '') NOT LIKE '%%赎回%%'
                LIMIT 1
                """,
                (customer_id, advisor_id, customer_id, advisor_id),
            )
            return bool(rows)
        except Exception as exc:
            logger.error(
                "校验投顾客户范围失败: advisor_id=%s customer_id=%s error=%s",
                advisor_id,
                customer_id,
                exc,
            )
            return False

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
            # 只暴露投顾解释所需的画像结论，不暴露内部审计字段。
            context["profile"] = {
                key: profile_data.get(key)
                for key in (
                    "dimension1_score", "dimension2_score", "dimension3_score", "dimension4_score",
                    "asset_allocation", "product_preference", "memory_units", "confidence_score",
                )
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
        normalized = [
            self._model_to_dict(product)
            for product in products
            if self._value(product, "status", "在售") == "在售"
        ]
        return self._attach_return_scores(normalized)

    def _attach_return_scores(self, products: list[dict]) -> list[dict]:
        product_ids = [int(product["id"]) for product in products if product.get("id")]
        try:
            histories = self.nav_history_loader(product_ids) or {}
        except Exception as exc:
            logger.warning("读取产品净值历史失败，收益因子使用中性分: %s", exc)
            histories = {}

        observed_returns: dict[int, float] = {}
        for product in products:
            product_id = int(product.get("id") or 0)
            rows = histories.get(product_id, [])
            if len(rows) < 2:
                continue
            try:
                first_nav = float(rows[0]["nav"])
                last_nav = float(rows[-1]["nav"])
                if first_nav > 0:
                    observed_returns[product_id] = last_nav / first_nav - 1.0
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue

        values = list(observed_returns.values())
        low = min(values) if values else None
        high = max(values) if values else None
        for product in products:
            product_id = int(product.get("id") or 0)
            period_return = observed_returns.get(product_id)
            if period_return is None:
                product["return_score"] = 0.5
                product["return_source"] = "unavailable"
                product["period_return"] = None
            else:
                product["return_score"] = 0.5 if high == low else self._clamp((period_return - low) / (high - low))
                product["return_source"] = "nav_history_90d"
                product["period_return"] = round(period_return, 6)
        return products

    def filter_suitable_products(self, customer_id: int, products: Iterable[dict], assessment: Optional[dict] = None) -> list[dict]:
        """按有效风险评估过滤产品；无有效评估时不放行任何产品。"""
        return [
            product
            for product in self.evaluate_products_suitability(customer_id, products, assessment)
            if product["suitability"]["passed"]
        ]

    def evaluate_products_suitability(
        self,
        customer_id: int,
        products: Iterable[dict],
        assessment: Optional[dict] = None,
    ) -> list[dict]:
        """Annotate every candidate so explanations can include rejected products."""
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
        context["holdings"] = self._enrich_holdings(context.get("holdings", []), products)
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
            from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2

            hits = ProductCollectionModelV2.hybrid_search(
                dense_vector=ollama_embedding(query),
                query_text=query,
                dense_weight=0.7,
                sparse_weight=0.3,
                limit=20,
                output_fields=["metadata"],
            )
            scores: Dict[str, float] = {}
            for hit_group in hits or []:
                group = hit_group if isinstance(hit_group, list) else [hit_group]
                for hit in group:
                    if not isinstance(hit, dict):
                        continue
                    entity = hit.get("entity", {}) if isinstance(hit.get("entity", {}), dict) else {}
                    metadata = hit.get("metadata") or entity.get("metadata") or {}
                    code = metadata.get("product_code") if isinstance(metadata, dict) else None
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
        industry_weights = graph_result.get("industry_weights", {})
        industry_total = sum(float(value or 0.0) for value in industry_weights.values()) if isinstance(industry_weights, dict) else 0.0
        current_industries = self._holding_industries(context.get("holdings", []))
        ranked = []
        for item in products:
            product = dict(item)
            product_code = str(product.get("product_code", ""))
            product_id = str(product.get("id", ""))
            vector_score = self._clamp(vector_scores.get(product_code, vector_scores.get(product_id, product.get("vector_score", 0.5))))
            explicit_graph_score = graph_by_product.get(product_code, graph_by_product.get(product_id))
            product_industry = product.get("industry")
            if explicit_graph_score is not None:
                graph_score = self._clamp(explicit_graph_score)
            elif product_industry and industry_total > 0:
                # 未持有行业获得最高分；已有行业按其集中度反向计分。
                concentration = float(industry_weights.get(str(product_industry), 0.0) or 0.0) / industry_total
                graph_score = self._clamp(1.0 - concentration)
            else:
                graph_score = self._clamp(overall_graph)
            fusion_score = vector_score * 0.6 + graph_score * 0.4
            risk_match_score = self._risk_match_score(context.get("risk_assessment", {}).get("risk_level"), product.get("risk_level"))
            term_score = self._term_score(
                product.get("redemption_period_days"),
                context.get("profile", {}).get("product_preference", {}),
            )
            diversification_score = 1.0 if product.get("industry") and product.get("industry") not in current_industries else 0.5
            factors = {
                "return_score": self._clamp(product.get("return_score", 0.5)),
                "risk_match_score": risk_match_score,
                "term_score": term_score,
                "diversification_score": diversification_score,
                # 融合分作为图谱信号输入，保留向量与图谱两路证据。
                "graph_signal": fusion_score,
                "preference_score": self._preference_score(product, context.get("profile", {})),
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
    def _term_score(days: Any, preference: Optional[dict] = None) -> float:
        preference_text = AdvisorService._flatten_text(preference or {})
        if not preference_text:
            return 0.5
        try:
            redemption_days = max(float(days or 0), 0.0)
        except (TypeError, ValueError):
            return 0.5
        if any(word in preference_text for word in ("灵活", "随时", "高流动", "短期")):
            return AdvisorService._clamp(1.0 - redemption_days / 90.0)
        if any(word in preference_text for word in ("长期", "养老", "传承")):
            return AdvisorService._clamp(1.0 - abs(redemption_days - 365.0) / 365.0)
        return 0.5

    @staticmethod
    def _preference_score(product: dict, profile: dict) -> float:
        preference_text = AdvisorService._flatten_text(profile.get("product_preference", {}))
        if not preference_text:
            return 0.5
        candidates = (
            product.get("product_type"),
            product.get("industry"),
            product.get("risk_level"),
            product.get("product_name"),
        )
        return 1.0 if any(str(value) in preference_text for value in candidates if value) else 0.5

    @staticmethod
    def _flatten_text(value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(AdvisorService._flatten_text(item) for item in value.values())
        if isinstance(value, list):
            return " ".join(AdvisorService._flatten_text(item) for item in value)
        return str(value or "")

    @staticmethod
    def _enrich_holdings(holdings: Iterable[dict], products: Iterable[dict]) -> list[dict]:
        products_by_id = {
            int(product["id"]): product
            for product in products
            if isinstance(product, dict) and product.get("id")
        }
        enriched = []
        for holding in holdings:
            item = dict(holding)
            product = products_by_id.get(int(item.get("product_id") or 0), {})
            for key in ("product_code", "product_name", "product_type", "risk_level", "industry"):
                if product.get(key) is not None:
                    item[key] = product[key]
            enriched.append(item)
        return enriched

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
            data = value.model_dump()
            record_id = getattr(value, "id", None)
            if record_id is not None:
                data.setdefault("id", record_id)
            return data
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
