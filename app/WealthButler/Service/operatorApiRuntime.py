"""业务操作 API 的可注入运行时。

此层把 API 身份上下文、结构化候选和既有 ``OperatorAgent`` 连接起来。
正式入口必须显式注入真实 Adapter；Fake Runtime 仅供离线测试使用。
"""

from datetime import date, datetime
from decimal import Decimal
import json
from typing import Any, Dict, Optional, Set
from uuid import uuid4

from app.WealthButler.Agent.operatorAgent import OperatorAgent
from app.WealthButler.Tools.nl2apiTool import IntentParser
from app.WealthButler.Service.confirmationService import ConfirmationService, InMemoryConfirmationGateway
from app.WealthButler.Service.operationService import OperationService
from app.WealthButler.Service.operatorContracts import INTENT_PERMISSIONS, OperationResult
from app.WealthButler.Service.operatorFakes import (
    FakeAdvisorQualificationGateway,
    FakeCustomerGateway,
    FakeCustomerInfoGateway,
    FakeEventPublisher,
    FakeHoldingGateway,
    FakeOperationAuditGateway,
    FakeOperationRiskGateway,
    FakePermissionGateway,
    FakeProductGateway,
    FakePurchaseComplianceGateway,
    FakeRiskAlertGateway,
    FakeRiskAssessmentGateway,
    FakeSuitabilityGateway,
    FakeTransactionGateway,
    FakeWorkOrderGateway,
)


class OperatorApiRuntime:
    """承载一个业务操作 Agent 实例及其可观察的依赖。"""

    def __init__(
        self,
        agent: OperatorAgent,
        service: OperationService,
        runtime_mode: str = "fake",
        **dependencies: Any,
    ):
        self.agent = agent
        self.service = service
        self.runtime_mode = runtime_mode
        for name, dependency in dependencies.items():
            setattr(self, name, dependency)

    def execute(
        self,
        employee_id: int,
        customer_id: int,
        user_input: str,
        candidate: Optional[Dict[str, Any]],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """执行一次 API 操作请求，并创建不可由客户端指定的调用链标识。"""
        # 结构化候选只属于离线 Fake 验收；真实 Runtime 一律从自然语言解析。
        raw_candidate = candidate if self.runtime_mode == "fake" and isinstance(candidate, dict) else {}
        trace_prefix = str(session_id or "operator").strip() or "operator"
        session_key = trace_prefix[:128]
        safe_context = {
            "intent": raw_candidate.get("intent"),
            "confidence": raw_candidate.get("confidence", 0.0),
            "extracted_params": raw_candidate.get("extracted_params", {}),
            # API 请求可携带的 trace_id 不具备可信性，不参与幂等或审计边界。
            "trace_id": f"operator:{uuid4()}",
            # 会话名只用于 employee+customer 命名空间内的短期草稿，不能提供身份或业务 ID。
            "session_key": session_key,
            "trusted_customer_id": customer_id,
        }
        return self.agent.handle_natural_language(
            employee_id=employee_id,
            customer_id=customer_id or 0,
            user_input=user_input,
            context=safe_context,
        )

    def submit(
        self,
        employee_id: int,
        customer_id: int,
        intent: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行结构化 REST 请求，复用 APIExecutor 的安全边界。"""
        return to_json_safe_result(self.agent.api_executor_tool.run(
            intent=intent,
            employee_id=employee_id,
            customer_id=customer_id,
            params=params,
            confidence=1.0,
            trace_id=f"operator:rest:{uuid4()}",
        ))

    def confirm(self, employee_id: int, confirm_token: str, action: str) -> Dict[str, Any]:
        """从确认令牌恢复原始客户上下文，防止客户端伪造确认对象。"""
        pending = self.service.confirmation_service.get_pending(confirm_token)
        customer_id = pending.customer_id if pending else 0
        if action == "confirm":
            return self.agent.confirm(confirm_token, employee_id, customer_id)
        if action == "cancel":
            return self.agent.cancel(confirm_token, employee_id, customer_id)
        return OperationResult(False, "INVALID_CONFIRM_ACTION", "确认动作仅支持confirm或cancel").to_dict()


def to_json_safe_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """按 API 契约序列化金额与时间，避免 Decimal 直接进入 JSON。"""
    def default(value: Any) -> str:
        if isinstance(value, Decimal):
            return format(value, "f")
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        raise TypeError(f"不支持的响应字段类型: {type(value).__name__}")

    return json.loads(json.dumps(result, ensure_ascii=False, default=default))


class OperatorApiRuntimeFactory:
    """业务操作 Runtime 装配工厂。

    Fake Runtime 只服务于离线回归；正式联调需以真实 Adapter 构造
    OperationService 后调用 create_real，不改变 API 或 Agent。
    """

    @staticmethod
    def create_real(
        operation_service: OperationService,
        intent_parser: IntentParser,
        **dependencies: Any,
    ) -> OperatorApiRuntime:
        """以已注入真实 Adapter 的 OperationService 构造真实联调 Runtime。"""
        if not isinstance(operation_service, OperationService):
            raise TypeError("operation_service 必须是 OperationService 实例")
        if not callable(getattr(intent_parser, "parse", None)):
            raise TypeError("真实 Runtime 必须注入 IntentParser")
        return OperatorApiRuntime(
            agent=OperatorAgent(operation_service, intent_parser=intent_parser),
            service=operation_service,
            runtime_mode="real",
            **dependencies,
        )

    @staticmethod
    def create_fake(
        employee_permissions: Optional[Dict[int, Set[str]]] = None,
        customer_ids: Optional[Set[int]] = None,
        products: Optional[Dict[int, Dict[str, Any]]] = None,
        advisor_levels: Optional[Dict[int, Optional[str]]] = None,
    ) -> OperatorApiRuntime:
        permissions = FakePermissionGateway(
            employee_permissions if employee_permissions is not None else {8: set(INTENT_PERMISSIONS.values())}
        )
        customers = FakeCustomerGateway(customer_ids if customer_ids is not None else {1001})
        product_gateway = FakeProductGateway(products if products is not None else {
            1: {
                "product_id": 1,
                "product_name": "阶段5模拟R3公募基金",
                "product_type": "公募基金",
                "risk_level": "R3",
                "min_investment": "100.00",
                "nav": "10.00",
                "status": "在售",
                "admission_tier": "可执行",
            },
            2: {
                "product_id": 2,
                "product_name": "阶段5模拟私募基金",
                "product_type": "私募基金",
                "risk_level": "R4",
                "min_investment": "1000.00",
                "status": "在售",
                "admission_tier": "仅预约",
            },
        })
        holdings = FakeHoldingGateway(
            total_values={1001: "50000.00"},
            r3_values={1001: "0.00"},
            positions={},
        )
        transactions = FakeTransactionGateway(holdings)
        work_orders = FakeWorkOrderGateway()
        confirmations = InMemoryConfirmationGateway()
        confirmation_service = ConfirmationService(confirmation_gateway=confirmations)
        service = OperationService(
            permission_gateway=permissions,
            customer_gateway=customers,
            advisor_qualification_gateway=FakeAdvisorQualificationGateway(
                advisor_levels if advisor_levels is not None else {8: "高级"}
            ),
            product_gateway=product_gateway,
            suitability_gateway=FakeSuitabilityGateway(),
            purchase_compliance_gateway=FakePurchaseComplianceGateway(),
            holding_gateway=holdings,
            transaction_gateway=transactions,
            work_order_gateway=work_orders,
            risk_assessment_gateway=FakeRiskAssessmentGateway(),
            customer_info_gateway=FakeCustomerInfoGateway(),
            risk_alert_gateway=FakeRiskAlertGateway(),
            event_publisher=FakeEventPublisher(),
            operation_risk_gateway=FakeOperationRiskGateway(),
            operation_audit_gateway=FakeOperationAuditGateway(),
            confirmation_service=confirmation_service,
        )
        return OperatorApiRuntime(
            agent=OperatorAgent(service, allow_test_candidate=True),
            service=service,
            runtime_mode="fake",
            permissions=permissions,
            customers=customers,
            products=product_gateway,
            holdings=holdings,
            transactions=transactions,
            work_orders=work_orders,
            confirmations=confirmations,
            events=service.event_publisher,
            audit=service.operation_audit_gateway,
        )
