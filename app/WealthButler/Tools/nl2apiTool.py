"""业务操作的自然语言解析 Tool。"""

import json
import re
from typing import Any, Dict, Optional, Protocol

from pydantic import BaseModel, Field

from app.Base.Ai.base.baseTool import BaseTool
from app.WealthButler.Service.operatorContracts import INTENT_PERMISSIONS
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
可选 intent 仅有：purchase、redeem、transfer、reassess、update_info、product_query、suspicious_report、workorder_create。
输出结构固定为：
{"intent":"...或unknown","confidence":0到1的小数,"extracted_params":{}}
只能提取用户明确表达的参数，绝不编造 customer_id、employee_id、trace_id、权限、角色、确认令牌或幂等键。
金额和份额必须输出为字符串；信息不完整时保留已明确字段，其余字段不要猜测。
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
    ):
        super().__init__()
        self.intent_parser = intent_parser
        # 仅 Fake Runtime 可使用此开关，正式 Runtime 绝不信任 HTTP 请求中的候选。
        self.allow_test_candidate = allow_test_candidate

    def execute(self, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """解析并归一化候选；任何解析异常均失败关闭，不触发执行。"""
        try:
            candidate = context if self.allow_test_candidate else self._parse_with_llm(user_input)
        except (TypeError, ValueError, json.JSONDecodeError):
            candidate = {}
        if not isinstance(candidate, dict):
            candidate = {}

        intent = candidate.get("intent")
        if intent not in INTENT_PERMISSIONS:
            return {"intent": "unknown", "confidence": 0.0, "extracted_params": {}, "missing_params": []}

        raw_params = candidate.get("extracted_params", {})
        normalized = OperationInputPolicy.normalize(intent, {} if raw_params is None else raw_params)
        confidence_valid, confidence = is_valid_confidence(candidate.get("confidence", 0.0))
        return {
            "intent": intent,
            "confidence": confidence if confidence_valid else 0.0,
            "extracted_params": normalized["params"],
            "missing_params": normalized["missing_params"],
            "normalization_errors": normalized["errors"],
        }

    def _parse_with_llm(self, user_input: str) -> Dict[str, Any]:
        if self.intent_parser is None:
            raise ValueError("业务操作意图解析器尚未配置")
        return self.intent_parser.parse(user_input)
