"""业务操作 Agent 骨架。

Agent 只负责意图路由、置信度门槛和 Tool 编排；资金、工单、风评与风控写入
全部交由确定性 Service 和可替换 Adapter 完成。
"""

import json
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Dict, Optional

from app.Base.Ai.base.baseAgent import BaseAgent
from app.WealthButler.Prompts.operatorPrompts import OPERATOR_SYSTEM_PROMPT
from app.WealthButler.Service.operationService import OperationService
from app.WealthButler.Service.operatorContracts import OperationResult
from app.WealthButler.Service.operatorDraftStore import OperatorDraftStore
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
        draft_store: Optional[OperatorDraftStore] = None,
    ):
        self.operation_service = operation_service
        self.draft_store = draft_store or OperatorDraftStore()
        self.nl2api_tool = NL2APITool(
            intent_parser=intent_parser,
            allow_test_candidate=allow_test_candidate,
            candidate_resolver=self._resolve_candidate_params,
        )
        self.api_executor_tool = APIExecutorTool(operation_service)
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
                    "resolution_pending": bool(parsed.get("resolution_pending")),
                    "resolution_errors": normalization_errors if parsed.get("resolution_pending") else [],
                },
            ).to_dict()
        missing_params = parsed.get("missing_params") or []
        if missing_params:
            return OperationResult(
                False,
                "MISSING_PARAMS",
                "缺少必要参数：" + "、".join(missing_params),
                metadata={
                    "trace_id": trace_id,
                    "missing_params": missing_params,
                    "collected_fields": sorted((parsed.get("draft_params") or {}).keys()),
                },
            ).to_dict()
        if parsed.get("intent") == "product_query" and not customer_id:
            # 产品查询是公共只读能力，不需要绑定客户；仍保留员工权限校验。
            from app.WealthButler.Service.operatorContracts import OperationCommand

            result = self.operation_service._execute_after_preflight(
                employee_id,
                customer_id,
                OperationCommand(
                    intent="product_query",
                    params=parsed.get("extracted_params") or {},
                    confidence=confidence,
                    trace_id=trace_id,
                ),
            )
            return result.to_dict() if hasattr(result, "to_dict") else result
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
        session_key = str(context.get("session_key") or "default")
        if self._is_cancel_request(user_input):
            self.draft_store.clear(employee_id, customer_id, session_key)
            return OperationResult(True, "OPERATION_DRAFT_CANCELLED", "已取消当前未完成的业务操作").to_dict()
        # 公共产品查询没有客户上下文，不进入按客户隔离的业务草稿存储。
        draft = self.draft_store.get(employee_id, customer_id, session_key) if customer_id else None
        parse_context = dict(context)
        if draft:
            parse_context["draft_intent"] = draft.intent
            parse_context["draft_params"] = draft.params
        parsed = self.nl2api_tool.run(user_input=user_input, context=parse_context)
        if not isinstance(parsed, dict):
            return OperationResult(False, "INTENT_PARSER_FAILED", "业务操作意图解析失败，请补充明确指令").to_dict()
        parsed["trace_id"] = context.get("trace_id", "operator-stage1")
        intent = parsed.get("intent")
        if draft and intent not in {draft.intent, "unknown"}:
            if customer_id:
                self.draft_store.clear(employee_id, customer_id, session_key)
        result = self.handle(employee_id, customer_id, parsed)
        should_save = (
            intent and intent != "unknown"
            and (
                result.get("code") == "MISSING_PARAMS"
                or parsed.get("resolution_pending")
                or (
                    not result.get("success")
                    and result.get("code") not in {"LOW_CONFIDENCE", "PARAMETER_REJECTED", "PERMISSION_DENIED"}
                )
            )
        )
        if should_save:
            self.draft_store.save(
                employee_id,
                customer_id,
                session_key,
                intent,
                parsed.get("draft_params") or parsed.get("extracted_params") or {},
            )
        elif result.get("success") and customer_id:
            self.draft_store.clear(employee_id, customer_id, session_key)
        return result

    def _resolve_candidate_params(self, intent: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """把模型临时字段确定性解析为现有交易契约字段。"""
        resolved = dict(params)
        errors = []
        product_name = resolved.get("product_name")
        if resolved.get("product_id") is None and isinstance(product_name, str) and product_name.strip():
            try:
                result = self.operation_service.product_gateway.list_products(
                    keyword=product_name.strip(), page=1, per_page=100
                )
                items = result.get("items", []) if isinstance(result, dict) else []
                exact = [
                    item for item in items
                    if str(item.get("product_name", "")).strip().casefold() == product_name.strip().casefold()
                    or str(item.get("product_code", "")).strip().casefold() == product_name.strip().casefold()
                ]
                candidates = exact or items
                if len(candidates) == 1:
                    resolved["product_id"] = candidates[0]["product_id"]
                    resolved.pop("product_name", None)
                elif len(candidates) > 1:
                    errors.append({"field": "product_name", "code": "PRODUCT_AMBIGUOUS", "message": "产品名称匹配到多个产品"})
                else:
                    errors.append({"field": "product_name", "code": "PRODUCT_NOT_FOUND", "message": "未找到对应产品"})
            except Exception:
                errors.append({"field": "product_name", "code": "PRODUCT_LOOKUP_FAILED", "message": "产品库查询失败"})

        ratio = resolved.get("redeem_ratio")
        if intent == "redeem" and ratio is not None and resolved.get("shares") is None and resolved.get("product_id") is not None:
            try:
                numeric_ratio = self._normalize_redeem_ratio(ratio)
                if not numeric_ratio.is_finite() or numeric_ratio <= 0 or numeric_ratio > 1:
                    raise InvalidOperation
                customer_id = int(context["trusted_customer_id"])
                position = self.operation_service.holding_gateway.get_position(customer_id, int(resolved["product_id"]))
                available = Decimal(str(position.get("shares", "0")))
                shares = (available * numeric_ratio).quantize(Decimal("0.000001"))
                if shares <= 0:
                    raise InvalidOperation
                resolved["shares"] = format(shares, "f")
                resolved.pop("redeem_ratio", None)
            except (KeyError, TypeError, ValueError, InvalidOperation):
                errors.append({"field": "redeem_ratio", "code": "REDEEM_RATIO_INVALID", "message": "无法按当前持仓换算赎回比例"})
        return {"params": resolved, "errors": errors}

    @staticmethod
    def _normalize_redeem_ratio(value: Any) -> Decimal:
        normalized = str(value or "").strip().casefold()
        if normalized in {"all", "全部", "全额"}:
            return Decimal("1")
        if normalized in {"half", "一半", "半数"}:
            return Decimal("0.5")
        percent = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", normalized)
        if percent:
            return Decimal(percent.group(1)) / Decimal("100")
        return Decimal(normalized)

    @staticmethod
    def _is_cancel_request(user_input: str) -> bool:
        normalized = str(user_input or "").strip().replace(" ", "")
        return normalized in {"取消", "算了", "不办了", "取消操作", "取消办理"}

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
