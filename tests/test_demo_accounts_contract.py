"""Quick-login account selection contracts."""

from app.Base.Api.authApi import _demo_login_kind


def test_demo_login_kind_accepts_supported_seed_accounts() -> None:
    assert _demo_login_kind("测试员工", "测试员工", "EMPLOYEE") == "employee_named"
    assert _demo_login_kind("测试客户001", "测试客户", "CUSTOMER") == "customer_numbered"


def test_demo_login_kind_rejects_accounts_from_other_seed_rules() -> None:
    assert _demo_login_kind("wb_seed_operator", "测试经理", "EMPLOYEE") is None
    assert _demo_login_kind("wb_seed_customer_001", "测试客户", "CUSTOMER") is None
    assert _demo_login_kind("测试客户", "测试客户", "CUSTOMER") is None
