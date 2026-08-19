"""Operator 真实只读 Adapter 的隔离回归测试。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.WealthButler.Service.operatorRealAdapters import (
    AuthPermissionGateway,
    ModelAdvisorQualificationGateway,
    ModelCustomerGateway,
    ModelHoldingGateway,
    ModelProductGateway,
)


def record(**values):
    return SimpleNamespace(**values)


class UserModelStub:
    records = {}

    @classmethod
    def get_by_id(cls, user_id):
        return cls.records.get(user_id)


class AuthServiceStub:
    calls = []

    @classmethod
    def has_permission(cls, user_id, permission, source_module=None):
        cls.calls.append((user_id, permission, source_module))
        return permission == "operation:purchase"


def user(user_type, **overrides):
    values = {
        "user_type": user_type,
        "status": "active",
        "deleted_at": None,
        "source_module": "fin",
        "employee_role": None,
        "advisor_level": None,
    }
    values.update(overrides)
    return record(**values)


def test_permission_customer_and_employee_boundaries_fail_closed():
    UserModelStub.records = {
        1: user("EMPLOYEE"),
        2: user("CUSTOMER"),
        3: user("EMPLOYEE", status="inactive"),
        4: user("EMPLOYEE", deleted_at="deleted"),
    }
    AuthServiceStub.calls = []
    gateway = AuthPermissionGateway(AuthServiceStub, UserModelStub)

    assert gateway.has_permission(1, "operation:purchase") is True
    assert gateway.has_permission(1, "operation:transfer") is False
    assert gateway.has_permission(2, "operation:purchase") is False
    assert gateway.has_permission(3, "operation:purchase") is False
    assert gateway.has_permission(4, "operation:purchase") is False
    assert AuthServiceStub.calls == [
        (1, "operation:purchase", "fin"),
        (1, "operation:transfer", "fin"),
    ]


def test_customer_and_advisor_gateways_enforce_type_status_and_role():
    UserModelStub.records = {
        10: user("CUSTOMER"),
        11: user("CUSTOMER", status="banned"),
        12: user("EMPLOYEE", employee_role="理财顾问", advisor_level="高级"),
        13: user("EMPLOYEE", employee_role="客户经理", advisor_level="高级"),
        14: user("EMPLOYEE", employee_role="理财顾问", advisor_level="专家"),
    }

    customers = ModelCustomerGateway(UserModelStub)
    advisors = ModelAdvisorQualificationGateway(UserModelStub)

    assert customers.exists(10) is True
    assert customers.exists(11) is False
    assert customers.exists(12) is False
    assert advisors.get_advisor_level(12) is None
    assert advisors.get_advisor_level(13) == "高级"
    assert advisors.get_advisor_level(14) is None


class ProductModelStub:
    records = [
        record(id=1, product_code="PUB-1", product_name="稳健公募一号", product_type="公募基金", risk_level="R2", min_investment=Decimal("100.00"), redemption_period_days=1, nav=Decimal("1.2345"), nav_date=None, industry="综合", fund_manager="甲", status="在售", description=None),
        record(id=2, product_code="PRI-1", product_name="进取私募一号", product_type="私募基金", risk_level="R4", min_investment=Decimal("1000.00"), redemption_period_days=7, nav=Decimal("2.0000"), nav_date=None, industry="科技", fund_manager="乙", status="在售", description=None),
        record(id=3, product_code="PUB-2", product_name="稳健公募二号", product_type="公募基金", risk_level="R2", min_investment=Decimal("200.00"), redemption_period_days=1, nav=Decimal("1.1000"), nav_date=None, industry="综合", fund_manager="丙", status="已下架", description=None),
    ]

    @classmethod
    def get_by_id(cls, product_id):
        return next((item for item in cls.records if item.id == product_id), None)

    @classmethod
    def find_by(cls, order_by=None, order="ASC", **filters):
        assert order_by == "id" and order == "ASC"
        return [
            item for item in cls.records
            if all(getattr(item, field) == value for field, value in filters.items())
        ]


def test_product_mapping_filtering_decimal_and_bounded_pagination():
    gateway = ModelProductGateway(ProductModelStub)

    private_product = gateway.get_product(2)
    assert private_product["product_id"] == 2
    assert private_product["admission_tier"] == "仅预约"
    assert private_product["min_investment"] == Decimal("1000.00")

    result = gateway.list_products(
        product_type="公募基金",
        risk_level="R2",
        keyword="稳健",
        page=2,
        per_page=1,
    )
    assert result == {
        "items": [gateway.get_product(3)],
        "total": 2,
        "page": 2,
        "per_page": 1,
    }
    with pytest.raises(ValueError, match="不能超过 100"):
        gateway.list_products(per_page=101)
    with pytest.raises(ValueError, match="不支持的产品筛选字段"):
        gateway.list_products(drop_table=True)


class HoldingsModelStub:
    positions = [
        record(customer_id=10, product_id=1, shares=Decimal("10"), current_value=Decimal("100.25"), cost_amount=Decimal("80"), deleted_at=None),
        record(customer_id=10, product_id=2, shares=Decimal("5"), current_value=Decimal("50.75"), cost_amount=Decimal("40"), deleted_at=None),
        record(customer_id=10, product_id=1, shares=Decimal("1"), current_value=Decimal("999"), cost_amount=Decimal("1"), deleted_at="deleted"),
        record(customer_id=10, product_id=1, shares=Decimal("0"), current_value=Decimal("888"), cost_amount=Decimal("1"), deleted_at=None),
    ]

    @classmethod
    def find_by_customer_id(cls, customer_id):
        return [item for item in cls.positions if item.customer_id == customer_id]

    @classmethod
    def find_by_customer_and_product(cls, customer_id, product_id):
        return next(
            (item for item in cls.positions if item.customer_id == customer_id and item.product_id == product_id),
            None,
        )


class HoldingProductModelStub:
    @classmethod
    def get_by_id(cls, product_id):
        risk_levels = {1: "R3", 2: "R4"}
        risk_level = risk_levels.get(product_id)
        return record(risk_level=risk_level) if risk_level else None


def test_holding_values_use_decimal_and_exclude_deleted_or_empty_positions():
    gateway = ModelHoldingGateway(HoldingsModelStub, HoldingProductModelStub)

    assert gateway.current_total_value(10) == Decimal("151.00")
    assert gateway.current_r3_value(10) == Decimal("100.25")
    position = gateway.get_position(10, 1)
    assert position["shares"] == Decimal("10")
    assert position["current_value"] == Decimal("100.25")
    assert position["average_cost"] == Decimal("8")
    assert gateway.get_position(10, 999)["shares"] == Decimal("0")

    HoldingsModelStub.positions[0].current_value = "not-a-number"
    with pytest.raises(ValueError, match="有效 Decimal"):
        gateway.current_total_value(10)
    HoldingsModelStub.positions[0].current_value = Decimal("100.25")
