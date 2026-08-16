"""业务操作执行 Tool，只允许已注册的八种意图进入确定性 Service。"""

from typing import Any, Dict

from pydantic import BaseModel, Field

from app.Base.Ai.base.baseTool import BaseTool
from app.WealthButler.Service.operationService import OperationService
from app.WealthButler.Service.operatorContracts import INTENT_PERMISSIONS, OperationCommand
from app.WealthButler.Service.operatorInputPolicy import OperationInputPolicy, is_valid_confidence


class APIExecutorInput(BaseModel):
    intent: str = Field(..., description="已识别的业务操作意图")
    employee_id: int = Field(..., gt=0, description="当前员工ID")
    customer_id: int = Field(..., gt=0, description="受理客户ID")
    params: Dict[str, Any] = Field(default_factory=dict, description="归一化后的意图参数")
    confidence: float = Field(default=1.0, ge=0, le=1, description="意图识别置信度")
    trace_id: str = Field(..., min_length=1, description="调用链ID")


class APIExecutorTool(BaseTool):
    name = "APIExecutor"
    description = "白名单分发业务操作到确定性业务服务"
    args_schema = APIExecutorInput
    MIN_EXECUTION_CONFIDENCE = 0.75

    def __init__(self, operation_service: OperationService):
        super().__init__()
        self.operation_service = operation_service

    def execute(
        self,
        intent: str,
        employee_id: int,
        customer_id: int,
        params: Dict[str, Any],
        confidence: float,
        trace_id: str,
    ) -> Dict[str, Any]:
        if intent not in INTENT_PERMISSIONS:
            return self._failure("UNKNOWN_INTENT", "不支持的业务操作意图", trace_id)
        if not isinstance(employee_id, int) or isinstance(employee_id, bool) or employee_id <= 0:
            return self._failure("INVALID_EMPLOYEE", "员工上下文不合法", trace_id)
        if not isinstance(customer_id, int) or isinstance(customer_id, bool) or customer_id <= 0:
            return self._failure("INVALID_CUSTOMER", "客户上下文不合法", trace_id)
        if not isinstance(trace_id, str) or not trace_id.strip():
            return self._failure("INVALID_TRACE_ID", "调用链ID不合法", "")

        confidence_valid, normalized_confidence = is_valid_confidence(confidence)
        if not confidence_valid or normalized_confidence < self.MIN_EXECUTION_CONFIDENCE:
            return self._failure("LOW_CONFIDENCE", "意图置信度不足，不能执行写操作", trace_id)

        normalized = OperationInputPolicy.normalize(intent, params)
        if normalized["errors"]:
            return self._failure(
                "PARAMETER_REJECTED",
                "请求参数不符合意图安全约束",
                trace_id,
                {"rejected_fields": [item["field"] for item in normalized["errors"]]},
            )
        if normalized["missing_params"]:
            return self._failure(
                "MISSING_PARAMS",
                "缺少必要参数：" + "、".join(normalized["missing_params"]),
                trace_id,
                {"missing_params": normalized["missing_params"]},
            )
        command = OperationCommand(intent=intent, params=normalized["params"], confidence=normalized_confidence, trace_id=trace_id.strip())
        return self.operation_service.submit(employee_id, customer_id, command).to_dict()

    @staticmethod
    def _failure(code: str, message: str, trace_id: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        final_metadata = {"trace_id": trace_id}
        if metadata:
            final_metadata.update(metadata)
        return {"success": False, "code": code, "message": message, "data": {}, "metadata": final_metadata}
