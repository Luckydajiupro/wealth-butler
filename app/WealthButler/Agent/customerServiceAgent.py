"""智能客服 Agent：真实 LLM + Milvus RAG + MySQL 持久化。"""
import json
import logging
import re
import time
from typing import Any, Optional
from uuid import uuid4

from app.Base.Ai.base.baseAgent import AgentResult, ReActAgent
from app.Base.Ai.llms.qwenLlm import get_default_qwen_llm
from app.WealthButler.Prompts.customerServicePrompts import (
    ANSWER_PROMPT,
    FALLBACK_MESSAGE,
    INTENT_CLASSIFY_PROMPT,
    SYSTEM_PROMPT,
    TRANSFER_MESSAGE,
)
from app.WealthButler.Service.customerService import CustomerService
from app.WealthButler.Service.workOrderService import WorkOrderService
from app.WealthButler.Tools.knowledgeRetrievalTool import KnowledgeRetrievalTool
from app.WealthButler.Tools.profileExtractTool import ProfileExtractTool
from app.WealthButler.Tools.workOrderTool import WorkOrderTool

logger = logging.getLogger(__name__)


class CustomerServiceAgent(ReActAgent):
    """面向客户的只读客服 Agent。"""

    INTENT_THRESHOLD = 0.6
    RETRIEVAL_THRESHOLDS = {
        "fin_faq_collection": 0.75,
        "fin_product_collection": 0.70,
        "fin_policy_collection": 0.70,
    }
    VALID_INTENTS = {
        "product_consult", "policy_explain", "faq", "chitchat", "transfer_to_human"
    }

    def __init__(
        self,
        llm: Optional[Any] = None,
        knowledge_tool: Optional[KnowledgeRetrievalTool] = None,
        profile_tool: Optional[ProfileExtractTool] = None,
        customer_service: Optional[CustomerService] = None,
        work_order_service: Optional[WorkOrderService] = None,
        validate_customer: bool = True,
        **kwargs: Any,
    ):
        self.customer_service = customer_service or CustomerService()
        self.knowledge_tool = knowledge_tool or KnowledgeRetrievalTool()
        self.profile_tool = profile_tool or ProfileExtractTool()
        self.work_order_tool = WorkOrderTool(service=work_order_service)
        self.validate_customer = validate_customer
        self._sessions: dict[str, list[dict]] = {}
        self._session_owners: dict[str, int] = {}

        super().__init__(
            llm=llm or get_default_qwen_llm(),
            name="CustomerServiceAgent",
            system_prompt=SYSTEM_PROMPT,
            tools=[self.knowledge_tool, self.profile_tool, self.work_order_tool],
            max_iterations=3,
            **kwargs,
        )

    def classify_intent(self, question: str) -> tuple[str, float]:
        """调用真实 LLM 返回五类意图和置信度，异常时使用保守规则降级。"""
        try:
            content = self._chat([
                {"role": "system", "content": "你只负责意图分类，并严格输出 JSON。"},
                {"role": "user", "content": INTENT_CLASSIFY_PROMPT.format(user_input=question)},
            ])
            parsed = self._parse_json_object(content)
            intent = str(parsed.get("intent", ""))
            confidence = float(parsed.get("confidence", 0.0))
            if intent not in self.VALID_INTENTS:
                raise ValueError(f"未知意图: {intent}")
            return intent, min(max(confidence, 0.0), 1.0)
        except Exception as error:
            logger.warning("LLM 意图分类失败，进入保守降级: %s", error)
            return self._fallback_intent(question)

    def run(
        self,
        user_input: str,
        customer_id: int,
        session_id: Optional[str] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """执行分类、检索、回答、转人工和会话归档。"""
        started = time.time()
        session_id = session_id or str(uuid4())
        if self.validate_customer:
            self.customer_service.validate_customer(customer_id)
        self._bind_session(session_id, customer_id)
        self._sessions.setdefault(session_id, []).append({"role": "user", "content": user_input})

        tool_calls: list[dict] = []
        metadata: dict = {"source_refs": [], "session_id": session_id}
        intent, confidence = self.classify_intent(user_input)
        metadata.update({"intent": intent, "intent_confidence": confidence})

        profile_result = self.profile_tool.run(conversation_text=user_input, customer_id=customer_id)
        if isinstance(profile_result, dict) and profile_result.get("extracted_attrs"):
            tool_calls.append({"name": self.profile_tool.name, "result": profile_result})

        if confidence < self.INTENT_THRESHOLD:
            return self._transfer_to_human(
                user_input, customer_id, session_id, tool_calls, metadata, started, FALLBACK_MESSAGE
            )
        if intent == "transfer_to_human":
            return self._transfer_to_human(
                user_input, customer_id, session_id, tool_calls, metadata, started, TRANSFER_MESSAGE
            )
        if intent == "chitchat":
            answer = self._generate_answer(
                user_input,
                context="普通寒暄，不包含任何金融业务事实。",
                session_id=session_id,
            )
            return self._complete(answer, tool_calls, metadata, started, session_id, customer_id, False)

        collection = {
            "product_consult": "fin_product_collection",
            "policy_explain": "fin_policy_collection",
            "faq": "fin_faq_collection",
        }[intent]
        top_k = 3 if collection == "fin_faq_collection" else 5
        results = self.knowledge_tool.run(query=user_input, collection=collection, top_k=top_k)
        if not isinstance(results, list):
            raise RuntimeError(f"知识检索返回格式错误: {results}")
        tool_calls.append({
            "name": self.knowledge_tool.name,
            "args": {"collection": collection, "top_k": top_k},
            "result": results,
        })

        threshold = self.RETRIEVAL_THRESHOLDS[collection]
        if not results or results[0]["score"] < threshold:
            return self._transfer_to_human(
                user_input, customer_id, session_id, tool_calls, metadata, started, FALLBACK_MESSAGE
            )

        metadata["source_refs"] = [
            {key: result[key] for key in ("title", "source_file", "score")}
            for result in results
        ]
        context = "\n\n".join(
            f"【{result['title']}】\n{result['content']}\n来源：{result['source_file']}"
            for result in results
        )
        answer = self._generate_answer(user_input, context=context, session_id=session_id)
        return self._complete(answer, tool_calls, metadata, started, session_id, customer_id, False)

    def _generate_answer(self, question: str, context: str, session_id: str) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self._current_history(session_id=session_id, limit=6))
        messages.append({
            "role": "user",
            "content": ANSWER_PROMPT.format(context=context, user_input=question),
        })
        return self._chat(messages).strip()

    def _transfer_to_human(
        self,
        question: str,
        customer_id: int,
        session_id: str,
        tool_calls: list[dict],
        metadata: dict,
        started: float,
        message: str,
    ) -> AgentResult:
        ticket = self.work_order_tool.run(
            customer_id=customer_id,
            intent_summary=question[:500],
            priority="中",
            session_id=session_id,
        )
        if not isinstance(ticket, dict) or not ticket.get("id"):
            raise RuntimeError(f"转人工工单创建失败: {ticket}")
        tool_calls.append({"name": self.work_order_tool.name, "result": ticket})
        metadata["transfer_ticket_id"] = ticket["id"]
        return self._complete(message, tool_calls, metadata, started, session_id, customer_id, True)

    def _complete(
        self,
        output: str,
        tool_calls: list[dict],
        metadata: dict,
        started: float,
        session_id: str,
        customer_id: int,
        transferred: bool,
    ) -> AgentResult:
        self._sessions[session_id].append({"role": "assistant", "content": output})
        archive_id = self.customer_service.archive_conversation(
            session_id=session_id,
            customer_id=customer_id,
            messages=self._sessions[session_id],
            transferred_to_human=transferred,
        )
        metadata["conversation_archive_id"] = archive_id
        return AgentResult(
            success=True,
            output=output,
            tool_calls=tool_calls,
            iterations=2 if metadata.get("source_refs") else 1,
            duration_ms=int((time.time() - started) * 1000),
            token_usage=self._total_token_usage or None,
            metadata=metadata,
        )

    def _chat(self, messages: list[dict]) -> str:
        response = self.llm.model_client.chat.completions.create(
            model=self.llm.model_name,
            messages=messages,
            temperature=0.1,
        )
        if response.usage:
            self._total_token_usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return response.choices[0].message.content or ""

    def _bind_session(self, session_id: str, customer_id: int) -> None:
        self._session_owners.setdefault(session_id, customer_id)
        if self._session_owners[session_id] != customer_id:
            raise ValueError("会话不属于当前客户")

    def _current_history(self, session_id: str, limit: int) -> list[dict]:
        return self._sessions.get(session_id, [])[-limit:]

    @staticmethod
    def _parse_json_object(content: str) -> dict:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise ValueError("模型未返回 JSON 对象")
        return json.loads(match.group(0))

    @staticmethod
    def _fallback_intent(question: str) -> tuple[str, float]:
        text = question.lower()
        if any(word in text for word in ("人工", "投诉", "申购", "赎回", "转账", "购买", "办理")):
            return "transfer_to_human", 0.80
        if any(word in text for word in ("政策", "适当性", "合规", "保本", "风险揭示")):
            return "policy_explain", 0.65
        if any(word in text for word in ("产品", "理财", "基金", "风险等级", "说明书")):
            return "product_consult", 0.65
        if any(word in text for word in ("电话", "热线", "服务时间", "营业时间", "流程")):
            return "faq", 0.65
        if any(word in text for word in ("你好", "您好", "谢谢", "再见")):
            return "chitchat", 0.65
        return "chitchat", 0.0

    def get_session_messages(self, session_id: str) -> list[dict]:
        return list(self._sessions.get(session_id, []))

    def get_session_owner(self, session_id: str) -> Optional[int]:
        return self._session_owners.get(session_id)
