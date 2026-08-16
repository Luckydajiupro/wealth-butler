"""业务操作 Agent 骨架。

Agent 只负责意图路由、置信度门槛和 Tool 编排；资金、工单、风评与风控写入
全部交由确定性 Service 和可替换 Adapter 完成。
"""

import json
from typing import Any, Dict, Optional

from app.Base.Ai.base.baseAgent import BaseAgent
from app.WealthButler.Prompts.operatorPrompts import OPERATOR_SYSTEM_PROMPT
from app.WealthButler.Service.operationService import OperationService
from app.WealthButler.Service.operatorContracts import OperationResult
from app.WealthButler.Service.operatorInputPolicy import is_valid_confidence
from app.WealthButler.Tools.apiExecutorTool import APIExecutorTool
from app.WealthButler.Tools.nl2apiTool import IntentParser, NL2APITool


class OperatorAgent(BaseAgent):
    """业务操作 Agent 的阶段 1 路由实现。"""

    CONFIDENCE_THRESHOLD = 0.75

    def __init__(
        self,
        operation_service: OperationService,
        intent_parser: Optional[IntentParser] = None,
        allow_test_candidate: bool = False,
    ):
        self.nl2api_tool = NL2APITool(
            intent_parser=intent_parser,
            allow_test_candidate=allow_test_candidate,
        )
        self.api_executor_tool = APIExecutorTool(operation_service)
        self.operation_service = operation_service
        super().__init__(
            llm=None,
            name="OperatorAgent",
            system_prompt=OPERATOR_SYSTEM_PROMPT,
            tools=[self.nl2api_tool, self.api_executor_tool],
        )

    def handle(self, employee_id: int, customer_id: int, parsed: Dict[str, Any]) -> Dict[str, Any]:
        """处理已解析命令；低置信度和缺参只返回追问结果。"""
        confidence_valid, confidence = is_valid_confidence(parsed.get("confidence", 0.0))
        trace_id = str(parsed.get("trace_id") or "operator-stage1")
        if not confidence_valid or confidence < self.CONFIDENCE_THRESHOLD:
            return OperationResult(
                False,
                "LOW_CONFIDENCE",
                "无法可靠识别业务意图，请补充明确的操作信息",
                metadata={"trace_id": trace_id},
            ).to_dict()
        authorization_error = self.operation_service.authorize(
            employee_id,
            parsed.get("intent", "unknown"),
            trace_id,
        )
        if authorization_error:
            return authorization_error.to_dict()
        normalization_errors = parsed.get("normalization_errors") or []
        if normalization_errors:
            return OperationResult(
                False,
                "PARAMETER_REJECTED",
                "请求参数不符合意图安全约束",
                metadata={
                    "trace_id": trace_id,
                    "rejected_fields": [item.get("field") for item in normalization_errors if isinstance(item, dict)],
                },
            ).to_dict()
        missing_params = parsed.get("missing_params") or []
        if missing_params:
            return OperationResult(
                False,
                "MISSING_PARAMS",
                "缺少必要参数：" + "、".join(missing_params),
                metadata={"trace_id": trace_id, "missing_params": missing_params},
            ).to_dict()
        result = self.api_executor_tool.run(
            intent=parsed.get("intent", "unknown"),
            employee_id=employee_id,
            customer_id=customer_id,
            params=parsed.get("extracted_params") or {},
            confidence=confidence,
            trace_id=trace_id,
        )
        if isinstance(result, dict):
            return result
        return OperationResult(False, "TOOL_EXECUTION_FAILED", "业务操作执行器不可用", metadata={"trace_id": trace_id}).to_dict()

    def handle_natural_language(self, employee_id: int, customer_id: int, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
        parsed = self.nl2api_tool.run(user_input=user_input, context=context)
        if not isinstance(parsed, dict):
            return OperationResult(False, "INTENT_PARSER_FAILED", "业务操作意图解析失败，请补充明确指令").to_dict()
        parsed["trace_id"] = context.get("trace_id", "operator-stage1")
        return self.handle(employee_id, customer_id, parsed)

    def confirm(self, confirm_token: str, employee_id: int, customer_id: int) -> Dict[str, Any]:
        return self.operation_service.confirm(confirm_token, employee_id, customer_id).to_dict()

    def cancel(self, confirm_token: str, employee_id: int, customer_id: int) -> Dict[str, Any]:
        return self.operation_service.cancel(confirm_token, employee_id, customer_id).to_dict()

    def _run_loop(self, messages: list, **kwargs: Any) -> str:
        """兼容 BaseAgent.run；实际 LLM 解析接入留到后续阶段。"""
        context = kwargs.get("operator_context") or {}
        employee_id = kwargs.get("employee_id")
        customer_id = kwargs.get("customer_id")
        if not employee_id or not customer_id:
            return json.dumps(
                OperationResult(False, "OPERATOR_CONTEXT_REQUIRED", "业务操作需要员工ID和客户ID").to_dict(),
                ensure_ascii=False,
            )
        user_input = messages[-1].get("content", "") if messages else ""
        return json.dumps(self.handle_natural_language(employee_id, customer_id, user_input, context), ensure_ascii=False)
