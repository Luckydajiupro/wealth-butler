"""认证安全基线测试。"""

from datetime import timedelta

import pytest

from app.Base.Config.setting import settings
from app.Base.Service.authService import AuthService


def test_jwt_signing_fails_closed_without_secret(monkeypatch):
    monkeypatch.setattr(settings.auth, "jwt_secret", None)

    with pytest.raises(RuntimeError, match="JWT_SECRET 未配置"):
        AuthService._create_jwt({"sub": "1"}, timedelta(minutes=1))


def test_jwt_verification_fails_closed_without_secret(monkeypatch):
    monkeypatch.setattr(settings.auth, "jwt_secret", None)

    with pytest.raises(RuntimeError, match="JWT_SECRET 未配置"):
        AuthService.verify_token("untrusted-token")


def test_jwt_round_trip_with_explicit_secret(monkeypatch):
    monkeypatch.setattr(settings.auth, "jwt_secret", "test-only-secret-not-for-production")

    token = AuthService._create_jwt(
        {"sub": "42", "source_module": "wealth", "type": "access"},
        timedelta(minutes=1),
    )

    payload = AuthService.verify_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["source_module"] == "wealth"
