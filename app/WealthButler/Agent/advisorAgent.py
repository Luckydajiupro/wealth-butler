"""投顾助手 Agent。

Agent 负责把理财顾问的自然语言请求编排为：读取上下文 → 适当性过滤 →
GraphRAG 查询 → 融合/多因子排序 → LLM 生成推荐理由。确定性业务逻辑放在
AdvisorService，避免在 Agent 中直接读写数据库。
"""

import json
import logging
import re
from typing import Any, Callable, Dict, Optional

from app.Base.Ai.base.baseAgent import AssistantMessages, DBMemory, ReActAgent, UserMessages
from app.WealthButler.Prompts.advisorPrompts import ADVISOR_SYSTEM_PROMPT
from app.WealthButler.Service.advisorService import AdvisorService
from app.WealthButler.Tools.graphQueryTool import GraphQueryTool
from app.WealthButler.Tools.suitabilityCheckTool import SuitabilityCheckTool

logger = logging.getLogger(__name__)


class AdvisorAgent(ReActAgent):
    """面向理财顾问的 GraphRAG 投顾助手。"""

    def __init__(
        self,
        llm: Any = None,
        service: Optional[AdvisorService] = None,
        graph_tool: Optional[GraphQueryTool] = None,
        suitability_tool: Optional[SuitabilityCheckTool] = None,
        **kwargs: Any,
    ):
        if llm is None:
            # 延迟初始化默认模型，避免仅导入业务模块时强制读取 LLM 配置。
            from app.Base.Ai.llms.deepseekLlm import get_default_deepseek_llm

            llm = get_default_deepseek_llm()
        self.service = service or AdvisorService()
        self.graph_tool = graph_tool or GraphQueryTool(llm=llm)
        self.suitability_tool = suitability_tool or SuitabilityCheckTool()
        self.last_metadata: Dict[str, Any] = {}
        super().__init__(
            llm=llm,
            name=kwargs.pop("name", "AdvisorAgent"),
            system_prompt=kwargs.pop("system_prompt", ADVISOR_SYSTEM_PROMPT),
            tools=[self.graph_tool, self.suitability_tool],
            max_iterations=kwargs.pop("max_iterations", 4),
            **kwargs,
        )

    def classify_intent(self, text: str) -> tuple[str, float]:
        """Deterministic routing keeps write requests out of the read-only advisor."""
        normalized = text.strip().lower()
        read_only_request = any(word in normalized for word in (
            "不执行", "不要执行", "无需执行", "只读", "核验", "分析", "查询", "说明", "判断",
        ))
        if not read_only_request and any(phrase in normalized for phrase in (
            "执行申购", "办理申购", "提交申购", "确认申购", "代客户申购", "帮客户申购",
            "执行赎回", "办理赎回", "提交赎回", "确认赎回", "代客户赎回", "帮客户赎回",
            "执行转账", "办理转账", "提交转账", "下单", "买入", "卖出", "执行交易", "办理业务",
        )):
            return "operation_request", 0.98
        if any(phrase in normalized for phrase in (
            "怎么样", "好不好", "值得", "对比", "区别", "哪个更",
            "产品详情", "产品风险", "费率", "起投", "净值", "适配性", "适当性",
        )):
            return "product_explain", 0.92
        if "推荐" in normalized or any(phrase in normalized for phrase in (
            "配置一款", "配置几款", "适合什么", "适合哪", "选什么产品", "做个方案", "配置方案",
            "产品方案", "配置建议", "理财建议", "匹配产品", "合适的产品", "合适产品", "有什么适合",
            "怎么配置", "如何配置", "建议配置", "建议买什么", "产品组合",
        )):
            return "recommend", 0.95
        if any(word in normalized for word in (
            "组合诊断", "持仓分析", "分析客户", "分析一下", "资产配置", "行业集中", "分散度", "分散配置",
            "风险等级", "持仓", "适当性核验", "需要核验", "客户画像", "客户情况", "客户的情况", "客户资料",
            "风险承受", "资产结构", "资产分布", "持仓情况", "组合情况", "看看客户", "看看这个客户", "了解客户",
        )):
            return "portfolio_analysis", 0.95
        if any(word in normalized for word in (
            "介绍", "说明", "费率", "起投", "期限", "净值", "产品详情", "产品风险",
            "怎么样", "好不好", "值得", "对比", "区别", "哪个更", "如何看", "适配性", "适当性",
        )):
            return "product_explain", 0.90
        if any(word in normalized for word in ("你好", "您好", "谢谢", "再见")):
            return "chitchat", 0.95
        return "clarify", 0.40

    def _resolve_contextual_intent(
        self,
        messages: list[dict],
        query: str,
        intent: str,
        confidence: float,
    ) -> tuple[str, float, str]:
        """让省略主语的追问继承最近一轮投顾任务。"""
        if not any(phrase in query for phrase in (
            "为什么", "为何", "怎么得出", "依据是什么", "什么依据", "理由是什么",
            "这样匹配", "这样推荐", "这么配", "详细说说", "展开说说", "分别说说",
            "那第一个", "那第二个", "这些产品", "它们",
        )):
            return intent, confidence, query

        forced_recommend = any(phrase in query for phrase in (
            "这样匹配", "这样推荐", "这么配", "这些产品", "分别说说理由",
        ))

        previous_user = ""
        previous_assistant = ""
        previous_recommend_query = ""
        for message in reversed(messages[:-1]):
            role = message.get("role")
            content = str(message.get("content") or "")
            if role == "assistant" and not previous_assistant:
                previous_assistant = content
            elif role == "user" and not previous_user:
                previous_user = content
            if role == "user" and not previous_recommend_query:
                previous_intent, _ = self.classify_intent(content)
                if previous_intent == "recommend":
                    previous_recommend_query = content
            if previous_user and previous_assistant and (previous_recommend_query or not forced_recommend):
                break

        if forced_recommend and previous_recommend_query:
            return "recommend", 0.90, f"{previous_recommend_query}\n追问：{query}"

        if previous_user:
            previous_intent, _ = self.classify_intent(previous_user)
            if forced_recommend:
                return "recommend", 0.90, query
            if previous_intent in {"recommend", "portfolio_analysis", "product_explain"}:
                return previous_intent, 0.88, f"{previous_user}\n追问：{query}"

        if forced_recommend:
            return "recommend", 0.90, query

        if "推荐结果如下" in previous_assistant or "配置建议" in previous_assistant:
            return "recommend", 0.85, query
        if "持仓市值合计" in previous_assistant or "图谱行业多样性" in previous_assistant:
            return "portfolio_analysis", 0.85, query
        if "适当性结论" in previous_assistant:
            return "product_explain", 0.85, query
        return intent, 0.40, query

    @staticmethod
    def _recommendation_limit(query: str) -> int:
        match = re.search(r"([1-5一二三四五])\s*(?:款|个)", query)
        if not match:
            return 5
        number_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}
        value = match.group(1)
        return int(value) if value.isdigit() else number_map[value]

    def _get_handler(self, intent: str) -> Callable[..., Any]:
        return self._handle_recommend

    def _intent_threshold(self) -> float:
        return 0.65

    def _scenario_name(self) -> str:
        return "advisor_recommendation"

    def _handle_recommend(self, messages: list[dict], customer_id: int, query: str) -> str:
        """执行推荐管线并让 LLM 生成面向理财顾问的解释。"""
        recommendation = self.service.recommend_products(
            customer_id=customer_id,
            query=query or "行业分散度和持仓关联产品",
            graph_query=self.graph_tool.execute,
            top_k=self._recommendation_limit(query),
        )
        context = recommendation["context"]
        ranked = recommendation["recommendations"]
        graph_result = recommendation["graph"]
        if not graph_result.get("success"):
            # 图谱故障不能绕过适当性过滤；排序只降级为无图谱信号。
            logger.warning("GraphRAG 降级: %s", graph_result.get("error"))
            graph_result = {"success": False, "graph_score": 0.0, "diversity_score": 0.0, "nodes": [], "edges": []}
        self.last_metadata = {
            "audit_applicable": True,
            "audit_kind": "recommendation",
            "customer_id": customer_id,
            "graph_signals": {
                "diversity_score": graph_result.get("diversity_score", 0.0),
                "node_count": len(graph_result.get("nodes", [])),
                "edge_count": len(graph_result.get("edges", [])),
                "query_success": graph_result.get("success", False),
            },
            "recommendations": ranked,
            "admission_tier": self._aggregate_admission_tier(ranked),
        }

        evidence = {
            "risk_assessment": context.get("risk_assessment"),
            "profile_context": context.get("profile", {}),
            "holdings": context.get("holdings", []),
            "graph": {
                "diversity_score": graph_result.get("diversity_score", 0.0),
                "nodes": graph_result.get("nodes", [])[:50],
                "edges": graph_result.get("edges", [])[:50],
            },
            "recommendations": ranked,
        }
        fallback = self._fallback_text(ranked, context)
        return self._answer_from_evidence(
            messages,
            evidence,
            "回答理财顾问当前的推荐或追问。逐个解释产品与客户风险、流动性、偏好和现有持仓的匹配依据；明确这是只读建议，不代表已办理交易。",
            fallback,
        )

    def _handle_portfolio_analysis(self, messages: list[dict], customer_id: int, query: str) -> str:
        context = self.service.load_customer_context(customer_id)
        products = self.service.load_products()
        context["holdings"] = self.service._enrich_holdings(context.get("holdings", []), products)
        graph_result = self.graph_tool.execute(customer_id=customer_id, depth=2, query_intent=query)
        if not isinstance(graph_result, dict) or not graph_result.get("success"):
            graph_result = {"success": False, "diversity_score": 0.0, "nodes": [], "edges": []}
        self.last_metadata = {
            "audit_applicable": True,
            "audit_kind": "portfolio_analysis",
            "customer_id": customer_id,
            "graph_signals": {
                "diversity_score": graph_result.get("diversity_score", 0.0),
                "node_count": len(graph_result.get("nodes", [])),
                "edge_count": len(graph_result.get("edges", [])),
                "query_success": graph_result.get("success", False),
            },
            "recommendations": [],
            "admission_tier": "仅分析",
        }
        evidence = {
            "risk_assessment": context.get("risk_assessment"),
            "profile_context": context.get("profile", {}),
            "holdings": context.get("holdings", []),
            "graph": graph_result,
        }
        fallback = self._portfolio_fallback(context, graph_result)
        return self._answer_from_evidence(
            messages,
            evidence,
            "回答理财顾问当前的客户画像或持仓追问。结论必须基于有效风评、四维画像、资产结构和持仓证据，说明数据缺口和需要人工确认的事项。",
            fallback,
        )

    def _handle_product_explain(self, messages: list[dict], customer_id: int, query: str) -> str:
        context = self.service.load_customer_context(customer_id)
        products = self.service.load_products()
        matched = []
        for product in products:
            searchable = " ".join(str(product.get(key) or "") for key in (
                "product_code", "product_name", "product_type",
            ))
            if any(value and str(value) in query for value in (
                product.get("product_code"), product.get("product_name"), product.get("product_type"),
            )) or query in searchable:
                matched.append(product)
        if not matched:
            matched = self._resolve_products_from_history(messages, products, query)
        if not matched:
            self.last_metadata = {"audit_applicable": False, "intent": "product_explain"}
            return "请提供具体产品名称或产品代码，我会基于在售产品资料和客户有效风评进行说明。"
        annotated = self.service.evaluate_products_suitability(
            customer_id,
            matched[:5],
            assessment=context.get("risk_assessment") or {},
        )
        self.last_metadata = {
            "audit_applicable": True,
            "audit_kind": "product_explanation",
            "customer_id": customer_id,
            "graph_signals": {},
            "recommendations": annotated,
            "admission_tier": self._aggregate_admission_tier(annotated),
        }
        fallback = self._product_explain_fallback(annotated)
        evidence = {
            "risk_assessment": context.get("risk_assessment"),
            "products": annotated,
        }
        return self._answer_from_evidence(
            messages,
            evidence,
            "回答理财顾问当前的产品说明或追问。只能使用产品证据和客户有效风评，说清风险、起投、流动性、适当性及资料缺口，不得承诺收益。",
            fallback,
        )

    @staticmethod
    def _resolve_products_from_history(
        messages: list[dict],
        products: list[dict],
        query: str,
    ) -> list[dict]:
        """Resolve ordinal follow-ups such as '第一个产品' from the latest answer."""
        ordinal_match = re.search(r"第\s*([一二三四五1-5])\s*(?:个|款)?", query)
        if not ordinal_match:
            return []
        ordinal_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}
        ordinal = ordinal_map.get(ordinal_match.group(1), int(ordinal_match.group(1)) if ordinal_match.group(1).isdigit() else 0)
        for message in reversed(messages[:-1]):
            if message.get("role") != "assistant":
                continue
            content = str(message.get("content") or "")
            mentioned = []
            for product in products:
                name = str(product.get("product_name") or "")
                position = content.find(name) if name else -1
                if position >= 0:
                    mentioned.append((position, product))
            mentioned.sort(key=lambda item: item[0])
            if len(mentioned) >= ordinal:
                return [mentioned[ordinal - 1][1]]
        return []

    def _answer_from_evidence(
        self,
        messages: list[dict],
        evidence: dict,
        instruction: str,
        fallback: str,
    ) -> str:
        evidence_messages = list(messages)
        evidence_messages.append(UserMessages(prompt=(
            instruction
            + " 只能使用以下系统证据，使用纯文本，不使用 Markdown。"
            + "不得输出客户ID或内部技术字段；不得自行改写或推翻 suitability 中的适当性结论：\n"
            + json.dumps(evidence, ensure_ascii=False, default=str)
        )))
        try:
            response = self.llm.model_client.chat.completions.create(
                model=self.llm.model_name,
                messages=evidence_messages,
                temperature=0.2,
                max_tokens=1200,
                extra_body={"thinking": {"type": "disabled"}},
            )
            if getattr(response, "usage", None):
                self._total_token_usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            return self._extract_text_content(response) or fallback
        except Exception as exc:
            logger.warning("投顾证据回答生成失败，返回确定性结果: %s", exc)
            return fallback

    def _run_loop(self, messages: list[dict], **kwargs: Any) -> str:
        """Route supported read-only intents before entering deterministic pipelines."""
        customer_id = kwargs.get("customer_id")
        if not customer_id:
            raise ValueError("投顾助手必须传入 customer_id")
        query = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                query = message.get("content", "")
                break
        self._total_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        intent, confidence = self.classify_intent(query)
        intent, confidence, routed_query = self._resolve_contextual_intent(
            messages, query, intent, confidence
        )
        if intent == "operation_request":
            self.last_metadata = {"audit_applicable": False, "intent": intent, "intent_confidence": confidence}
            return "这属于申购、赎回或其他业务办理事项，不在理财顾问职责范围内。请转交客户经理/运营，由业务操作助手按权限和二次确认流程办理。"
        if intent == "chitchat":
            self.last_metadata = {"audit_applicable": False, "intent": intent, "intent_confidence": confidence}
            return "您好，当前客户已就绪。我可以协助进行持仓组合诊断、产品推荐和适当性说明。"
        if intent == "clarify":
            self.last_metadata = {"audit_applicable": False, "intent": intent, "intent_confidence": confidence}
            return "我还不能确定你的投顾目标。你可以说明是要查看当前客户画像、诊断持仓组合、生成配置方案，还是分析某个具体产品。"
        if intent == "portfolio_analysis":
            return self._handle_portfolio_analysis(messages, int(customer_id), routed_query)
        if intent == "product_explain":
            return self._handle_product_explain(messages, int(customer_id), routed_query)
        return self._handle_recommend(messages, customer_id=int(customer_id), query=routed_query)

    def run(self, user_input: str, **kwargs: Any):
        """复用 BaseAgent.run，并把推荐审计信息放到 AgentResult.metadata。"""
        self.last_metadata = {}
        result = super().run(user_input, **kwargs)
        result.metadata = self.last_metadata
        if isinstance(self.memory, DBMemory):
            self.memory.save_conversation(
                question=user_input,
                answer=result.output,
                ai_model=getattr(self.llm, "model_name", None),
                ai_agent=self.name,
                status="success" if result.success else "error",
                error_msg=result.error_msg,
                duration_ms=result.duration_ms,
            )
        else:
            self.memory.add_message(UserMessages(prompt=user_input))
            self.memory.add_message(AssistantMessages(prompt=result.output))
        return result

    @staticmethod
    def _aggregate_admission_tier(products: list[dict]) -> str:
        tiers = {
            item.get("suitability", {}).get("admission_tier", "不可执行")
            for item in products
        }
        if not products or not tiers or tiers == {"不可执行"}:
            return "不可执行"
        if len(tiers) == 1:
            return next(iter(tiers))
        return "混合（逐产品确认）"

    @staticmethod
    def _portfolio_fallback(context: dict, graph_result: dict) -> str:
        assessment = context.get("risk_assessment") or {}
        profile = context.get("profile") or {}
        holdings = context.get("holdings") or []
        total_value = sum(float(item.get("current_value") or 0) for item in holdings)
        grouped: dict[str, float] = {}
        for item in holdings:
            group = str(item.get("product_type") or "其他产品")
            grouped[group] = grouped.get(group, 0.0) + float(item.get("current_value") or 0)
        allocation_text = "暂无持仓结构数据"
        if total_value > 0 and grouped:
            allocation_text = "、".join(
                f"{name}{value / total_value * 100:.1f}%"
                for name, value in sorted(grouped.items(), key=lambda pair: pair[1], reverse=True)[:4]
            )
        experience_score = profile.get("dimension2_score")
        experience_text = (
            f"投资经验维度{float(experience_score):.1f}/25分"
            if experience_score is not None else "投资经验画像数据不足"
        )
        graph_text = (
            f"图谱行业多样性分数为{float(graph_result.get('diversity_score', 0.0)):.2f}。"
            if graph_result.get("success") else
            "图谱数据暂不可用，当前无法确认行业集中度。"
        )
        return (
            f"客户当前有效风险等级为{assessment.get('risk_level', '未评估')}，"
            f"共持有{len(holdings)}个产品，持仓市值合计{total_value:.2f}元。"
            f"持仓结构为：{allocation_text}；{experience_text}。"
            f"{graph_text}请结合客户流动性需求和最新风险揭示进行人工复核。"
        )

    @staticmethod
    def _product_explain_fallback(products: list[dict]) -> str:
        lines = []
        for product in products:
            suitability = product.get("suitability", {})
            period_return = product.get("period_return")
            return_text = "近90天净值数据不足" if period_return is None else f"近90天区间收益{period_return * 100:+.2f}%"
            tier = suitability.get("admission_tier", "不可执行")
            advisor_tier = "风险适配（仅供投顾建议）" if tier == "可执行" else tier
            lines.append(
                f"{product.get('product_name', '未命名产品')}：风险等级{product.get('risk_level', '未知')}，"
                f"起投金额{product.get('min_investment', '未提供')}元，{return_text}；"
                f"适当性结论为{advisor_tier}，原因：{suitability.get('reason', '资料不足')}。"
            )
        return "\n".join(lines)

    @staticmethod
    def _fallback_text(ranked: list[dict], context: dict) -> str:
        risk_level = (context.get("risk_assessment") or {}).get("risk_level", "未知")
        if not ranked:
            return f"客户当前有效风险评估等级为{risk_level}，没有找到通过适当性过滤的在售产品。"
        lines = [f"客户当前有效风险评估等级为{risk_level}，推荐结果如下："]
        for index, item in enumerate(ranked, 1):
            tier = item.get("suitability", {}).get("admission_tier", "可执行")
            advisor_tier = "风险适配（仅供投顾建议）" if tier == "可执行" else tier
            factors = item.get("factor_scores") or {}
            reasons = [item.get("suitability", {}).get("reason")]
            if float(factors.get("diversification_score", 0) or 0) >= 0.75:
                reasons.append("有助于分散现有持仓")
            if float(factors.get("term_score", 0) or 0) >= 0.65:
                reasons.append("赎回周期较符合客户流动性偏好")
            if float(factors.get("preference_score", 0) or 0) >= 0.65:
                reasons.append("产品类型与客户偏好匹配")
            reason_text = "；".join(reason for reason in reasons if reason) or "综合风险、期限、偏好和持仓分散度后入选"
            lines.append(
                f"{index}. {item.get('product_name', '未命名产品')}（{item.get('risk_level', '未知')}，"
                f"综合分 {item.get('score', 0):.3f}，{advisor_tier}）。匹配依据：{reason_text}。"
            )
        lines.append("以上结果仅供理财顾问与客户沟通，不会自动创建或执行交易；实际办理需转交客户经理/运营并完成风险揭示。")
        return "\n".join(lines)
