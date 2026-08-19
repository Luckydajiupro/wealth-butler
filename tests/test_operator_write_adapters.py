"""Operator 非交易写入 Adapter 的纯离线回归测试。"""

from datetime import datetime
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from app.WealthButler.Service.operatorWriteAdapters import (
    AuthCustomerInfoGateway,
    EventBusPublisherGateway,
    LoggingOperationAuditGateway,
    MySQLOperationAuditGateway,
    ModelWorkOrderGateway,
    RepositoryRiskAlertGateway,
    ServiceRiskAssessmentGateway,
)


class WorkOrderRecord:
    next_save_result = 1
    records = {}

    def __init__(self, **values):
        self.__dict__.update(values)
        self.id = values.get("id")
        self.deleted_at = values.get("deleted_at")
        self.handler_id = values.get("handler_id")
        self.handled_by = values.get("handled_by")
        self.handled_at = values.get("handled_at")

    def save(self):
        result = self.next_save_result
        if result > 0:
            self.id = result
            self.records[result] = self
        return result

    def update(self, **fields):
        self.__dict__.update(fields)
        return True

    @classmethod
    def get_by_id(cls, order_id):
        return cls.records.get(order_id)


def test_work_order_create_and_state_machine_check_write_results():
    WorkOrderRecord.records = {}
    WorkOrderRecord.next_save_result = 7
    gateway = ModelWorkOrderGateway(
        WorkOrderRecord,
        now=lambda: datetime(2026, 8, 17, 1, 2, 3),
        transition_writer=lambda order, expected, fields, handler: order.update(**fields),
    )

    created = gateway.create_booking(10, "预约私募产品", 22)
    assert created["id"] == 7
    assert created["order_type"] == "业务申请"
    assert created["related_entity_id"] == 22
    assert gateway.claim(7, 8)["status"] == "处理中"
    assert gateway.submit_for_review(7, 8, "等待审核")["status"] == "待审核"
    assert gateway.complete(7, 8, "product", 22, "审核通过")["status"] == "已完成"
    with pytest.raises(ValueError, match="不能从已完成"):
        gateway.reject(7, 8, "不能再驳回")

    WorkOrderRecord.next_save_result = -1
    with pytest.raises(RuntimeError, match="工单写入失败"):
        gateway.create_work_order(10, "其他", "失败样例")


class AssessmentServiceStub:
    saved_answers = None

    @classmethod
    def calculate_risk_level(cls, answers):
        cls.saved_answers = answers
        return Decimal("66.50"), "C4"


class AssessmentModelStub:
    save_result = 31

    def __init__(self, **fields):
        self.__dict__.update(fields)
        self.id = None

    def save(self):
        if self.save_result > 0:
            self.id = self.save_result
        return self.save_result


class ProfileServiceStub:
    @classmethod
    def get_comprehensive_profile(cls, customer_id, updated_reason):
        return SimpleNamespace(id=41, risk_level="C4")


def assessment_answers():
    answers = [
        {"question_id": f"Q{number}", "option_index": 1}
        for number in range(1, 17)
        if number != 7
    ]
    answers.append({"question_id": "Q7", "option_ids": [1, 3]})
    return answers


def test_risk_assessment_normalizes_q7_saves_and_recalculates_profile():
    AssessmentModelStub.save_result = 31
    gateway = ServiceRiskAssessmentGateway(
        AssessmentServiceStub,
        AssessmentModelStub,
        ProfileServiceStub,
        now=lambda: datetime(2026, 8, 17, 1, 2, 3),
    )

    result = gateway.submit_assessment(10, assessment_answers())
    assert AssessmentServiceStub.saved_answers[7] == 3
    assert result["assessment_id"] == 31
    assert result["total_score"] == Decimal("66.50")
    assert result["recalc_profile"] == {"profile_id": 41, "risk_level": "C4"}

    AssessmentModelStub.save_result = -1
    with pytest.raises(RuntimeError, match="风险评估写入失败"):
        gateway.submit_assessment(10, assessment_answers())


class UserModelStub:
    records = {}

    @classmethod
    def get_by_id(cls, user_id):
        return cls.records.get(user_id)


class AuthServiceStub:
    result = (True, "")
    call = None

    @classmethod
    def update_profile(cls, customer_id, **fields):
        cls.call = (customer_id, fields)
        target = UserModelStub.records.get(customer_id)
        if cls.result[0] and target:
            target.__dict__.update(fields)
        return cls.result


def test_customer_contact_update_enforces_customer_and_masks_response():
    UserModelStub.records = {
        10: SimpleNamespace(user_type="CUSTOMER", status="active", deleted_at=None, phone=None, email=None),
        11: SimpleNamespace(user_type="EMPLOYEE", status="active", deleted_at=None, phone=None, email=None),
    }
    AuthServiceStub.result = (True, "")
    gateway = AuthCustomerInfoGateway(AuthServiceStub, UserModelStub)

    result = gateway.update_contact(10, "13812345678", "alice@example.com")
    assert AuthServiceStub.call == (10, {"phone": "13812345678", "email": "alice@example.com"})
    assert result["phone_masked"] == "*******5678"
    assert result["email_masked"] == "a***@example.com"
    assert "13812345678" not in str(result)
    with pytest.raises(ValueError, match="有效客户"):
        gateway.update_contact(11, "13812345678", None)


class AlertRepositoryStub:
    result = SimpleNamespace(id=51, status="待处理")
    call = None

    @classmethod
    def create(cls, **fields):
        cls.call = fields
        return cls.result


def test_manual_risk_alert_checks_employee_and_failed_save():
    UserModelStub.records = {
        8: SimpleNamespace(user_type="EMPLOYEE", status="active", deleted_at=None, employee_role="理财顾问"),
    }
    AlertRepositoryStub.result = SimpleNamespace(id=51, status="待处理")
    gateway = RepositoryRiskAlertGateway(
        AlertRepositoryStub,
        UserModelStub,
        now=lambda: datetime(2026, 8, 17, 1, 2, 3),
    )

    result = gateway.report_suspicious_transaction(8, 10, "high", "异常拆分交易", 99, [{"type": "transaction", "id": 99}])
    assert result["alert_id"] == 51
    assert AlertRepositoryStub.call["confidence"] == Decimal("1.000")
    assert AlertRepositoryStub.call["trigger_details"]["reporter_role"] == "理财顾问"

    AlertRepositoryStub.result = None
    with pytest.raises(RuntimeError, match="预警写入失败"):
        gateway.report_suspicious_transaction(8, 10, "high", "异常", None, None)


class EventBusStub:
    result = b"123-0"
    calls = []

    @classmethod
    def publish(cls, *args):
        cls.calls.append(args)
        return cls.result


def test_event_publisher_validates_and_requires_message_id():
    validated = []
    EventBusStub.calls = []
    EventBusStub.result = b"123-0"
    gateway = EventBusPublisherGateway(EventBusStub, lambda event_type, payload: validated.append((event_type, payload)))

    assert gateway.publish("stream:x", "large_transaction", {"customer_id": 10}, "operator", "trace") == "123-0"
    assert validated == [("large_transaction", {"customer_id": 10})]
    retry_id = gateway.enqueue_retry("stream:x", "large_transaction", {"customer_id": 10}, "operator", "trace", "down")
    assert retry_id == "123-0"
    assert EventBusStub.calls[-1][0] == "stream:x:retry"
    retry_envelope = EventBusStub.calls[-1][2]
    assert gateway.replay_retry(retry_envelope, "trace") == "123-0"
    assert EventBusStub.calls[-1][:2] == ("stream:x", "large_transaction")
    assert gateway.handle_retry_event("operator_event_retry", retry_envelope, "trace") is True
    assert gateway.handle_retry_event("unexpected", retry_envelope, "trace") is False

    EventBusStub.result = ""
    with pytest.raises(RuntimeError, match="空 message_id"):
        gateway.publish("stream:x", "large_transaction", {"customer_id": 10}, "operator", "trace")


def test_operation_audit_keeps_only_names_and_masked_results():
    writes = []
    gateway = LoggingOperationAuditGateway(writes.append)
    gateway.record({
        "employee_id": 8,
        "customer_id": 10,
        "intent": "update_info",
        "trace_id": "secret-trace",
        "parameter_names": ["phone", "email", "bad name"],
        "success": True,
        "result_code": "CONTACT_UPDATED",
        "phone": "13812345678",
        "params": {"email": "alice@example.com"},
    })

    stored = json.loads(writes[0])
    assert stored["parameter_names"] == ["email", "phone"]
    assert stored["result_code"] == "CONTACT_UPDATED"
    assert stored["employee_ref"] != "8"
    assert "13812345678" not in writes[0]
    assert "alice@example.com" not in writes[0]
    assert "secret-trace" not in writes[0]

    with pytest.raises(RuntimeError, match="审计写入失败"):
        LoggingOperationAuditGateway(lambda _: False).record({"parameter_names": []})


class AuditCursorStub:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.rowcount = 0
        self.statement = None
        self.params = None
        self.closed = False

    def execute(self, statement, params):
        self.statement = " ".join(statement.split())
        self.params = params
        if self.fail:
            raise RuntimeError("db down")
        self.rowcount = 1

    def close(self):
        self.closed = True


class AuditConnectionStub:
    def __init__(self, *, fail=False):
        self.cursor_value = AuditCursorStub(fail=fail)
        self.begun = self.committed = self.rolled_back = self.closed = False

    def begin(self):
        self.begun = True

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_mysql_operation_audit_is_append_only_and_rolls_back_on_failure():
    connection = AuditConnectionStub()
    gateway = MySQLOperationAuditGateway(lambda: connection)
    gateway.record({
        "employee_id": 8,
        "customer_id": 10,
        "intent": "update_info",
        "trace_id": "operator:rest:123",
        "parameter_names": ["phone", "bad name", "email"],
        "success": False,
        "result_code": "CONTACT_UPDATE_FAILED",
        "phone": "13812345678",
    })

    assert connection.begun and connection.committed and connection.closed
    assert connection.cursor_value.statement.startswith("INSERT INTO `biz_operation_audit`")
    assert "UPDATE" not in connection.cursor_value.statement
    assert json.loads(connection.cursor_value.params[5]) == ["email", "phone"]
    assert "13812345678" not in repr(connection.cursor_value.params)
    assert connection.cursor_value.params[8] == "CONTACT_UPDATE_FAILED"

    failed = AuditConnectionStub(fail=True)
    with pytest.raises(RuntimeError, match="db down"):
        MySQLOperationAuditGateway(lambda: failed).record({
            "employee_id": 8,
            "customer_id": 10,
            "intent": "purchase",
            "trace_id": "operator:rest:456",
            "parameter_names": ["amount"],
            "success": True,
            "result_code": "TRANSACTION_SUCCEEDED",
        })
    assert failed.rolled_back and failed.closed and failed.cursor_value.closed
