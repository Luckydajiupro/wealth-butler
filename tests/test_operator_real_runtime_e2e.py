"""Operator real Runtime 的无外部网络端到端验收。"""

import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import re
from threading import Lock
from types import SimpleNamespace

from app.WealthButler.Service.confirmationService import ConfirmationService, InMemoryConfirmationGateway
from app.WealthButler.Service.operationService import OperationService
from app.WealthButler.Service.operatorApiRuntime import OperatorApiRuntimeFactory
from app.WealthButler.Service.operatorRealAdapters import (
    AuthPermissionGateway,
    ModelAdvisorQualificationGateway,
    ModelCustomerGateway,
    ModelHoldingGateway,
    ModelProductGateway,
)
from app.WealthButler.Service.operatorRuleAdapters import (
    ModelOperationRiskGateway,
    ModelPurchaseComplianceGateway,
    ModelSuitabilityGateway,
)
from app.WealthButler.Service.operatorWriteAdapters import (
    AuthCustomerInfoGateway,
    EventBusPublisherGateway,
    LoggingOperationAuditGateway,
    ModelWorkOrderGateway,
)


class UserModelStore:
    records = {
        8: SimpleNamespace(id=8, user_type="EMPLOYEE", employee_role="客户经理", advisor_level="高级", status="active", deleted_at=None, source_module="fin"),
        1001: SimpleNamespace(id=1001, user_type="CUSTOMER", employee_role=None, advisor_level=None, status="active", deleted_at=None, source_module="fin", phone=None, email=None),
    }

    @classmethod
    def get_by_id(cls, user_id):
        return cls.records.get(user_id)


class AuthStore:
    permissions = {
        8: {
            "operation:purchase", "operation:redeem", "operation:transfer",
            "customer:info_update", "product:query",
        }
    }

    @classmethod
    def has_permission(cls, user_id, permission, source_module=None):
        return permission in cls.permissions.get(user_id, set())

    @classmethod
    def update_profile(cls, user_id, **fields):
        user = UserModelStore.records.get(user_id)
        if not user:
            return False, "用户不存在"
        user.__dict__.update(fields)
        return True, ""


def product(product_id, risk_level, name):
    return SimpleNamespace(
        id=product_id,
        product_code=f"P-{product_id}",
        product_name=name,
        product_type="公募基金",
        risk_level=risk_level,
        min_investment=Decimal("100.00"),
        redemption_period_days=1,
        nav=Decimal("10.00"),
        nav_date=None,
        industry="综合",
        fund_manager="测试经理",
        status="在售",
        description=None,
    )


class ProductStore:
    records = {1: product(1, "R2", "稳健产品"), 2: product(2, "R4", "进取产品")}

    @classmethod
    def get_by_id(cls, product_id):
        return cls.records.get(product_id)

    @classmethod
    def find_by(cls, order_by=None, order="ASC", **filters):
        return [item for item in cls.records.values() if all(getattr(item, key) == value for key, value in filters.items())]


class HoldingStore:
    position = SimpleNamespace(
        customer_id=1001,
        product_id=1,
        shares=Decimal("100"),
        current_value=Decimal("1000.00"),
        cost_amount=Decimal("900.00"),
        deleted_at=None,
    )

    @classmethod
    def find_by_customer_id(cls, customer_id):
        return [cls.position] if customer_id == 1001 else []

    @classmethod
    def find_by_customer_and_product(cls, customer_id, product_id):
        return cls.position if (customer_id, product_id) == (1001, 1) else None


class AtomicTransactionGateway:
    def __init__(self):
        self.lock = Lock()
        self.execute_count = 0

    def execute(self, employee_id, customer_id, command, execution):
        with self.lock:
            self.execute_count += 1
            transaction_id = self.execute_count
        names = {"purchase": "申购", "redeem": "赎回", "transfer": "转账"}
        return {
            "transaction_id": transaction_id,
            "transaction_type": names[command.intent],
            "status": "成交",
            "product_id": execution.get("product_id"),
            "amount": execution.get("amount"),
        }


class RecordingEventBus:
    def __init__(self):
        self.calls = []
        self.fail_business_events = False
        self.fail_retry_events = False

    def publish(self, stream_key, event_type, payload, source_agent, trace_id):
        self.calls.append((stream_key, event_type, payload, source_agent, trace_id))
        if self.fail_business_events and not stream_key.endswith(":retry"):
            raise RuntimeError("event bus unavailable")
        if self.fail_retry_events and stream_key.endswith(":retry"):
            raise RuntimeError("retry stream unavailable")
        return f"{len(self.calls)}-0"


class ParserStub:
    def parse(self, user_input):
        return {"intent": "unknown", "confidence": 0, "extracted_params": {}}


class WorkOrderStub:
    def create_booking(self, *args):
        return {"id": 1}

    def submit_for_review(self, *args):
        return {"id": args[0]}

    def create_work_order(self, *args):
        return {"id": 1}


class NoopRiskAssessment:
    def submit_assessment(self, *args, **kwargs):
        return {"assessment_id": 1, "recalc_profile": None}


class NoopRiskAlert:
    def report_suspicious_transaction(self, *args, **kwargs):
        return {"alert_id": 1}


class RuntimeHarness:
    def __init__(self):
        now = datetime(2026, 8, 17, 0, 0, 0)
        self.assessment = SimpleNamespace(risk_level="C3", valid_until=now + timedelta(days=30), is_professional_investor=False)
        self.profile = SimpleNamespace(fm_flags=[])
        self.evidence = {"customer_age": 30, "has_prior_r3_plus_purchase": True}
        self.audit_writes = []
        self.transactions = AtomicTransactionGateway()
        self.bus = RecordingEventBus()

        permissions = AuthPermissionGateway(AuthStore, UserModelStore)
        customers = ModelCustomerGateway(UserModelStore)
        advisors = ModelAdvisorQualificationGateway(UserModelStore)
        products = ModelProductGateway(ProductStore)
        holdings = ModelHoldingGateway(HoldingStore, ProductStore)
        suitability = ModelSuitabilityGateway(
            assessment_loader=lambda _: self.assessment,
            profile_loader=lambda _: self.profile,
            product_loader=ProductStore.get_by_id,
            now_provider=lambda: now,
        )
        compliance = ModelPurchaseComplianceGateway(
            suitability_gateway=suitability,
            evidence_loader=lambda customer_id, product_id: self.evidence,
            holding_summary_loader=lambda customer_id, risk_level: {
                "total_value": Decimal("100000"),
                "risk_level_value": Decimal("0"),
            },
        )
        operation_risk = ModelOperationRiskGateway(
            profile_loader=lambda _: self.profile,
            payee_verifier=lambda customer_id, payee: True,
        )
        event_publisher = EventBusPublisherGateway(self.bus, lambda event_type, payload: None)
        audit = LoggingOperationAuditGateway(self.audit_writes.append)
        confirmation = ConfirmationService(confirmation_gateway=InMemoryConfirmationGateway())
        service = OperationService(
            permission_gateway=permissions,
            customer_gateway=customers,
            advisor_qualification_gateway=advisors,
            product_gateway=products,
            suitability_gateway=suitability,
            purchase_compliance_gateway=compliance,
            holding_gateway=holdings,
            transaction_gateway=self.transactions,
            work_order_gateway=WorkOrderStub(),
            risk_assessment_gateway=NoopRiskAssessment(),
            customer_info_gateway=AuthCustomerInfoGateway(AuthStore, UserModelStore),
            risk_alert_gateway=NoopRiskAlert(),
            event_publisher=event_publisher,
            operation_risk_gateway=operation_risk,
            operation_audit_gateway=audit,
            confirmation_service=confirmation,
        )
        self.runtime = OperatorApiRuntimeFactory.create_real(
            service,
            ParserStub(),
            transactions=self.transactions,
            event_bus=self.bus,
        )


def _confirm(runtime, pending):
    assert pending["code"] == "CONFIRMATION_REQUIRED"
    return runtime.confirm(8, pending["metadata"]["confirm_token"], "confirm")


def test_real_runtime_purchase_redeem_and_transfer_end_to_end():
    harness = RuntimeHarness()
    runtime = harness.runtime

    purchase = _confirm(runtime, runtime.submit(8, 1001, "purchase", {"product_id": 1, "amount": "1000.00"}))
    redeem = _confirm(runtime, runtime.submit(8, 1001, "redeem", {"product_id": 1, "shares": "10"}))
    transfer = _confirm(runtime, runtime.submit(8, 1001, "transfer", {
        "amount": "100.00",
        "counterparty_account": "622200001234",
        "counterparty_name": "测试收款人",
    }))

    assert [purchase["code"], redeem["code"], transfer["code"]] == [
        "TRANSACTION_SUCCEEDED", "TRANSACTION_SUCCEEDED", "TRANSACTION_SUCCEEDED",
    ]
    assert harness.transactions.execute_count == 3
    assert harness.runtime.runtime_mode == "real"


def test_concurrent_confirmation_executes_transaction_at_most_once():
    harness = RuntimeHarness()
    pending = harness.runtime.submit(8, 1001, "purchase", {"product_id": 1, "amount": "20000.00"})
    token = pending["metadata"]["confirm_token"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: harness.runtime.confirm(8, token, "confirm"), range(8)))

    assert harness.transactions.execute_count == 1
    assert any(result["code"] == "TRANSACTION_SUCCEEDED" for result in results)
    assert all(result["code"] in {"TRANSACTION_SUCCEEDED", "CONFIRMATION_IN_PROGRESS"} for result in results)


def test_permission_suitability_and_missing_evidence_fail_closed():
    harness = RuntimeHarness()
    original_permissions = set(AuthStore.permissions[8])
    try:
        AuthStore.permissions[8].discard("operation:purchase")
        denied = harness.runtime.submit(8, 1001, "purchase", {"product_id": 1, "amount": "1000.00"})
        assert denied["code"] == "PERMISSION_DENIED"

        AuthStore.permissions[8] = original_permissions
        harness.assessment = None
        no_assessment = harness.runtime.submit(8, 1001, "purchase", {"product_id": 1, "amount": "1000.00"})
        assert no_assessment["code"] == "SUITABILITY_REJECTED"

        harness.assessment = SimpleNamespace(
            risk_level="C3",
            valid_until=datetime(2026, 9, 17),
            is_professional_investor=False,
        )
        missing_evidence = harness.runtime.submit(8, 1001, "purchase", {"product_id": 2, "amount": "1000.00"})
        assert missing_evidence["code"] == "PURCHASE_COMPLIANCE_REJECTED"
        assert "合规" in missing_evidence["message"] or "合规" in str(missing_evidence)
        assert harness.transactions.execute_count == 0
    finally:
        AuthStore.permissions[8] = original_permissions


def test_event_failure_enters_retry_and_audit_never_contains_sensitive_values():
    harness = RuntimeHarness()
    harness.bus.fail_business_events = True
    result = _confirm(harness.runtime, harness.runtime.submit(8, 1001, "transfer", {
        "amount": "100.00",
        "counterparty_account": "622200001234",
        "counterparty_name": "测试收款人",
    }))
    assert result["code"] == "TRANSACTION_SUCCEEDED_EVENT_PENDING"
    assert result["metadata"]["retry_persisted"] is True
    assert any(call[0] == "stream:large_transaction:retry" for call in harness.bus.calls)

    contact = harness.runtime.submit(8, 1001, "update_info", {
        "phone": "13812345678",
        "email": "alice@example.com",
    })
    assert contact["code"] == "CONTACT_UPDATED"
    audit_blob = "\n".join(harness.audit_writes)
    assert "13812345678" not in audit_blob
    assert "alice@example.com" not in audit_blob
    assert "622200001234" not in audit_blob
    assert '"parameter_names": ["email", "phone"]' in audit_blob


def test_retry_write_failure_is_not_misreported_as_durable_pending_event():
    harness = RuntimeHarness()
    harness.bus.fail_business_events = True
    harness.bus.fail_retry_events = True

    result = _confirm(harness.runtime, harness.runtime.submit(8, 1001, "transfer", {
        "amount": "100.00",
        "counterparty_account": "622200001234",
        "counterparty_name": "测试收款人",
    }))

    assert result["success"] is True
    assert result["code"] == "TRANSACTION_SUCCEEDED_EVENT_RETRY_FAILED"
    assert result["metadata"]["trace_id"]
    assert result["metadata"]["event_pending"] is True
    assert result["metadata"]["retry_persisted"] is False
    # The runtime may also report optional work-order closure details.
    assert result["metadata"].get("work_order_completion") is None


class AtomicWorkOrderDB:
    def __init__(self, model):
        self.model = model
        self.lock = Lock()

    def execute(self, sql, params):
        with self.lock:
            fields = re.findall(r"`([^`]+)`=%s", sql.split(" WHERE ", 1)[0])
            order_id = params[len(fields)]
            expected_status = params[len(fields) + 1]
            order = self.model.records[order_id]
            if order.status != expected_status:
                return 0
            for field, value in zip(fields, params[:len(fields)]):
                if field == "handle_records" and isinstance(value, str):
                    value = json.loads(value)
                setattr(order, field, value)
            return 1


class AtomicWorkOrderModel:
    table_alias = "biz_work_order"
    records = {
        1: SimpleNamespace(
            id=1,
            status="待处理",
            deleted_at=None,
            handler_id=None,
            handled_by=None,
            handled_at=None,
            handle_records={"records": []},
            order_no="WO-1",
            customer_id=1001,
            order_type="客户转介",
            related_entity_type=None,
            related_entity_id=None,
        )
    }
    db = None

    @classmethod
    def _ensure_table_exists(cls):
        return None

    @classmethod
    def get_db_connection(cls):
        return cls.db

    @classmethod
    def get_by_id(cls, order_id):
        original = cls.records.get(order_id)
        return SimpleNamespace(**original.__dict__) if original else None


def test_work_order_claim_uses_atomic_compare_and_set():
    AtomicWorkOrderModel.records[1].status = "待处理"
    AtomicWorkOrderModel.records[1].handler_id = None
    AtomicWorkOrderModel.records[1].handled_by = None
    AtomicWorkOrderModel.records[1].handle_records = {"records": []}
    AtomicWorkOrderModel.db = AtomicWorkOrderDB(AtomicWorkOrderModel)
    gateway = ModelWorkOrderGateway(AtomicWorkOrderModel)

    def claim(handler_id):
        try:
            return gateway.claim(1, handler_id)["handler_id"]
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = list(pool.map(claim, (8, 9)))
    assert len([winner for winner in winners if winner is not None]) == 1
    assert AtomicWorkOrderModel.records[1].handler_id in {8, 9}


def test_operator_confirm_api_binds_employee_to_authenticated_user():
    source_path = Path(__file__).parents[1] / "app" / "WealthButler" / "Api" / "chatApi.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    request_classes = {
        node.name: {statement.target.id for statement in node.body if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)}
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name in {"ChatRequest", "DirectChatRequest", "OperatorConfirmRequest"}
    }
    assert all("user_id" not in fields and "employee_id" not in fields for fields in request_classes.values())

    confirm_function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "operator_confirm")
    calls = [node for node in ast.walk(confirm_function) if isinstance(node, ast.Call)]
    confirm_call = next(
        call for call in calls
        if isinstance(call.func, ast.Attribute) and call.func.attr == "confirm_operator_action"
    )
    employee_keyword = next(keyword for keyword in confirm_call.keywords if keyword.arg == "employee_id")
    assert ast.unparse(employee_keyword.value) == "current_user.id"
    assert any(
        isinstance(call.func, ast.Name) and call.func.id == "_authorize_agent"
        and call.args and isinstance(call.args[0], ast.Constant) and call.args[0].value == "operator"
        for call in calls
    )
