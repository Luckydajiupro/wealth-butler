"""智能客服 Agent：真实 LLM + Milvus RAG + MySQL 持久化。"""
import json
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional
from uuid import uuid4

from app.Base.Ai.base.baseAgent import AgentResult, ReActAgent
from app.Base.Ai.llms.deepseekLlm import get_default_deepseek_llm
from app.WealthButler.Prompts.customerServicePrompts import (
    ANSWER_PROMPT,
    CLARIFICATION_MESSAGE,
    FALLBACK_MESSAGE,
    INTENT_CLASSIFY_PROMPT,
    KNOWLEDGE_UNAVAILABLE_MESSAGE,
    RISK_ASSESSMENT_MESSAGE,
    SYSTEM_PROMPT,
    TRANSFER_MESSAGE,
)
from app.WealthButler.Service.customerService import CustomerService
from app.WealthButler.Service.workOrderService import WorkOrderService
from app.WealthButler.Tools.knowledgeRetrievalTool import KnowledgeRetrievalTool
from app.WealthButler.Tools.profileExtractTool import ProfileExtractTool
from app.WealthButler.Tools.workOrderTool import WorkOrderTool
from app.WealthButler.Tools.holdingsTool import HoldingsTool
from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel
from app.WealthButler.Models.advisorAllocationPlanModel import AdvisorAllocationPlanModel
from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel

logger = logging.getLogger(__name__)


class CustomerStreamCancelled(Exception):
    """客户端断开后终止客服回答流，不归档不完整回答。"""


class CustomerServiceAgent(ReActAgent):
    """面向客户的只读客服 Agent。"""

    INTENT_THRESHOLD = 0.6
    RETRIEVAL_THRESHOLDS = {
        "fin_faq_collection": 0.55,      # 常见问题检索（从0.75降低）
        "fin_product_collection": 0.55,  # 产品说明检索（从0.70降低）
        "fin_policy_collection": 0.60,   # 政策法规检索（从0.70降低）
    }
    VALID_INTENTS = {
        "product_consult", "policy_explain", "faq", "holdings_query", "risk_assessment",
        "risk_level_query", "suitability_query", "chitchat", "transfer_to_human"
    }

    def __init__(
        self,
        llm: Optional[Any] = None,
        knowledge_tool: Optional[KnowledgeRetrievalTool] = None,
        profile_tool: Optional[ProfileExtractTool] = None,
        holdings_tool: Optional[HoldingsTool] = None,
        customer_service: Optional[CustomerService] = None,
        work_order_service: Optional[WorkOrderService] = None,
        validate_customer: bool = True,
        **kwargs: Any,
    ):
        self.customer_service = customer_service or CustomerService()
        self.knowledge_tool = knowledge_tool or KnowledgeRetrievalTool()
        self.profile_tool = profile_tool or ProfileExtractTool()
        self.holdings_tool = holdings_tool or HoldingsTool()
        self.work_order_tool = WorkOrderTool(service=work_order_service)
        self.validate_customer = validate_customer
        self._sessions: dict[str, list[dict]] = {}
        self._session_owners: dict[str, int] = {}
        self._stream_lock = threading.Lock()
        self._active_stream = None

        super().__init__(
            llm=llm or get_default_deepseek_llm(),
            name="CustomerServiceAgent",
            system_prompt=SYSTEM_PROMPT,
            tools=[self.knowledge_tool, self.profile_tool, self.holdings_tool, self.work_order_tool],
            max_iterations=3,
            **kwargs,
        )

    def classify_intent(self, question: str) -> tuple[str, float]:
        """调用真实 LLM 返回五类意图和置信度，异常时使用保守规则降级。"""
        fast_path = self._fast_path_intent(question)
        if fast_path is not None:
            return fast_path
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

    @staticmethod
    def _fast_path_intent(question: str) -> Optional[tuple[str, float]]:
        """Route clear customer-service intents without an LLM round trip."""
        greeting_words = ("你好", "您好", "嗨")
        business_words = (
            "产品", "基金", "理财", "风险", "政策", "合规", "持仓", "资产", "收益",
            "申购", "赎回", "购买", "转账", "投诉", "人工", "电话", "营业时间",
            "公司", "全称", "名称", "客服热线", "开户", "密码", "银行卡", "账户",
        )
        normalized = question.strip().lower()
        if any(phrase in normalized for phrase in (
            "开始风险测评", "开始风险评估", "进行风险测评", "进行风险评估",
            "重新测评", "重做测评", "重新做风险测评", "打开风险测评",
            "打开风险评估", "打开风险问卷", "测一下风险承受能力",
        )):
            return "risk_assessment", 0.99
        if any(phrase in normalized for phrase in (
            "我的风险等级", "我的风险测评结果", "我的风险评估结果",
            "我的测评等级", "我的风险承受能力", "风险等级是多少",
        )):
            return "risk_level_query", 0.99
        if any(phrase in normalized for phrase in (
            "转人工", "转接人工", "找人工", "我要人工", "找客服", "联系人工", "人工客服", "我要投诉", "提交投诉", "我要申购", "我想申购", "帮我申购",
            "我要找理财顾问", "找理财顾问", "联系理财顾问", "人工理财顾问", "找投顾", "联系投顾",
            "我要追加申购", "我想追加申购", "帮我追加申购",
            "我要赎回", "帮我赎回", "我要购买", "帮我购买", "我要转账", "帮我转账",
            "办理申购", "办理赎回", "办理转账", "修改银行卡", "解绑银行卡",
            "修改个人资料", "修改手机号", "账户被盗", "冻结账户",
        )):
            return "transfer_to_human", 0.98
        if any(phrase in normalized for phrase in (
            "今日收益", "今天收益", "当日收益", "我的持仓", "持仓情况", "总资产",
            "累计收益", "累计盈亏", "总盈亏", "赚了多少", "亏了多少", "持有哪些",
            "买了哪些", "持仓盈亏", "今天的持仓", "持有几个产品", "持有多少个产品",
            "账户资金", "账户资产",
            "几个持仓产品", "多少个持仓产品", "持仓产品数量",
        )):
            return "holdings_query", 0.98
        if any(phrase in normalized for phrase in (
            "我适合什么产品", "适合我的产品", "适合我的理财", "推荐适合我的产品",
            "帮我推荐产品", "帮我做产品配置", "我的产品配置", "产品配置方案",
        )):
            return "suitability_query", 0.99
        if any(phrase in normalized for phrase in (
            "公司名称", "公司全称", "客服电话", "客服热线", "服务时间", "营业时间",
            "怎么开户", "如何开户", "开户流程", "官方网站", "公司总部", "忘记登录密码",
            "忘记密码", "重置密码流程", "确认份额", "几天确认", "申购后", "赎回到账",
        )):
            return "faq", 0.95
        if any(phrase in normalized for phrase in (
            "适当性", "监管政策", "合规要求", "风险揭示", "是否保本", "投资者保护",
            "现金交易", "大额交易", "需要报告", "反洗钱", "风险评估有效期",
        )):
            return "policy_explain", 0.92
        if any(word in normalized for word in (
            "产品", "基金", "理财", "费率", "净值", "起投", "期限", "风险等级", "说明书"
        )):
            return "product_consult", 0.90
        has_greeting = (
            any(word in normalized for word in greeting_words)
            or re.search(r"\b(?:hello|hi)\b", normalized) is not None
        )
        if (
            has_greeting
            and not any(word in normalized for word in business_words)
        ):
            return "chitchat", 0.95
        return None

    def run(
        self,
        user_input: str,
        customer_id: int,
        session_id: Optional[str] = None,
        on_final_chunk: Optional[Callable[[str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """执行分类、检索、回答、转人工和会话归档。"""
        started = time.time()
        session_id = session_id or str(uuid4())
        if self.validate_customer:
            self.customer_service.validate_customer(customer_id)
        self._bind_session(session_id, customer_id)
        self._hydrate_session(session_id, customer_id)
        self._sessions.setdefault(session_id, []).append({"role": "user", "content": user_input})

        tool_calls: list[dict] = []
        metadata: dict = {"source_refs": [], "session_id": session_id}
        resolved_input = user_input
        contextual = self._resolve_contextual_follow_up(
            user_input, self._sessions[session_id][:-1]
        )
        pending_subscription = self._pending_subscription(self._sessions[session_id][:-1])
        pending_redemption = self._pending_redemption(self._sessions[session_id][:-1])
        if (pending_subscription or pending_redemption) and self._looks_like_operation_detail(user_input):
            # 金额/产品的短回复继承同一会话中的申购意图，避免被误判为闲聊。
            contextual = ("transfer_to_human", 0.99, user_input)
        if contextual is not None:
            intent, confidence, resolved_input = contextual
            metadata["contextual_follow_up"] = True
        else:
            intent, confidence = self.classify_intent(user_input)
        metadata.update({"intent": intent, "intent_confidence": confidence})

        if self._should_extract_profile(user_input):
            try:
                profile_result = self.profile_tool.run(
                    conversation_text=user_input,
                    customer_id=customer_id,
                )
                if not isinstance(profile_result, dict):
                    metadata["profile_extraction_failed"] = True
                    logger.error("客服画像提取返回格式错误: customer_id=%s", customer_id)
                elif profile_result.get("extracted_attrs"):
                    tool_calls.append({"name": self.profile_tool.name, "result": profile_result})
            except Exception:
                logger.exception("客服画像提取失败: customer_id=%s", customer_id)
                metadata["profile_extraction_failed"] = True

        # 检测可疑意图并发布事件
        suspicious_result = self._detect_suspicious_intent(user_input, customer_id, session_id)
        if suspicious_result:
            metadata["suspicious_detected"] = True
            metadata["suspicious_type"] = suspicious_result.get("intent_type")

        if confidence < self.INTENT_THRESHOLD:
            metadata["clarification_required"] = True
            return self._complete(
                CLARIFICATION_MESSAGE, tool_calls, metadata, started, session_id, customer_id, False
            )
        if intent == "transfer_to_human":
            if self._is_redemption_request(user_input, self._sessions[session_id][:-1]):
                return self._handle_redemption_request(
                    user_input, customer_id, session_id, tool_calls, metadata, started
                )
            if self._is_subscription_request(user_input, self._sessions[session_id][:-1]):
                return self._handle_subscription_request(
                    user_input, customer_id, session_id, tool_calls, metadata, started
                )
            return self._transfer_to_human(
                user_input, customer_id, session_id, tool_calls, metadata, started, TRANSFER_MESSAGE
            )
        if intent == "chitchat":
            answer = self._generate_answer(
                user_input,
                context="普通寒暄，不包含任何金融业务事实。",
                session_id=session_id,
                on_final_chunk=on_final_chunk,
                is_cancelled=is_cancelled,
            )
            return self._complete(answer, tool_calls, metadata, started, session_id, customer_id, False)

        if intent == "risk_assessment":
            metadata["client_action"] = "open_risk_assessment"
            return self._complete(
                RISK_ASSESSMENT_MESSAGE,
                tool_calls,
                metadata,
                started,
                session_id,
                customer_id,
                False,
            )

        if intent == "risk_level_query":
            try:
                answer, assessment_status = self._risk_level_answer(customer_id)
            except Exception:
                logger.exception("客服读取客户风险测评失败: customer_id=%s", customer_id)
                answer = "暂时无法查询您的风险测评结果，请稍后重试；如需协助，请回复“转人工”。"
                assessment_status = "unavailable"
            metadata["risk_assessment_status"] = assessment_status
            return self._complete(
                answer, tool_calls, metadata, started, session_id, customer_id, False
            )

        if intent == "suitability_query":
            return self._handle_suitability_query(
                user_input, customer_id, session_id, tool_calls, metadata, started
            )

        # 处理持仓查询意图（直接调用工具，不走知识库检索）
        if intent == "holdings_query":
            query_types = self._resolve_holdings_query_types(resolved_input)
            messages = []
            for query_type in query_types:
                holdings_result = self.holdings_tool.execute(
                    query_type=query_type,
                    customer_id=customer_id,
                )
                tool_calls.append({
                    "name": self.holdings_tool.name,
                    "args": {"query_type": query_type, "customer_id": customer_id},
                    "result": holdings_result,
                })
                if not holdings_result.get("success"):
                    error_msg = holdings_result.get("error", "持仓查询失败")
                    return self._complete(
                        f"抱歉，{error_msg}", tool_calls, metadata, started, session_id, customer_id, False
                    )
                messages.append(holdings_result.get("message", "查询成功"))
            metadata["holdings_query_type"] = query_types[0] if len(query_types) == 1 else query_types
            return self._complete(
                "；".join(messages), tool_calls, metadata, started, session_id, customer_id, False
            )

        collection = {
            "product_consult": "fin_product_collection",
            "policy_explain": "fin_policy_collection",
            "faq": "fin_faq_collection",
        }[intent]
        mysql_product_context = ""
        mysql_product_exact = False
        if intent == "product_consult":
            try:
                product_context = self._product_context_from_mysql(user_input)
                mysql_product_context = product_context.get("text", "")
                mysql_product_exact = bool(product_context.get("exact"))
            except Exception:
                logger.exception("客服读取 MySQL 产品事实失败")
        if mysql_product_exact:
            metadata["mysql_product_exact"] = True
            answer = self._generate_answer(
                user_input,
                context=mysql_product_context,
                session_id=session_id,
                on_final_chunk=on_final_chunk,
                is_cancelled=is_cancelled,
            )
            return self._complete(answer, tool_calls, metadata, started, session_id, customer_id, False)
        top_k = 3 if collection == "fin_faq_collection" else 5
        try:
            results = self.knowledge_tool.run(query=user_input, collection=collection, top_k=top_k)
        except Exception:
            logger.exception("客服知识检索失败: collection=%s", collection)
            if mysql_product_context:
                metadata["mysql_product_fallback"] = True
                answer = self._generate_answer(
                    user_input,
                    context=mysql_product_context,
                    session_id=session_id,
                    on_final_chunk=on_final_chunk,
                    is_cancelled=is_cancelled,
                )
                return self._complete(answer, tool_calls, metadata, started, session_id, customer_id, False)
            metadata["knowledge_unavailable"] = True
            return self._complete(
                KNOWLEDGE_UNAVAILABLE_MESSAGE,
                tool_calls,
                metadata,
                started,
                session_id,
                customer_id,
                False,
            )
        if not self._valid_knowledge_results(results):
            logger.error("客服知识检索返回格式错误: collection=%s", collection)
            if mysql_product_context:
                metadata["mysql_product_fallback"] = True
                answer = self._generate_answer(
                    user_input, context=mysql_product_context, session_id=session_id,
                    on_final_chunk=on_final_chunk, is_cancelled=is_cancelled,
                )
                return self._complete(answer, tool_calls, metadata, started, session_id, customer_id, False)
            metadata["knowledge_unavailable"] = True
            return self._complete(
                KNOWLEDGE_UNAVAILABLE_MESSAGE,
                tool_calls,
                metadata,
                started,
                session_id,
                customer_id,
                False,
            )
        tool_calls.append({
            "name": self.knowledge_tool.name,
            "args": {"collection": collection, "top_k": top_k},
            "result": results,
        })

        threshold = self.RETRIEVAL_THRESHOLDS[collection]
        if not results or results[0]["score"] < threshold:
            if mysql_product_context:
                metadata["mysql_product_fallback"] = True
                answer = self._generate_answer(
                    user_input, context=mysql_product_context, session_id=session_id,
                    on_final_chunk=on_final_chunk, is_cancelled=is_cancelled,
                )
                return self._complete(answer, tool_calls, metadata, started, session_id, customer_id, False)
            metadata["retrieval_below_threshold"] = True
            return self._complete(
                FALLBACK_MESSAGE, tool_calls, metadata, started, session_id, customer_id, False
            )

        metadata["source_refs"] = [
            {key: result[key] for key in ("title", "source_file", "score")}
            for result in results
        ]
        context = "\n\n".join(
            f"【{result['title']}】\n{result['content']}\n来源：{result['source_file']}"
            for result in results
        )
        if mysql_product_context:
            context = mysql_product_context + "\n\n" + context
        answer = self._generate_answer(
            user_input,
            context=context,
            session_id=session_id,
            on_final_chunk=on_final_chunk,
            is_cancelled=is_cancelled,
        )
        return self._complete(answer, tool_calls, metadata, started, session_id, customer_id, False)

    @staticmethod
    def _is_subscription_request(question: str, history: list[dict]) -> bool:
        text = question.lower()
        purchase_words = ("申购", "购买", "买入", "预约申购")
        if any(word in text for word in purchase_words):
            return True
        # 后续只回复金额或产品名时，上一轮客服必须明确询问过申购资料。
        return bool(CustomerServiceAgent._pending_subscription(history))

    @staticmethod
    def _is_redemption_request(question: str, history: list[dict]) -> bool:
        text = question.lower()
        if any(word in text for word in ("赎回", "卖出", "退出持仓")):
            return True
        return bool(CustomerServiceAgent._pending_redemption(history))

    @staticmethod
    def _pending_subscription(history: list[dict]) -> bool:
        users = [str(item.get("content") or "") for item in history if item.get("role") == "user"]
        assistants = [str(item.get("content") or "") for item in history if item.get("role") == "assistant"]
        return any(any(word in message.lower() for word in ("申购", "购买", "买入", "预约申购")) for message in users) and any(
            "申购金额" in message or "产品名称" in message or "产品代码" in message
            for message in assistants[-3:]
        )

    @staticmethod
    def _pending_redemption(history: list[dict]) -> bool:
        users = [str(item.get("content") or "") for item in history if item.get("role") == "user"]
        assistants = [str(item.get("content") or "") for item in history if item.get("role") == "assistant"]
        return any(any(word in message.lower() for word in ("赎回", "卖出", "退出持仓")) for message in users) and any(
            "赎回份额" in message or "持有份额" in message or "卖出数量" in message
            for message in assistants[-3:]
        )

    @staticmethod
    def _looks_like_operation_detail(question: str) -> bool:
        text = question.strip().lower()
        return (
            bool(re.search(r"(?:\d[\d,]*(?:\.\d+)?)\s*(?:万|万元|千|千元|元|份|%)?", text))
            or any(word in text for word in ("全部", "一半", "二分之一", "三分之一", "四分之一", "百分之"))
            or len(text) <= 30
        )

    @staticmethod
    def _extract_operation_ratio(text: str) -> Optional[str]:
        normalized = re.sub(r"\s+", "", text)
        named = {
            "全部": "100%",
            "全额": "100%",
            "一半": "50%",
            "二分之一": "50%",
            "三分之一": "33.33%",
            "四分之一": "25%",
        }
        for word, ratio in named.items():
            if word in normalized:
                return ratio
        percent_match = re.search(r"([0-9]+(?:\.[0-9]+)?)%", normalized)
        if percent_match:
            value = float(percent_match.group(1))
            if 0 < value <= 100:
                return f"{value:g}%"
        chinese_percent = re.search(r"百分之([0-9]+(?:\.[0-9]+)?)", normalized)
        if chinese_percent:
            value = float(chinese_percent.group(1))
            if 0 < value <= 100:
                return f"{value:g}%"
        return None

    @staticmethod
    def _extract_subscription_details(text: str) -> tuple[Optional[str], Optional[float]]:
        amount = None
        amount_match = re.search(r"(?<![a-zA-Z])([0-9][0-9,]*(?:\.\d+)?)\s*(万元|万|千元|千|元)", text)
        if not amount_match and "%" not in text and "百分之" not in text:
            amount_match = re.fullmatch(r"\s*([0-9][0-9,]*(?:\.\d+)?)\s*", text)
        if amount_match:
            value = float(amount_match.group(1).replace(",", ""))
            unit = amount_match.group(2) if amount_match.lastindex and amount_match.lastindex >= 2 else "元"
            if unit in ("万", "万元"):
                value *= 10000
            elif unit in ("千", "千元"):
                value *= 1000
            amount = value

        product = None
        product_match = re.search(r"(?:申购|预约申购|购买|买入)\s*(?:产品)?\s*([^，,。！？；;\s]+)", text)
        if product_match:
            candidate = product_match.group(1).strip()
            if candidate not in {"请", "一下", "产品", "金额", "并", "并且"}:
                product = candidate
        code_match = re.search(r"\b[A-Za-z]{1,5}\d{2,8}\b", text)
        if code_match:
            product = code_match.group(0).upper()
        return product, amount

    def _handle_subscription_request(
        self,
        question: str,
        customer_id: int,
        session_id: str,
        tool_calls: list[dict],
        metadata: dict,
        started: float,
    ) -> AgentResult:
        history = self._sessions.get(session_id, [])[:-1]
        product, amount = self._extract_subscription_details(question)
        for item in reversed(history):
            if item.get("role") != "user":
                continue
            previous = str(item.get("content") or "")
            if not any(word in previous for word in ("申购", "购买", "买入")):
                continue
            previous_product, previous_amount = self._extract_subscription_details(previous)
            product = product or previous_product
            amount = amount if amount is not None else previous_amount
            if product and amount is not None:
                break
        ratio = self._extract_operation_ratio(question)
        is_additional = "追加申购" in question or any(
            "追加申购" in str(item.get("content") or "")
            for item in history
            if item.get("role") == "user"
        )
        operation_label = "追加申购" if is_additional else "申购"
        # 合并后续轮次可能导致产品名取到“请人工联系我”等提示，优先从最近明确申购句提取。
        if product and product in {"请", "一下", "产品", "金额"}:
            product = None
        metadata["subscription_product"] = product
        metadata["subscription_amount"] = amount
        metadata["subscription_ratio"] = ratio
        if ratio and amount is None:
            metadata["subscription_pending"] = True
            return self._complete(
                f"已识别您希望按{ratio}的比例追加申购{product or '该产品'}。追加申购需要明确资金基数，请说明是按可用资金、计划投资资金还是其他金额的{ratio}，并提供对应的具体申购金额。",
                tool_calls, metadata, started, session_id, customer_id, False,
            )
        missing = []
        if not product:
            missing.append("产品名称或产品代码")
        if amount is None or amount <= 0:
            missing.append("申购金额")
        if missing:
            if len(missing) == 2:
                prompt = f"请提供您要{operation_label}的产品名称或产品代码，以及{operation_label}金额（例如：科技创新股票，10万元）。资料收集完整后我再为您提交人工申请。"
            elif missing[0] == "申购金额":
                prompt = f"已记录您想{operation_label}{product}。请提供{operation_label}金额（例如：10万元），我收集完整后再为您提交人工申请。"
            else:
                prompt = f"已记录{operation_label}金额{amount:,.2f}元。请提供要{operation_label}的产品名称或产品代码，我收集完整后再为您提交人工申请。"
            metadata["subscription_pending"] = True
            return self._complete(prompt, tool_calls, metadata, started, session_id, customer_id, False)

        metadata["subscription_pending"] = False
        summary = f"客户申请{operation_label}{product}，意向金额{amount:,.2f}元；待人工进行适当性核验、风险揭示和最终确认。"
        return self._transfer_to_human(
            summary, customer_id, session_id, tool_calls, metadata, started,
            "已收集到产品和金额信息，已提交客户经理进行适当性核验、风险揭示与申购确认。当前仅创建申请工单，不会直接执行交易。",
        )

    def _handle_redemption_request(
        self,
        question: str,
        customer_id: int,
        session_id: str,
        tool_calls: list[dict],
        metadata: dict,
        started: float,
    ) -> AgentResult:
        history = self._sessions.get(session_id, [])[:-1]
        product = None
        product_match = re.search(r"(?:赎回|卖出|退出持仓)\s*(?:产品)?\s*([^，,。！？；;\s]+)", question)
        if product_match and product_match.group(1) not in {"请", "一下", "产品", "份额", "数量"}:
            product = product_match.group(1)
        if not product:
            for item in reversed(history):
                if item.get("role") != "user":
                    continue
                previous = str(item.get("content") or "")
                previous_match = re.search(r"(?:赎回|卖出|退出持仓)\s*(?:产品)?\s*([^，,。！？；;\s]+)", previous)
                if previous_match and previous_match.group(1) not in {"请", "一下", "产品", "份额", "数量"}:
                    product = previous_match.group(1)
                    break
        shares = None
        ratio = self._extract_operation_ratio(question)
        if ratio:
            shares = f"当前可赎回持仓的{ratio}"
        elif "全部" in question:
            shares = "全部"
        else:
            share_match = re.search(r"(?<![a-zA-Z])([0-9][0-9,]*(?:\.\d+)?)\s*(?:份|股)", question)
            if not share_match:
                share_match = re.fullmatch(r"\s*([0-9][0-9,]*(?:\.\d+)?)\s*", question)
            if share_match:
                shares = share_match.group(1).replace(",", "")
        metadata["redemption_product"] = product
        metadata["redemption_shares"] = shares
        missing = []
        if not product:
            missing.append("持仓产品名称")
        if not shares:
            missing.append("赎回份额（或全部赎回）")
        if missing:
            if len(missing) == 2:
                prompt = "请提供要赎回的持仓产品名称，以及赎回份额（或说明“全部赎回”）。资料收集完整后我再提交人工申请。"
            elif missing[0].startswith("赎回"):
                prompt = f"已记录您要赎回{product}。请提供赎回份额，或说明“全部赎回”，我收集完整后再提交人工申请。"
            else:
                prompt = f"已记录赎回数量{shares}份。请提供持仓产品名称，我收集完整后再提交人工申请。"
            metadata["redemption_pending"] = True
            return self._complete(prompt, tool_calls, metadata, started, session_id, customer_id, False)

        metadata["redemption_pending"] = False
        summary = f"客户申请赎回{product}，赎回份额{shares}；待人工核验可赎份额、费用和到账安排。"
        return self._transfer_to_human(
            summary, customer_id, session_id, tool_calls, metadata, started,
            "已收集到赎回产品和份额信息，已提交客户经理核验。当前仅创建赎回申请工单，不会直接卖出持仓。",
        )

    @staticmethod
    def _product_context_from_mysql(question: str) -> dict:
        """读取当前在售产品事实，作为产品向量检索的只读兜底。"""
        from app.Base.Client.mysqlClient import MySQLClient

        client = MySQLClient()
        try:
            rows = client.execute_sync(
                "SELECT product_code, product_name, product_type, risk_level, "
                "min_investment, redemption_period_days, nav, nav_date, fund_manager, status "
                "FROM fin_product WHERE status='在售' ORDER BY id ASC LIMIT 200"
            ) or []
        finally:
            client.close()
        if not rows:
            return {"text": "", "exact": False}

        text = question.casefold()
        exact = [row for row in rows if row.get("product_name") and str(row["product_name"]).casefold() in text]
        code_hits = [row for row in rows if row.get("product_code") and str(row["product_code"]).casefold() in text]
        risk_hits = [row for row in rows if row.get("risk_level") and str(row["risk_level"]).casefold() in text]
        type_hits = [row for row in rows if row.get("product_type") and str(row["product_type"]).casefold() in text]
        selected = exact or code_hits or risk_hits or type_hits or rows
        selected = selected[:8]
        lines = ["【当前数据库在售产品事实（fin_product）】"]
        for row in selected:
            lines.append(
                "；".join((
                    f"名称：{row.get('product_name')}",
                    f"代码：{row.get('product_code')}",
                    f"类型：{row.get('product_type')}",
                    f"风险等级：{row.get('risk_level')}",
                    f"起投金额：{row.get('min_investment')}",
                    f"最新净值：{row.get('nav')}",
                    f"净值日期：{row.get('nav_date')}",
                    f"赎回到账周期：{row.get('redemption_period_days')}天",
                    f"管理人：{row.get('fund_manager')}",
                ))
            )
        lines.append("以上为当前业务数据库事实；产品说明、费率细则和政策仍以审核知识库为准。")
        return {"text": "\n".join(lines), "exact": bool(exact)}

    def _generate_answer(
        self,
        question: str,
        context: str,
        session_id: str,
        on_final_chunk: Optional[Callable[[str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        history = self._current_history(session_id=session_id, limit=7)
        if history and history[-1] == {"role": "user", "content": question}:
            history = history[:-1]
        messages.extend(history[-6:])
        messages.append({
            "role": "user",
            "content": ANSWER_PROMPT.format(context=context, user_input=question),
        })
        if on_final_chunk is not None:
            return self._chat_stream(messages, on_final_chunk, is_cancelled)
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
        ticket_subtype = self._business_subtype_for_transfer(question)
        ticket = self.work_order_tool.run(
            customer_id=customer_id,
            intent_summary=question[:500],
            priority="中",
            session_id=session_id,
            business_subtype=ticket_subtype,
        )
        if not isinstance(ticket, dict) or not ticket.get("id"):
            raise RuntimeError(f"转人工工单创建失败: {ticket}")
        tool_calls.append({"name": self.work_order_tool.name, "result": ticket})
        metadata["transfer_ticket_id"] = ticket["id"]

        # 发布工单事件到EventBus
        try:
            from app.WealthButler.EventBus.eventBus import EventBus

            payload = {
                "order_id": ticket["id"],
                "order_type": "客户转介",
                "business_subtype": ticket_subtype,
                "customer_id": customer_id,
                "description": question[:200],
                "priority": "中",
                "handler_id": None
            }

            trace_id = str(uuid4())
            EventBus.publish(
                stream_key="stream:work_order",
                event_type="work_order",
                payload=payload,
                source_agent="customer_service_agent",
                trace_id=trace_id
            )

            logger.info(
                f"[CustomerServiceAgent] 工单事件已发布: order_id={ticket['id']}, "
                f"trace_id={trace_id}"
            )
        except Exception as e:
            logger.error(f"[CustomerServiceAgent] 发布工单事件失败: {e}", exc_info=True)
            # 事件发布失败不影响主流程
        # 客户转人工时明确展示负责理财顾问，避免只显示泛化的人工客服提示。
        try:
            profile = CustomerProfileModel.find_by_customer_id(customer_id)
            advisor_id = getattr(profile, "advisor_id", None) if profile else None
            advisor = BaseUserExtModel.get_by_id(advisor_id) if advisor_id else None
            advisor_name = getattr(advisor, "username", None) if advisor else None
        except Exception:
            logger.exception("读取客户负责理财顾问失败: customer_id=%s", customer_id)
            advisor_id = None
            advisor_name = None
        if advisor_name:
            metadata.update({"advisor_id": advisor_id, "advisor_name": advisor_name})
            if ticket_subtype == "产品配置":
                message = f"{message}负责理财顾问：{advisor_name}。工单已转交该顾问处理。"
            elif message == TRANSFER_MESSAGE:
                message = f"已为您转接负责理财顾问{advisor_name}，工作人员将根据工单跟进您的诉求。"
        return self._complete(message, tool_calls, metadata, started, session_id, customer_id, True)

    def _handle_suitability_query(
        self,
        question: str,
        customer_id: int,
        session_id: str,
        tool_calls: list[dict],
        metadata: dict,
        started: float,
    ) -> AgentResult:
        """Return the advisor's latest persisted plan, or refer to that advisor."""
        profile = CustomerProfileModel.find_by_customer_id(customer_id)
        plan = AdvisorAllocationPlanModel.find_latest_by_customer_id(customer_id)
        # 客服只复用风险画像更新前已有的投顾方案；画像更新后必须重新由投顾确认。
        profile_updated_at = getattr(profile, "updated_at", None) if profile else None
        if plan is not None and profile_updated_at and plan.created_at and plan.created_at > profile_updated_at:
            plan = None
        if plan is not None:
            advisor = BaseUserExtModel.get_by_id(plan.advisor_id)
            advisor_name = getattr(advisor, "username", None) or f"员工{plan.advisor_id}"
            products = plan.products if isinstance(plan.products, list) else []
            product_lines = []
            for item in products:
                if not isinstance(item, dict):
                    continue
                name = item.get("product_name") or item.get("name") or item.get("product_code")
                if not name:
                    continue
                details = []
                if item.get("risk_level"):
                    details.append(f"风险{item['risk_level']}")
                if item.get("allocation") is not None:
                    details.append(f"配置比例{item['allocation']}%")
                product_lines.append(f"{name}" + (f"（{'，'.join(details)}）" if details else ""))
            summary = "、".join(product_lines) or "方案中暂未记录具体产品"
            answer = (
                f"已查询到理财顾问{advisor_name}在您最近一次风险画像更新前生成的配置方案。"
                f"方案风险基准：{plan.risk_level or '暂无'}；建议产品：{summary}。"
                "该方案仅供参考，不能代替最新风险测评，实际办理需由客户经理按流程确认。"
            )
            metadata.update({"suitability_source": "advisor_allocation_plan", "advisor_id": plan.advisor_id, "advisor_name": advisor_name, "allocation_plan_id": plan.id})
            tool_calls.append({"name": "AdvisorAllocationPlan", "result": {"id": plan.id, "advisor_name": advisor_name, "products": products}})
            return self._complete(answer, tool_calls, metadata, started, session_id, customer_id, False)

        advisor_id = getattr(profile, "advisor_id", None) if profile else None
        advisor = BaseUserExtModel.get_by_id(advisor_id) if advisor_id else None
        advisor_name = getattr(advisor, "username", None) if advisor else None
        target = f"负责理财顾问{advisor_name}" if advisor_name else "负责理财顾问"
        referral_question = f"客户希望查询适合自己的产品，请{target}基于最新风险画像生成配置方案：{question}"[:500]
        metadata.update({"suitability_source": "advisor_workorder", "advisor_id": advisor_id, "advisor_name": advisor_name})
        result = self._transfer_to_human(
            referral_question, customer_id, session_id, tool_calls, metadata, started,
            f"目前没有查询到您在风险画像更新前由理财顾问生成的有效配置方案。已为您创建产品配置工单，转交{target}处理。"
        )
        return result

    @staticmethod
    def _business_subtype_for_transfer(question: str) -> str:
        """Return an explicit referral subtype for downstream role routing."""
        text = str(question or "")
        if "追加申购" in text:
            return "追加申购"
        if "申购" in text or "买入" in text:
            return "申购"
        if "赎回" in text or "卖出" in text:
            return "赎回"
        if "转账" in text or "转帐" in text:
            return "转账"
        if any(token in text for token in ("资料变更", "修改资料", "账户变更", "手机号", "邮箱")):
            return "资料变更"
        if any(token in text for token in ("配置", "推荐", "投顾", "组合诊断", "适当性")):
            return "产品配置"
        if any(token in text for token in ("理财顾问", "找投顾", "联系投顾", "转接人工", "找人工", "我要人工", "找客服", "联系人工")):
            return "产品配置"
        if any(token in text for token in ("可疑交易", "风险预警", "异常交易")):
            return "风险预警"
        # 无明确业务内容的人工请求仍应进入人工服务队列，由负责顾问后续澄清。
        return "产品配置"

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
        try:
            archive_id = self.customer_service.archive_conversation(
                session_id=session_id,
                customer_id=customer_id,
                messages=self._sessions[session_id],
                transferred_to_human=transferred,
            )
            metadata["conversation_archive_id"] = archive_id
        except Exception:
            logger.exception(
                "客服会话归档失败: session_id=%s customer_id=%s",
                session_id,
                customer_id,
            )
            metadata["archive_failed"] = True
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

    def _chat_stream(
        self,
        messages: list[dict],
        on_chunk: Callable[[str], None],
        is_cancelled: Optional[Callable[[], bool]],
    ) -> str:
        response = self.llm.model_client.chat.completions.create(
            model=self.llm.model_name,
            messages=messages,
            temperature=0.1,
            stream=True,
        )
        with self._stream_lock:
            self._active_stream = response
        chunks: list[str] = []
        try:
            for event in response:
                if is_cancelled is not None and is_cancelled():
                    raise CustomerStreamCancelled()
                choices = getattr(event, "choices", None) or []
                content = getattr(choices[0].delta, "content", None) if choices else None
                if content:
                    chunks.append(content)
                    on_chunk(content)
                usage = getattr(event, "usage", None)
                if usage:
                    self._total_token_usage = {
                        "prompt_tokens": usage.prompt_tokens,
                        "completion_tokens": usage.completion_tokens,
                        "total_tokens": usage.total_tokens,
                    }
        finally:
            with self._stream_lock:
                if self._active_stream is response:
                    self._active_stream = None
            close = getattr(response, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    logger.debug("客服回答流关闭时连接已结束", exc_info=True)
        return "".join(chunks)

    def cancel_stream(self) -> None:
        """主动关闭当前 LLM 响应，使客户端断开能中止阻塞读取。"""
        with self._stream_lock:
            response = self._active_stream
        close = getattr(response, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                logger.debug("取消客服回答流时连接已结束", exc_info=True)

    def _bind_session(self, session_id: str, customer_id: int) -> None:
        self._session_owners.setdefault(session_id, customer_id)
        if self._session_owners[session_id] != customer_id:
            raise ValueError("会话不属于当前客户")

    def _hydrate_session(self, session_id: str, customer_id: int) -> None:
        """Restore bounded persisted history when ChatService creates a fresh agent."""
        if session_id in self._sessions:
            return
        self._sessions[session_id] = []
        get_conversation = getattr(self.customer_service, "get_conversation", None)
        if not callable(get_conversation):
            return
        try:
            conversation = get_conversation(session_id, customer_id)
            messages = conversation.get("messages", []) if isinstance(conversation, dict) else []
            if not isinstance(messages, list):
                return
            self._sessions[session_id] = [
                {"role": message["role"], "content": message["content"]}
                for message in messages[-20:]
                if isinstance(message, dict)
                and message.get("role") in {"user", "assistant"}
                and isinstance(message.get("content"), str)
                and message["content"].strip()
            ]
        except Exception:
            logger.exception(
                "客服会话历史恢复失败: session_id=%s customer_id=%s",
                session_id,
                customer_id,
            )

    @staticmethod
    def _valid_knowledge_results(results: Any) -> bool:
        if not isinstance(results, list):
            return False
        return all(
            isinstance(result, dict)
            and isinstance(result.get("score"), (int, float))
            and all(isinstance(result.get(key), str) for key in ("title", "content", "source_file"))
            for result in results
        )

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
        if any(word in text for word in (
            "持仓", "总资产", "今日收益", "今天收益", "累计收益", "盈亏", "买了哪些",
            "持有几个产品", "持有多少个产品", "持仓产品数量", "账户资金", "账户资产"
        )):
            return "holdings_query", 0.65
        if any(phrase in text for phrase in (
            "开始风险测评", "开始风险评估", "进行风险测评", "进行风险评估",
            "重新测评", "重做测评", "重新做风险测评", "打开风险问卷",
            "风险承受能力测评"
        )):
            return "risk_assessment", 0.80
        if any(phrase in text for phrase in (
            "我的风险等级", "我的风险测评结果", "我的风险评估结果",
            "我的测评等级", "我的风险承受能力", "风险等级是多少",
        )):
            return "risk_level_query", 0.80
        if any(phrase in text for phrase in (
            "转人工", "转接人工", "找人工", "我要人工", "找客服", "联系人工", "人工客服", "我要投诉", "我要申购", "我想申购", "帮我申购", "我要赎回",
            "我要追加申购", "我想追加申购", "帮我追加申购",
            "帮我赎回", "我要转账", "帮我转账", "帮我购买", "我要购买", "办理业务",
            "办理申购", "办理赎回", "办理转账", "账户被盗"
        )):
            return "transfer_to_human", 0.80
        if any(word in text for word in (
            "政策", "适当性", "合规", "保本", "风险揭示", "现金交易", "大额交易",
            "反洗钱", "风险评估有效期"
        )):
            return "policy_explain", 0.65
        if any(word in text for word in (
            "电话", "热线", "服务时间", "营业时间", "流程", "公司", "全称", "公司名称",
            "忘记密码", "确认份额", "几天确认", "申购后", "赎回到账"
        )):
            return "faq", 0.65
        if any(word in text for word in ("产品", "理财", "基金", "风险等级", "说明书")):
            return "product_consult", 0.65
        if any(word in text for word in ("你好", "您好", "谢谢", "再见")):
            return "chitchat", 0.65
        return "chitchat", 0.0

    @staticmethod
    def _risk_level_answer(customer_id: int) -> tuple[str, str]:
        """Return only the authenticated customer's current assessment status."""
        current = RiskAssessmentModel.find_valid_by_customer_id(customer_id)
        latest = current or RiskAssessmentModel.find_latest_by_customer_id(customer_id)
        if current is not None:
            assessment_date = CustomerServiceAgent._format_assessment_date(
                current.assessment_time
            )
            valid_until = CustomerServiceAgent._format_assessment_date(current.valid_until)
            return (
                f"您当前有效的风险承受能力等级为{current.risk_level}。"
                f"评估日期：{assessment_date}，有效期至：{valid_until}。",
                "valid",
            )
        if latest is not None:
            valid_until = CustomerServiceAgent._format_assessment_date(latest.valid_until)
            return (
                f"您最近一次风险测评等级为{latest.risk_level}，但已于{valid_until}失效。"
                "请重新完成风险测评后再查看适配产品。",
                "expired",
            )
        return (
            "您目前没有可查询的风险测评结果。请点击页面中的“开始风险测评”完成问卷，"
            "完成后即可查询您的风险承受能力等级。",
            "missing",
        )

    @staticmethod
    def _format_assessment_date(value: Any) -> str:
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        return str(value or "未知日期")[:10]

    @staticmethod
    def _should_extract_profile(question: str) -> bool:
        text = question.lower()
        return any(phrase in text for phrase in (
            "我偏好", "我希望", "我倾向", "我能承受", "我的风险承受", "我的投资目标",
            "我的投资期限", "我计划投资", "我需要流动性", "我不能接受亏损",
        ))

    @staticmethod
    def _resolve_holdings_query_types(question: str) -> list[str]:
        text = question.lower()
        holdings_phrases = (
            "持仓", "买了哪些", "累计收益", "累计盈亏", "总盈亏", "持有哪些",
            "持有几个产品", "持有多少个产品", "几个持仓产品", "多少个持仓产品",
            "持仓产品数量", "产品持仓数量",
        )
        query_groups = (
            ("holdings_list", holdings_phrases),
            ("total_asset", ("总资产", "资产总额", "账户资金", "账户资产")),
            ("today_profit", ("今日收益", "今天收益", "当日收益")),
        )
        detected = []
        for query_type, phrases in query_groups:
            positions = [text.find(phrase) for phrase in phrases if phrase in text]
            if positions:
                detected.append((min(positions), query_type))
        query_types = [query_type for _, query_type in sorted(detected)]
        return query_types or ["today_profit"]

    @staticmethod
    def _resolve_contextual_follow_up(
        question: str, history: list[dict]
    ) -> Optional[tuple[str, float, str]]:
        """Resolve short references against the most recent assistant answer."""
        normalized = re.sub(r"[？?。！!，,\s]", "", question)
        holdings_follow_ups = {
            "分别是什么", "都是什么", "具体是哪些", "分别有哪些",
            "是哪几个", "是哪几个产品", "都有哪些", "产品名称呢",
        }
        advisor_transfer_follow_ups = {"转人工", "转接人工", "好的转人工", "需要理财顾问", "需要投顾"}
        if normalized in advisor_transfer_follow_ups:
            for message in reversed(history[-6:]):
                if message.get("role") != "assistant":
                    continue
                content = str(message.get("content") or "")
                if "理财顾问" in content or "投顾" in content:
                    return "transfer_to_human", 0.99, "我要找理财顾问，进行产品配置咨询"
                break
        if normalized not in holdings_follow_ups:
            return None
        for message in reversed(history[-6:]):
            if message.get("role") != "assistant":
                continue
            content = str(message.get("content") or "")
            if re.search(r"持有\s*\d+\s*个产品", content) or "暂无持仓" in content:
                return "holdings_query", 0.99, "我的持仓产品分别是什么"
            break
        return None

    def get_session_messages(self, session_id: str) -> list[dict]:
        return list(self._sessions.get(session_id, []))

    def get_session_owner(self, session_id: str) -> Optional[int]:
        return self._session_owners.get(session_id)

    def _detect_suspicious_intent(
        self, user_input: str, customer_id: int, session_id: str
    ) -> Optional[dict]:
        """检测可疑意图并发布事件到EventBus

        检测规则：
        - money_laundering: 洗钱相关关键词
        - fraud: 诈骗相关关键词
        - phishing: 钓鱼/套取信息相关关键词
        - other: 其他可疑行为

        Args:
            user_input: 用户输入
            customer_id: 客户ID
            session_id: 会话ID

        Returns:
            检测结果字典或None
        """
        text_lower = user_input.lower()

        # 洗钱相关关键词
        money_laundering_keywords = [
            "现金交易", "大额现金", "拆分转账", "代理转账", "帮忙转账",
            "账户出租", "出租账户", "借用账户", "代收代付"
        ]

        # 诈骗相关关键词
        fraud_keywords = [
            "保证收益", "稳赚不赔", "内幕消息", "快速致富",
            "高额回报", "无风险高收益", "投资返利"
        ]

        # 钓鱼/套取信息关键词
        phishing_keywords = ["验证码", "密码", "身份证号", "银行卡号"]
        phishing_action_keywords = [
            "告诉我", "发给我", "提供给我", "帮我获取", "套取", "查看他人", "别人的"
        ]

        suspicious_type = None
        confidence = 0.0
        matched_keywords = []

        # 检测洗钱意图
        for keyword in money_laundering_keywords:
            if keyword in user_input:
                suspicious_type = "money_laundering"
                confidence = 0.85
                matched_keywords.append(keyword)
                break

        # 检测诈骗意图
        if not suspicious_type:
            for keyword in fraud_keywords:
                if keyword in user_input:
                    suspicious_type = "fraud"
                    confidence = 0.80
                    matched_keywords.append(keyword)
                    break

        # 检测钓鱼意图
        if not suspicious_type:
            sensitive_matches = [keyword for keyword in phishing_keywords if keyword in user_input]
            action_matches = [keyword for keyword in phishing_action_keywords if keyword in user_input]
            if sensitive_matches and action_matches:
                suspicious_type = "phishing"
                confidence = 0.85
                matched_keywords.extend(sensitive_matches + action_matches)

        # 未检测到可疑意图
        if not suspicious_type:
            return None

        # 发布可疑意图事件到EventBus
        try:
            from app.WealthButler.EventBus.eventBus import EventBus

            payload = {
                "customer_id": customer_id,
                "session_id": session_id,
                "intent_type": suspicious_type,
                "confidence": str(confidence),
                "suspicious_text": user_input[:200],  # 截取前200字符
                "evidence": {
                    "matched_keywords": matched_keywords,
                    "full_text_length": len(user_input)
                },
                "detected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            trace_id = str(uuid4())
            EventBus.publish(
                stream_key="stream:suspicious_intent",
                event_type="suspicious_intent",
                payload=payload,
                source_agent="customer_service_agent",
                trace_id=trace_id
            )

            logger.warning(
                f"[CustomerServiceAgent] 检测到可疑意图并发布事件: "
                f"customer_id={customer_id}, type={suspicious_type}, "
                f"trace_id={trace_id}"
            )

            return {
                "intent_type": suspicious_type,
                "confidence": confidence,
                "trace_id": trace_id,
                "matched_keywords": matched_keywords
            }

        except Exception as e:
            logger.error(f"[CustomerServiceAgent] 发布可疑意图事件失败: {e}", exc_info=True)
            return None
