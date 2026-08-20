"""Authentication cookie and bearer-session consistency contracts."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response

from app.Base.Api import authApi


def _user(user_id: int, status: str = "active"):
    return SimpleNamespace(id=user_id, status=status)


def test_browser_cookie_and_bearer_must_resolve_to_same_user(monkeypatch) -> None:
    bearer_user = _user(11)
    monkeypatch.setattr(authApi.AuthService, "get_current_user", lambda token: _user(11) if token == "same" else _user(22))

    assert authApi._require_consistent_browser_session(bearer_user, "same") is bearer_user

    with pytest.raises(HTTPException) as exc_info:
        authApi._require_consistent_browser_session(bearer_user, "different")
    assert exc_info.value.status_code == 401
    assert "会话不一致" in exc_info.value.detail


def test_invalid_workbench_cookie_requires_fresh_login(monkeypatch) -> None:
    monkeypatch.setattr(authApi.AuthService, "get_current_user", lambda _token: None)

    with pytest.raises(HTTPException) as exc_info:
        authApi._require_consistent_browser_session(_user(11), "expired")
    assert exc_info.value.status_code == 401
    assert "页面登录状态已失效" in exc_info.value.detail


def test_logout_expires_http_only_workbench_cookie() -> None:
    response = Response()

    result = authApi.logout(response)

    set_cookie = response.headers.get("set-cookie", "")
    assert result.status_code == 200
    assert "wealth_access_token=" in set_cookie
    assert "Max-Age=0" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/" in set_cookie
    assert "SameSite=lax" in set_cookie


def test_refresh_updates_workbench_cookie_with_new_access_token(monkeypatch) -> None:
    monkeypatch.setattr(
        authApi.AuthService,
        "refresh_access_token",
        lambda refresh_token: (True, "new-access-token", "ok"),
    )
    response = Response()

    result = authApi.refresh(authApi.RefreshRequest(refresh_token="opaque-refresh"), response)

    set_cookie = response.headers.get("set-cookie", "")
    assert result.status_code == 200
    assert result.data["access_token"] == "new-access-token"
    assert "wealth_access_token=new-access-token" in set_cookie
    assert "HttpOnly" in set_cookie
