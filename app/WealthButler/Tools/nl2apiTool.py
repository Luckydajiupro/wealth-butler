"""业务操作的自然语言解析 Tool。"""

import json
import re
from typing import Any, Callable, Dict, Optional, Protocol

from pydantic import BaseModel, Field

from app.Base.Ai.base.baseTool import BaseTool
from app.WealthButler.Service.operatorContracts import OPERATOR_AGENT_INTENTS
from app.WealthButler.Service.operatorInputPolicy import OperationInputPolicy, is_valid_confidence


class IntentParser(Protocol):
    """自然语言意图解析边界，便于注入项目的 Qwen/DeepSeek 封装。"""

    def parse(self, user_input: str) -> Dict[str, Any]: ...


class LLMIntentParser:
    """使用脚手架 ``BaseLlm`` 兼容实例提取业务操作结构化候选。"""

    def __init__(self, llm: Any):
        if not callable(getattr(llm, "invoke", None)):
            raise TypeError("llm 必须提供 invoke(prompt, stream=False) 方法")
        self.llm = llm

    def parse(self, user_input: str) -> Dict[str, Any]:
        prompt = self._build_prompt(user_input)
        response = self.llm.invoke(prompt, stream=False)
        if not isinstance(response, str):
            raise ValueError("意图解析模型未返回文本")
        payload = self._load_json(response)
        if not isinstance(payload, dict):
            raise ValueError("意图解析模型返回格式不合法")
        return payload

    @staticmethod
    def _build_prompt(user_input: str) -> str:
        return """你是业务操作意图解析器。只输出一个 JSON 对象，不要 Markdown，不要解释。
可选 intent 仅有：purchase、redeem、transfer、update_info、product_query。其他请求输出 unknown。
输出结构固定为：
{"intent":"...或unknown","confidence":0到1的小数,"extracted_params":{}}
各意图只能使用以下字段：
- purchase: product_id, product_name, amount, work_order_id；必填 product_id（或明确产品名）, amount
- redeem: product_id, product_name, shares, redeem_ratio；必填 product_id（或明确产品名）, shares（或明确比例）
- transfer: amount, counterparty_account, counterparty_name, channel；必填 amount, counterparty_account, counterparty_name
- update_info: phone, email
- product_query: product_id, product_type, risk_level, status, keyword, page, per_page
product_name 只能抄录员工明确说出的产品名称，不能生成 product_id。redeem_ratio 使用 0 到 1 的字符串，
例如“一半”为“0.5”、“全部”为“1”、“30%”为“0.3”。
禁止输出 product、product_code、account、payee、payee_name 等别名，必须使用上面的规范字段名。
只能提取用户明确表达的参数，绝不编造 customer_id、employee_id、trace_id、权限、角色、确认令牌或幂等键。
金额和份额必须输出为字符串；信息不完整时保留已明确字段，其余字段不要猜测。
示例：
输入“为客户申购产品12，金额20000元”时输出 {"intent":"purchase","confidence":0.99,"extracted_params":{"product_id":12,"amount":"20000"}}
输入“转账60000元到账号6222，收款人张三”时输出 {"intent":"transfer","confidence":0.99,"extracted_params":{"amount":"60000","counterparty_account":"6222","counterparty_name":"张三"}}
用户输入：
""" + user_input

    @staticmethod
    def _load_json(response: str) -> Dict[str, Any]:
        content = response.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            content = fenced.group(1)
        return json.loads(content)


class NL2APIInput(BaseModel):
    user_input: str = Field(..., min_length=1, description="员工的原始业务操作请求")
    context: Dict[str, Any] = Field(default_factory=dict, description="上游解析器提供的结构化候选")


class NL2APITool(BaseTool):
    name = "NL2API"
    description = "将业务操作请求规范化为意图、已提取参数和缺失参数"
    args_schema = NL2APIInput

    def __init__(
        self,
        intent_parser: Optional[IntentParser] = None,
        allow_test_candidate: bool = False,
        candidate_resolver: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        super().__init__()
        self.intent_parser = intent_parser
        # 仅 Fake Runtime 可使用此开关，正式 Runtime 绝不信任 HTTP 请求中的候选。
        self.allow_test_candidate = allow_test_candidate
        self.candidate_resolver = candidate_resolver

    def execute(self, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """解析并归一化候选；任何解析异常均失败关闭，不触发执行。"""
        try:
            candidate = context if self.allow_test_candidate else self._parse_with_llm(user_input, context)
        except (TypeError, ValueError, json.JSONDecodeError):
            candidate = {}
        if not isinstance(candidate, dict):
            candidate = {}

        intent = candidate.get("intent")
        draft_intent = context.get("draft_intent")
        draft_params = context.get("draft_params") if isinstance(context.get("draft_params"), dict) else {}
        # A short follow-up can be under-classified by the model. Only the runtime-injected
        # draft may supply the intent; model/request identity fields remain untrusted.
        followup_params = candidate.get("extracted_params")
        draft_policy_params = {
            field: value for field, value in draft_params.items()
            if field not in {"product_name", "redeem_ratio"}
        }
        draft_is_incomplete = bool(
            draft_intent in OPERATOR_AGENT_INTENTS
            and OperationInputPolicy.normalize(draft_intent, draft_policy_params)["missing_params"]
        )
        if (
            intent not in OPERATOR_AGENT_INTENTS
            and draft_intent in OPERATOR_AGENT_INTENTS
            and (
                (isinstance(followup_params, dict) and bool(followup_params))
                or draft_is_incomplete
            )
        ):
            intent = draft_intent
            candidate = {
                "intent": intent,
                "confidence": 1.0,
                "extracted_params": followup_params,
            }
        if intent not in OPERATOR_AGENT_INTENTS and self._looks_like_product_read_query(user_input):
            # 具体产品追问常被通用意图模型标成 unknown；这是只读查询，
            # 用原文作为关键词补入产品库筛选，不会触发任何交易动作。
            intent = "product_query"
            product_keyword = NL2APITool._extract_product_keyword(str(user_input).strip())
            candidate = {
                "intent": intent,
                "confidence": 0.95,
                "extracted_params": {"keyword": product_keyword},
            }
        if intent not in OPERATOR_AGENT_INTENTS:
            return {"intent": "unknown", "confidence": 0.0, "extracted_params": {}, "missing_params": []}

        raw_params = candidate.get("extracted_params", {})
        if draft_intent == intent:
            raw_params = {**draft_params, **({} if raw_params is None else raw_params)}
        if intent == "product_query" and isinstance(raw_params, dict):
            # 产品查询是只读筛选；模型偶尔会附带展示别名，丢弃这些非筛选字段，
            # 避免把一次安全查询误判成业务操作参数错误。
            raw_params = {
                key: value for key, value in raw_params.items()
                if key in {"product_id", "product_type", "risk_level", "status", "keyword", "product_name", "page", "per_page"}
            }
        resolution_errors = []
        if self.candidate_resolver and isinstance(raw_params, dict):
            resolved = self.candidate_resolver(intent, raw_params, context)
            raw_params = resolved.get("params", raw_params)
            resolution_errors = resolved.get("errors", [])
        provisional = {
            field: raw_params[field]
            for field in ("product_name", "redeem_ratio")
            if isinstance(raw_params, dict) and field in raw_params
        }
        policy_params = {
            field: value for field, value in (raw_params or {}).items()
            if field not in {"product_name", "redeem_ratio"}
        }
        normalized = OperationInputPolicy.normalize(intent, policy_params)
        if intent == "product_query" and "product_name" in normalized["params"] and "keyword" not in normalized["params"]:
            normalized["params"]["keyword"] = normalized["params"].pop("product_name")
        confidence_valid, confidence = is_valid_confidence(candidate.get("confidence", 0.0))
        return {
            "intent": intent,
            "confidence": confidence if confidence_valid else 0.0,
            "extracted_params": normalized["params"],
            "missing_params": normalized["missing_params"],
            "normalization_errors": resolution_errors + normalized["errors"],
            "draft_params": {**normalized["params"], **provisional},
            "resolution_pending": bool(resolution_errors),
        }

    def _parse_with_llm(self, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if self.intent_parser is None:
            raise ValueError("业务操作意图解析器尚未配置")
        draft_intent = context.get("draft_intent")
        draft_params = context.get("draft_params")
        if draft_intent and isinstance(draft_params, dict):
            user_input = (
                "可信会话中的未完成操作草稿（只用于补全本轮明确给出的信息）："
                f"intent={draft_intent}, params={json.dumps(draft_params, ensure_ascii=False)}\n"
                f"本轮员工输入：{user_input}"
            )
        return self.intent_parser.parse(user_input)

    @staticmethod
    def _looks_like_product_read_query(user_input: str) -> bool:
        text = re.sub(r"\s+", "", str(user_input or "")).strip()
        if not text or re.search(r"申购|认购|赎回|转账|变更|办理|买入|卖出", text):
            return False
        return bool(re.search(r"产品|理财|基金|混合|股票|债券|存款|保险|净值|起购|风险|赎回期限|在售|XX", text))

    @staticmethod
    def _extract_product_keyword(text: str) -> str:
        match = re.search(r"XX[\u4e00-\u9fffA-Za-z0-9]{1,40}?(?:混合|基金|股票|债券|存款|保险)", text)
        return match.group(0) if match else text
