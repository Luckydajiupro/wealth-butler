"""WealthButler Web 入口配置的最小回归测试。"""

import pytest

from app.WealthButler.runtimeConfig import (
    DEFAULT_CORS_ORIGINS,
    load_operator_runtime_config,
    load_web_runtime_config,
    parse_bool,
)


def test_development_defaults_are_local_and_debug_is_disabled():
    config = load_web_runtime_config({})

    assert config.debug is False
    assert config.cors_origins == DEFAULT_CORS_ORIGINS
    assert config.cors_allow_credentials is True
    assert config.log_level == "info"


def test_wildcard_origin_forces_credentials_off():
    config = load_web_runtime_config({
        "WEALTH_BUTLER_CORS_ORIGINS": "https://example.com, *",
        "WEALTH_BUTLER_CORS_ALLOW_CREDENTIALS": "true",
    })

    assert config.cors_origins == ("*",)
    assert config.cors_allow_credentials is False


def test_explicit_development_overrides_are_parsed():
    config = load_web_runtime_config({
        "WEALTH_BUTLER_DEBUG": "yes",
        "WEALTH_BUTLER_CORS_ORIGINS": "http://localhost:3000, http://localhost:3000",
        "WEALTH_BUTLER_ACCESS_LOG": "off",
    })

    assert config.debug is True
    assert config.cors_origins == ("http://localhost:3000",)
    assert config.access_log is False
    assert config.log_level == "debug"


def test_invalid_boolean_is_rejected():
    with pytest.raises(ValueError, match="无效的布尔配置值"):
        parse_bool("enabled")


def test_operator_runtime_is_disabled_without_configuration():
    config = load_operator_runtime_config({})

    assert config.enabled is False
    assert config.mysql_host == ""


def test_enabled_operator_runtime_fails_closed_on_missing_configuration():
    with pytest.raises(ValueError, match="DB_HOST.*DEEPSEEK_API_KEY.*LOADER"):
        load_operator_runtime_config({"WEALTH_BUTLER_OPERATOR_REAL_ENABLED": "true"})


def test_operator_runtime_config_loads_complete_environment_without_secret_repr():
    config = load_operator_runtime_config({
        "WEALTH_BUTLER_OPERATOR_REAL_ENABLED": "true",
        "DB_HOST": "db.internal",
        "DB_PORT": "3307",
        "DB_USER": "wealth",
        "DB_PASSWORD": "mysql-secret",
        "DB_NAME": "wealth_butler",
        "REDIS_HOST": "redis.internal",
        "REDIS_DB": "2",
        "REDIS_PASSWORD": "redis-secret",
        "DEEPSEEK_API_KEY": "llm-secret",
        "DEEPSEEK_BASE_URL": "https://llm.internal/v1",
        "DEEPSEEK_DEFAULT_MODEL": "deepseek-chat",
        "WEALTH_BUTLER_OPERATOR_COMPLIANCE_EVIDENCE_LOADER": "pkg.loaders:evidence",
        "WEALTH_BUTLER_OPERATOR_HOLDING_SUMMARY_LOADER": "pkg.loaders:holdings",
        "WEALTH_BUTLER_OPERATOR_PAYEE_VERIFIER": "pkg.loaders:payee",
        "WEALTH_BUTLER_PAYEE_HMAC_KEY": "h" * 32,
    })

    assert config.enabled is True
    assert config.mysql_port == 3307
    assert config.redis_db == 2
    assert "mysql-secret" not in repr(config)
    assert "redis-secret" not in repr(config)
    assert "llm-secret" not in repr(config)


def test_operator_runtime_rejects_weak_payee_hmac_key():
    environment = {
        "WEALTH_BUTLER_OPERATOR_REAL_ENABLED": "true",
        "DB_HOST": "db.internal",
        "DB_USER": "wealth",
        "DB_PASSWORD": "mysql-secret",
        "DB_NAME": "wealth_butler",
        "REDIS_HOST": "redis.internal",
        "DEEPSEEK_API_KEY": "llm-secret",
        "DEEPSEEK_BASE_URL": "https://llm.internal/v1",
        "DEEPSEEK_DEFAULT_MODEL": "deepseek-chat",
        "WEALTH_BUTLER_OPERATOR_COMPLIANCE_EVIDENCE_LOADER": "pkg.loaders:evidence",
        "WEALTH_BUTLER_OPERATOR_HOLDING_SUMMARY_LOADER": "pkg.loaders:holdings",
        "WEALTH_BUTLER_OPERATOR_PAYEE_VERIFIER": "pkg.loaders:payee",
        "WEALTH_BUTLER_PAYEE_HMAC_KEY": "short",
    }

    with pytest.raises(ValueError, match="32"):
        load_operator_runtime_config(environment)
