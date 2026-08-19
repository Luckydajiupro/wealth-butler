"""正式 Operator Runtime 装配工厂的离线安全测试。"""

from types import SimpleNamespace

import pytest

from app.WealthButler.Service.confirmationService import InMemoryConfirmationGateway
from app.WealthButler.Service.operatorFakes import FakeEventPublisher
from app.WealthButler.Service.operatorRuntimeBuilder import create_real_runtime
from app.WealthButler.Service.redisConfirmationGateway import RedisConfirmationGateway


class StubIntentParser:
    def parse(self, user_input):
        return {"intent": "product_query", "confidence": 1.0, "extracted_params": {}}


class StubRedis:
    def eval(self, *args):
        return 1

    def hget(self, *args):
        return None

    def delete(self, *args):
        return 1


class StubTransactionGateway:
    def execute(self, *args, **kwargs):
        return {"status": "成交"}


class StubWorkOrderGateway:
    def create_booking(self, *args, **kwargs): pass
    def transition(self, *args, **kwargs): pass
    def create_work_order(self, *args, **kwargs): pass
    def claim(self, *args, **kwargs): pass
    def submit_for_review(self, *args, **kwargs): pass
    def complete(self, *args, **kwargs): pass
    def reject(self, *args, **kwargs): pass


class StubRiskAssessmentGateway:
    def submit_assessment(self, *args, **kwargs): pass


class StubCustomerInfoGateway:
    def update_contact(self, *args, **kwargs): pass


class StubRiskAlertGateway:
    def report_suspicious_transaction(self, *args, **kwargs): pass


class StubEventPublisher:
    def publish(self, *args, **kwargs): pass
    def enqueue_retry(self, *args, **kwargs): pass


class StubAuditGateway:
    def record(self, *args, **kwargs): pass


def _write_dependencies():
    return {
        "transaction_gateway": StubTransactionGateway(),
        "work_order_gateway": StubWorkOrderGateway(),
        "risk_assessment_gateway": StubRiskAssessmentGateway(),
        "customer_info_gateway": StubCustomerInfoGateway(),
        "risk_alert_gateway": StubRiskAlertGateway(),
        "event_publisher": StubEventPublisher(),
        "operation_audit_gateway": StubAuditGateway(),
    }


def _real_builder_kwargs():
    return {
        "intent_parser": StubIntentParser(),
        "redis_client": StubRedis(),
        "compliance_evidence_loader": lambda customer_id, product_id: {},
        "holding_summary_loader": lambda customer_id, risk_level: {
            "total_value": "0",
            "risk_level_value": "0",
        },
        "payee_verifier": lambda customer_id, payee: True,
        **_write_dependencies(),
    }


def test_builder_creates_real_runtime_with_real_rule_and_redis_adapters():
    runtime = create_real_runtime(**_real_builder_kwargs())

    assert runtime.runtime_mode == "real"
    assert runtime.service is runtime.agent.operation_service
    assert isinstance(runtime.confirmations, RedisConfirmationGateway)
    assert type(runtime.suitability_gateway).__name__ == "ModelSuitabilityGateway"
    assert type(runtime.purchase_compliance_gateway).__name__ == "ModelPurchaseComplianceGateway"
    assert type(runtime.operation_risk_gateway).__name__ == "ModelOperationRiskGateway"


def test_builder_rejects_missing_write_dependency():
    kwargs = _real_builder_kwargs()
    kwargs["transaction_gateway"] = None

    with pytest.raises(ValueError, match="transaction_gateway"):
        create_real_runtime(**kwargs)


def test_builder_rejects_fake_dependency():
    kwargs = _real_builder_kwargs()
    kwargs["event_publisher"] = FakeEventPublisher()

    with pytest.raises(TypeError, match="禁止使用 Fake.*event_publisher"):
        create_real_runtime(**kwargs)


def test_builder_rejects_in_memory_confirmation_gateway():
    kwargs = _real_builder_kwargs()
    kwargs.pop("redis_client")
    kwargs["confirmation_gateway"] = InMemoryConfirmationGateway()

    with pytest.raises(TypeError, match="必须是 RedisConfirmationGateway"):
        create_real_runtime(**kwargs)


def test_builder_rejects_invalid_redis_client_before_runtime_creation():
    kwargs = _real_builder_kwargs()
    kwargs["redis_client"] = SimpleNamespace()

    with pytest.raises(TypeError, match="redis_client 未实现必要方法"):
        create_real_runtime(**kwargs)


def test_builder_requires_fail_closed_rule_loaders_when_auto_constructing():
    kwargs = _real_builder_kwargs()
    kwargs["compliance_evidence_loader"] = None

    with pytest.raises(ValueError, match="compliance_evidence_loader"):
        create_real_runtime(**kwargs)

