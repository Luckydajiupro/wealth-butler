"""业务管理员 REST 接口的角色与权限边界。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.WealthButler.Api import analystApi


def _credentials():
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")


def _user():
    return SimpleNamespace(id=7, status="active", source_module="fin")


def test_analyst_rest_requires_business_admin_role(monkeypatch):
    monkeypatch.setattr(analystApi.AuthService, "get_current_user", lambda _token: _user())
    monkeypatch.setattr(
        analystApi.AuthService,
        "get_user_role_info",
        lambda *_args, **_kwargs: {"role_names": ["advisor"]},
    )
    monkeypatch.setattr(analystApi.AuthService, "has_permission", lambda *_args, **_kwargs: True)

    with pytest.raises(HTTPException) as exc_info:
        analystApi._get_current_user(_credentials())

    assert exc_info.value.status_code == 403
    assert "业务管理员" in exc_info.value.detail


def test_analyst_rest_requires_nl2sql_permission(monkeypatch):
    monkeypatch.setattr(analystApi.AuthService, "get_current_user", lambda _token: _user())
    monkeypatch.setattr(
        analystApi.AuthService,
        "get_user_role_info",
        lambda *_args, **_kwargs: {"role_names": ["business_admin"]},
    )
    monkeypatch.setattr(analystApi.AuthService, "has_permission", lambda *_args, **_kwargs: False)

    with pytest.raises(HTTPException) as exc_info:
        analystApi._get_current_user(_credentials())

    assert exc_info.value.status_code == 403
    assert "data:nl2sql_query" in exc_info.value.detail


def test_analyst_rest_allows_authorized_business_admin(monkeypatch):
    user = _user()
    monkeypatch.setattr(analystApi.AuthService, "get_current_user", lambda _token: user)
    monkeypatch.setattr(
        analystApi.AuthService,
        "get_user_role_info",
        lambda *_args, **_kwargs: {"role_names": ["business_admin"]},
    )
    monkeypatch.setattr(analystApi.AuthService, "has_permission", lambda *_args, **_kwargs: True)

    assert analystApi._get_current_user(_credentials()) is user
