"""投顾助手 Agent。

Agent 负责把理财顾问的自然语言请求编排为：读取上下文 → 适当性过滤 →
GraphRAG 查询 → 融合/多因子排序 → LLM 生成推荐理由。确定性业务逻辑放在
AdvisorService，避免在 Agent 中直接读写数据库。
"""

import json
import logging
from typing import Any, Callable, Dict, Optional

from app.Base.Ai.base.baseAgent import ReActAgent, UserMessages
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
            from app.Base.Ai.llms.qwenLlm import get_default_qwen_llm

            llm = get_default_qwen_llm()
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
        """投顾是单一推荐管线，意图分类仅用于判断是否需要澄清。"""
        recommendation_words = ("推荐", "产品", "基金", "配置", "组合", "分散", "行业")
        hit = any(word in text for word in recommendation_words)
        return ("recommend", 0.85 if hit else 0.60)

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
            top_k=5,
        )
        context = recommendation["context"]
        ranked = recommendation["recommendations"]
        graph_result = recommendation["graph"]
        if not graph_result.get("success"):
            # 图谱故障不能绕过适当性过滤；排序只降级为无图谱信号。
            logger.warning("GraphRAG 降级: %s", graph_result.get("error"))
            graph_result = {"success": False, "graph_score": 0.0, "diversity_score": 0.0, "nodes": [], "edges": []}
        self.last_metadata = {
            "customer_id": customer_id,
            "graph_signals": {
                "diversity_score": graph_result.get("diversity_score", 0.0),
                "node_count": len(graph_result.get("nodes", [])),
                "edge_count": len(graph_result.get("edges", [])),
                "query_success": graph_result.get("success", False),
            },
            "recommendations": ranked,
            "admission_tier": "仅预约" if any(item.get("suitability", {}).get("admission_tier") == "仅预约" for item in ranked) else "可执行",
        }

        evidence = {
            "customer_id": customer_id,
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
        messages = list(messages)
        messages.append(
            UserMessages(
                prompt=(
                    "以下是系统已完成的确定性过滤、图谱查询和排序结果。请只基于这些证据回答，"
                    "不要重新猜测风险等级或产品字段：\n" + json.dumps(evidence, ensure_ascii=False, default=str)
                )
            )
        )
        try:
            response = self._call_llm(messages)
            return self._extract_text_content(response) or self._fallback_text(ranked, context)
        except Exception as exc:
            logger.warning("投顾理由生成失败，返回确定性结果: %s", exc)
            return self._fallback_text(ranked, context)

    def _run_loop(self, messages: list[dict], **kwargs: Any) -> str:
        """覆盖 ReAct 默认循环，固定执行投顾确定性管线，避免 LLM 跳过合规过滤。"""
        customer_id = kwargs.get("customer_id")
        if not customer_id:
            raise ValueError("投顾助手必须传入 customer_id")
        query = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                query = message.get("content", "")
                break
        self._total_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        return self._handle_recommend(messages, customer_id=int(customer_id), query=query)

    def run(self, user_input: str, **kwargs: Any):
        """复用 BaseAgent.run，并把推荐审计信息放到 AgentResult.metadata。"""
        self.last_metadata = {}
        result = super().run(user_input, **kwargs)
        result.metadata = self.last_metadata
        return result

    @staticmethod
    def _fallback_text(ranked: list[dict], context: dict) -> str:
        risk_level = (context.get("risk_assessment") or {}).get("risk_level", "未知")
        if not ranked:
            return f"客户当前有效风险评估等级为{risk_level}，没有找到通过适当性过滤的在售产品。"
        lines = [f"客户当前有效风险评估等级为{risk_level}，推荐结果如下："]
        for index, item in enumerate(ranked, 1):
            tier = item.get("suitability", {}).get("admission_tier", "可执行")
            lines.append(
                f"{index}. {item.get('product_name', '未命名产品')}（{item.get('risk_level', '未知')}，"
                f"综合分 {item.get('score', 0):.3f}，{tier}）"
            )
        lines.append("以上结果仅供理财顾问参考，实际操作仍需遵循适当性和风险揭示流程。")
        return "\n".join(lines)
