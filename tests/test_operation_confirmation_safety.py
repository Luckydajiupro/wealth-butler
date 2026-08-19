from decimal import Decimal

import pytest

from app.WealthButler.Service.operationService import OperationService
from app.WealthButler.Service.chatService import ChatService
from app.WealthButler.Service.operatorContracts import OperationCommand


class _Transactions:
    def __init__(self):
        self.calls = []

    def execute(self, employee_id, customer_id, command, execution):
        self.calls.append((employee_id, customer_id, command, execution))
        return {
            "status": "成交",
            "transaction_id": len(self.calls),
            "transaction_type": {"purchase": "申购", "redeem": "赎回", "transfer": "转账"}[command.intent],
            "product_id": execution.get("product_id"),
            "amount": execution["amount"],
        }


class _Holdings:
    shares = Decimal("100")

    def get_position(self, customer_id, product_id):
        return {"shares": self.shares}

    def current_total_value(self, customer_id):
        return Decimal("100000")

    def current_r3_value(self, customer_id):
        return Decimal("0")


class _WorkOrders:
    def __init__(self):
        self.booking_calls = []

    def create_booking(self, customer_id, summary, product_id):
        self.booking_calls.append((customer_id, summary, product_id))
        return {"id": 1}

    def submit_for_review(self, *args):
        return {"id": 1}


class _Events:
    def publish(self, *args):
        return "event-1"

    def enqueue_retry(self, *args):
        return "retry-1"


def _service():
    transactions = _Transactions()
    holdings = _Holdings()
    product = {
        "product_id": 1,
        "product_name": "测试产品",
        "status": "在售",
        "risk_level": "R2",
        "min_investment": Decimal("100"),
        "nav": Decimal("2"),
        "admission_tier": "可执行",
    }
    work_orders = _WorkOrders()
    service = OperationService(
        permission_gateway=type("Permissions", (), {"has_permission": lambda self, employee_id, permission: True})(),
        customer_gateway=type("Customers", (), {"exists": lambda self, customer_id: True})(),
        advisor_qualification_gateway=type(
            "Advisors", (), {"get_advisor_level": lambda self, employee_id: "高级"}
        )(),
        product_gateway=type(
            "Products",
            (),
            {
                "get_product": lambda self, product_id: product,
                "list_products": lambda self, **filters: {},
            },
        )(),
        suitability_gateway=type(
            "Suitability", (), {"check": lambda self, customer_id, product_id: {"passed": True}}
        )(),
        purchase_compliance_gateway=type(
            "Compliance", (), {"validate_purchase": lambda self, customer_id, product, command: None}
        )(),
        holding_gateway=holdings,
        transaction_gateway=transactions,
        work_order_gateway=work_orders,
        risk_assessment_gateway=object(),
        customer_info_gateway=object(),
        risk_alert_gateway=object(),
        event_publisher=_Events(),
        operation_risk_gateway=type(
            "Risk",
            (),
            {
                "validate_redeem": lambda self, customer_id, product_id, shares: None,
                "validate_transfer": lambda self, customer_id, amount, payee: None,
            },
        )(),
        operation_audit_gateway=type("Audit", (), {"record": lambda self, entry: None})(),
    )
    return service, transactions, holdings, product, work_orders


def test_operator_product_detail_response_contains_actionable_fields():
    message = ChatService._format_operator_response({
        "success": True,
        "code": "PRODUCT_FOUND",
        "message": "产品查询成功",
        "data": {
            "product_name": "XX货币市场基金",
            "product_code": "FUND001",
            "product_type": "货币基金",
            "risk_level": "R1",
            "nav": Decimal("1.2345"),
            "nav_date": "2026-08-19",
            "min_investment": Decimal("1000"),
            "redemption_period_days": 1,
            "status": "在售",
        },
    })

    assert "产品名称：XX货币市场基金" in message
    assert "产品代码：FUND001" in message
    assert "最新净值：1.2345（2026-08-19）" in message
    assert "起购金额：1,000.00 元" in message
    assert message != "产品查询成功"

    unique_match = ChatService._format_operator_response({
        "success": True,
        "code": "PRODUCT_LISTED",
        "message": "共找到 1 只产品：XX货币市场基金（R1）",
        "data": {"items": [{
            "product_name": "XX货币市场基金",
            "product_code": "FUND001",
            "risk_level": "R1",
            "status": "在售",
        }], "total": 1},
    })
    assert "产品名称：XX货币市场基金" in unique_match
    assert "产品代码：FUND001" in unique_match


@pytest.mark.parametrize(
    ("intent", "params"),
    [
        ("purchase", {"product_id": 1, "amount": "1000"}),
        ("redeem", {"product_id": 1, "shares": "10"}),
        (
            "transfer",
            {
                "amount": "100",
                "counterparty_account": "622200001234",
                "counterparty_name": "测试收款人",
            },
        ),
    ],
)
def test_every_funds_operation_requires_explicit_confirmation(intent, params):
    service, transactions, _, _, _ = _service()

    result = service.submit(8, 1001, OperationCommand(intent, params, trace_id=f"trace-{intent}"))

    assert result.code == "CONFIRMATION_REQUIRED"
    assert result.metadata["confirm_required"] is True
    assert result.metadata["confirmation_policy"] == "explicit_confirmation_required"
    assert transactions.calls == []


def test_purchase_fails_before_confirmation_when_available_balance_is_insufficient():
    service, transactions, _, _, _ = _service()
    transactions.get_available_balance = lambda customer_id: Decimal("500.00")

    result = service.submit(
        8,
        1001,
        OperationCommand("purchase", {"product_id": 1, "amount": "1000"}, trace_id="trace-insufficient-cash"),
    )

    assert result.code == "INSUFFICIENT_AVAILABLE_BALANCE"
    assert "申购金额1000.00元" in result.message
    assert "可用余额500.00元" in result.message
    assert result.metadata["available_balance"] == "500.00"
    assert result.metadata.get("confirm_token") is None
    assert transactions.calls == []


def test_confirmation_rechecks_preflight_before_redeem_execution():
    service, transactions, holdings, _, _ = _service()
    pending = service.submit(
        8,
        1001,
        OperationCommand("redeem", {"product_id": 1, "shares": "10"}, trace_id="trace-redeem"),
    )
    holdings.shares = Decimal("5")

    result = service.confirm(pending.metadata["confirm_token"], 8, 1001)

    assert result.code == "INSUFFICIENT_REDEEMABLE_SHARES"
    assert transactions.calls == []


def test_confirmed_mock_transfer_executes_through_transaction_gateway():
    service, transactions, _, _, _ = _service()
    pending = service.submit(
        8,
        1001,
        OperationCommand(
            "transfer",
            {
                "amount": "100",
                "counterparty_account": "622200001234",
                "counterparty_name": "测试收款人",
            },
            trace_id="trace-transfer",
        ),
    )

    result = service.confirm(pending.metadata["confirm_token"], 8, 1001)

    assert result.success is True
    assert result.code == "TRANSACTION_SUCCEEDED"
    assert result.data["status"] == "成交"
    assert result.data["transaction_type"] == "转账"
    assert len(transactions.calls) == 1


def test_high_amount_threshold_is_enhanced_review_metadata_not_confirmation_gate():
    service, _, _, _, _ = _service()

    low = service.submit(8, 1001, OperationCommand("purchase", {"product_id": 1, "amount": "1000"}))
    high = service.submit(8, 1001, OperationCommand("purchase", {"product_id": 1, "amount": "20000"}))

    assert low.code == high.code == "CONFIRMATION_REQUIRED"
    assert low.metadata["enhanced_review_required"] is False
    assert high.metadata["enhanced_review_required"] is True


def test_booking_purchase_is_created_only_after_confirmation():
    service, transactions, _, product, work_orders = _service()
    product["admission_tier"] = "仅预约"

    pending = service.submit(
        8,
        1001,
        OperationCommand("purchase", {"product_id": 1, "amount": "1000"}, trace_id="trace-booking"),
    )

    assert pending.code == "CONFIRMATION_REQUIRED"
    assert work_orders.booking_calls == []

    result = service.confirm(pending.metadata["confirm_token"], 8, 1001)

    assert result.code == "BOOKING_CREATED"
    assert len(work_orders.booking_calls) == 1
    assert transactions.calls == []
