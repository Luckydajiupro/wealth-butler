"""阶段 1 的跨轨道 Adapter 协议。

业务操作编排只依赖这些稳定方法，最终联调时替换为各负责人提供的真实实现。
"""

from typing import Any, Dict, Optional, Protocol

from app.WealthButler.Service.operatorContracts import OperationCommand


class PermissionGateway(Protocol):
    def has_permission(self, employee_id: int, permission: str) -> bool: ...


class CustomerGateway(Protocol):
    def exists(self, customer_id: int) -> bool: ...


class AdvisorQualificationGateway(Protocol):
    def get_advisor_level(self, employee_id: int) -> Optional[str]: ...


class ProductGateway(Protocol):
    def get_product(self, product_id: int) -> Optional[Dict[str, Any]]: ...

    def list_products(self, **filters: Any) -> Dict[str, Any]: ...


class SuitabilityGateway(Protocol):
    def check(self, customer_id: int, product_id: int) -> Dict[str, Any]: ...


class PurchaseComplianceGateway(Protocol):
    def validate_purchase(
        self,
        customer_id: int,
        product: Dict[str, Any],
        command: OperationCommand,
    ) -> Optional[str]: ...


class HoldingGateway(Protocol):
    def current_total_value(self, customer_id: int) -> Any: ...

    def current_r3_value(self, customer_id: int) -> Any: ...

    def get_position(self, customer_id: int, product_id: int) -> Dict[str, Any]: ...


class TransactionGateway(Protocol):
    def get_available_balance(self, customer_id: int) -> Any: ...

    def execute(
        self,
        employee_id: int,
        customer_id: int,
        command: OperationCommand,
        execution: Dict[str, Any],
    ) -> Dict[str, Any]: ...


class WorkOrderGateway(Protocol):
    def create_booking(self, customer_id: int, summary: str, product_id: int) -> Dict[str, Any]: ...

    def transition(self, work_order_id: int, status: str, note: str) -> Dict[str, Any]: ...

    def create_work_order(self, customer_id: int, order_type: str, summary: str) -> Dict[str, Any]: ...

    def claim(self, work_order_id: int, handler_id: int) -> Dict[str, Any]: ...

    def submit_for_review(self, work_order_id: int, handler_id: int, note: str) -> Dict[str, Any]: ...

    def complete(
        self,
        work_order_id: int,
        handler_id: int,
        related_entity_type: str,
        related_entity_id: int,
        handle_note: str,
    ) -> Dict[str, Any]: ...

    def reject(self, work_order_id: int, handler_id: int, handle_note: str) -> Dict[str, Any]: ...

    def complete_transaction_for_customer(
        self, customer_id: int, handler_id: int, intent: str, transaction_id: int
    ) -> Optional[Dict[str, Any]]: ...


class RiskAssessmentGateway(Protocol):
    def submit_assessment(self, customer_id: int, answers: list, is_professional: bool = False) -> Dict[str, Any]: ...


class CustomerInfoGateway(Protocol):
    def update_contact(self, customer_id: int, phone: Optional[str], email: Optional[str]) -> Dict[str, Any]: ...


class RiskAlertGateway(Protocol):
    def report_suspicious_transaction(
        self,
        reporter_id: int,
        customer_id: int,
        severity: str,
        description: str,
        related_transaction_id: Optional[int],
        evidence_refs: Optional[list],
    ) -> Dict[str, Any]: ...


class EventPublisher(Protocol):
    def publish(
        self,
        stream_key: str,
        event_type: str,
        payload: Dict[str, Any],
        source_agent: str,
        trace_id: str,
    ) -> str: ...

    def enqueue_retry(
        self,
        stream_key: str,
        event_type: str,
        payload: Dict[str, Any],
        source_agent: str,
        trace_id: str,
        failure_reason: str,
    ) -> str: ...


class OperationAuditGateway(Protocol):
    def record(self, entry: Dict[str, Any]) -> None: ...


class OperationRiskGateway(Protocol):
    def validate_redeem(self, customer_id: int, product_id: int, shares: Any) -> Optional[str]: ...

    def validate_transfer(self, customer_id: int, amount: Any, payee: Dict[str, Any]) -> Optional[str]: ...
