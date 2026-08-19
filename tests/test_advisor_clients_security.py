"""员工客户选择接口的数据隔离回归测试。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.WealthButler.Api import advisorApi


def _credentials():
    return SimpleNamespace(credentials="test-token")


def test_customer_account_cannot_list_all_clients(monkeypatch) -> None:
    monkeypatch.setattr(
        advisorApi.AuthService,
        "get_current_user",
        lambda _token: SimpleNamespace(id=1, status="active"),
    )
    monkeypatch.setattr(
        advisorApi.BaseUserExtModel,
        "get_by_id",
        lambda _user_id: SimpleNamespace(user_type="CUSTOMER"),
    )
    monkeypatch.setattr(
        advisorApi.AuthService,
        "get_user_role_info",
        lambda *_args: {"role_names": [], "is_super_admin": False},
    )

    with pytest.raises(HTTPException) as exc_info:
        advisorApi.get_advisor_clients(credentials=_credentials())

    assert exc_info.value.status_code == 403


def test_employee_client_query_filters_customer_rows(monkeypatch) -> None:
    statements = []

    class FakeDb:
        def execute(self, sql, params=None):
            statements.append((sql, params))
            if "COUNT(*)" in sql:
                return [{"total": 1}]
            return [{"id": 7, "username": "customer0007", "phone": "13800000007", "created_at": None}]

    monkeypatch.setattr(
        advisorApi.AuthService,
        "get_current_user",
        lambda _token: SimpleNamespace(id=200, status="active", source_module="fin"),
    )
    monkeypatch.setattr(
        advisorApi.BaseUserExtModel,
        "get_by_id",
        lambda _user_id: SimpleNamespace(user_type="EMPLOYEE", employee_role="理财顾问"),
    )
    monkeypatch.setattr(
        advisorApi.AuthService,
        "get_user_role_info",
        lambda *_args: {"role_names": ["advisor"], "is_super_admin": False},
    )
    monkeypatch.setattr(advisorApi.UserModel, "get_db_connection", lambda: FakeDb())
    monkeypatch.setattr(advisorApi.RiskAssessmentModel, "find_valid_by_customer_id", lambda _customer_id: None)

    response = advisorApi.get_advisor_clients(limit=20, offset=0, credentials=_credentials())

    assert response.status_code == 200
    assert all("user_type = 'CUSTOMER'" in sql for sql, _params in statements)
    assert all("advisor_id = %s" in sql for sql, _params in statements)
    assert statements[0][1] == (200, 200)
    assert statements[1][1] == (200, 200, 20, 0)
    assert response.data["clients"][0]["risk_level"] is None
    assert response.data["scope"] == "assigned"


def test_employee_client_list_uses_only_current_valid_assessment(monkeypatch) -> None:
    class FakeDb:
        def execute(self, sql, params=None):
            if "COUNT(*)" in sql:
                return [{"total": 1}]
            return [{"id": 7, "username": "customer0007", "phone": None, "created_at": None}]

    monkeypatch.setattr(
        advisorApi.AuthService,
        "get_current_user",
        lambda _token: SimpleNamespace(id=200, status="active", source_module="fin"),
    )
    monkeypatch.setattr(
        advisorApi.BaseUserExtModel,
        "get_by_id",
        lambda _user_id: SimpleNamespace(user_type="EMPLOYEE", employee_role="理财顾问"),
    )
    monkeypatch.setattr(
        advisorApi.AuthService,
        "get_user_role_info",
        lambda *_args: {"role_names": ["advisor"], "is_super_admin": False},
    )
    monkeypatch.setattr(advisorApi.UserModel, "get_db_connection", lambda: FakeDb())
    monkeypatch.setattr(
        advisorApi.RiskAssessmentModel,
        "find_valid_by_customer_id",
        lambda _customer_id: SimpleNamespace(risk_level="C2", total_score=35),
    )

    response = advisorApi.get_advisor_clients(limit=20, offset=0, credentials=_credentials())

    assert response.data["clients"][0]["risk_level"] == "C2"
    assert response.data["clients"][0]["risk_score"] == 35.0


def test_super_admin_client_query_can_use_all_customer_scope(monkeypatch) -> None:
    statements = []

    class FakeDb:
        def execute(self, sql, params=None):
            statements.append((sql, params))
            if "COUNT(*)" in sql:
                return [{"total": 0}]
            return []

    monkeypatch.setattr(
        advisorApi.AuthService,
        "get_current_user",
        lambda _token: SimpleNamespace(id=1, status="active", source_module="fin"),
    )
    monkeypatch.setattr(
        advisorApi.BaseUserExtModel,
        "get_by_id",
        lambda _user_id: SimpleNamespace(user_type="EMPLOYEE", employee_role="业务管理员"),
    )
    monkeypatch.setattr(
        advisorApi.AuthService,
        "get_user_role_info",
        lambda *_args: {"role_names": ["super_admin"], "is_super_admin": True},
    )
    monkeypatch.setattr(advisorApi.UserModel, "get_db_connection", lambda: FakeDb())

    response = advisorApi.get_advisor_clients(limit=20, offset=0, credentials=_credentials())

    assert response.data["scope"] == "all"
    assert all("advisor_id = %s" not in sql for sql, _params in statements)
    assert statements[0][1] == ()
    assert statements[1][1] == (20, 0)
