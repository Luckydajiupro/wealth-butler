"""角色工作台必须由服务端授权，不能只依赖 localStorage。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.WealthButler.Api import frontendApi


def _install_user(monkeypatch, roles):
    user = SimpleNamespace(id=17, source_module="fin", status="active")
    monkeypatch.setattr(frontendApi.AuthService, "get_current_user", lambda token: user if token == "valid" else None)
    monkeypatch.setattr(
        frontendApi.AuthService,
        "get_user_role_info",
        lambda user_id, source_module: {"role_names": roles},
    )


@pytest.mark.parametrize(
    ("path", "role"),
    [
        ("/chat/advisor", "advisor"),
        ("/chat/operator", "operator"),
        ("/chat/risk", "risk_officer"),
        ("/chat/analyst", "business_admin"),
    ],
)
def test_workbench_requires_its_own_server_side_role(monkeypatch, path, role):
    _install_user(monkeypatch, [role])

    assert frontendApi._require_page_role(path, "valid", None).id == 17

    _install_user(monkeypatch, ["advisor"])
    if role == "advisor":
        return
    with pytest.raises(HTTPException) as exc_info:
        frontendApi._require_page_role(path, "valid", None)
    assert exc_info.value.status_code == 403


def test_workbench_rejects_missing_or_invalid_credentials(monkeypatch):
    _install_user(monkeypatch, ["advisor"])

    with pytest.raises(HTTPException) as missing:
        frontendApi._require_page_role("/chat/advisor", None, None)
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as invalid:
        frontendApi._require_page_role("/chat/advisor", "invalid", None)
    assert invalid.value.status_code == 401

