"""正式 Web 入口所需的轻量运行配置。"""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


# 正式入口配置统一从项目根目录 .env 读取；不覆盖部署环境已注入的值。
load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env", override=False)


DEFAULT_CORS_ORIGINS = (
    "http://localhost:8010",
    "http://127.0.0.1:8010",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def parse_bool(value: str | None, *, default: bool = False) -> bool:
    """解析常见环境变量布尔值，拒绝拼写错误以免静默降低安全性。"""
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"无效的布尔配置值: {value!r}")


def parse_cors_origins(value: str | None) -> tuple[str, ...]:
    """解析逗号分隔的 CORS 来源；通配符存在时忽略其他来源。"""
    if value is None or not value.strip():
        return DEFAULT_CORS_ORIGINS
    origins = tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    if not origins:
        return DEFAULT_CORS_ORIGINS
    return ("*",) if "*" in origins else origins


@dataclass(frozen=True)
class WebRuntimeConfig:
    debug: bool
    cors_origins: tuple[str, ...]
    cors_allow_credentials: bool
    access_log: bool
    log_level: str


@dataclass(frozen=True)
class OperatorRuntimeConfig:
    """正式 Operator Runtime 配置；敏感字段不参与 repr。"""

    enabled: bool = False
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = field(default="", repr=False)
    mysql_database: str = ""
    mysql_charset: str = "utf8mb4"
    mysql_connect_timeout: int = 10
    redis_host: str = ""
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = field(default=None, repr=False)
    redis_socket_timeout: float = 5.0
    llm_api_key: str = field(default="", repr=False)
    llm_base_url: str = ""
    llm_model: str = ""
    llm_timeout: float = 30.0
    compliance_evidence_loader: str = ""
    holding_summary_loader: str = ""
    payee_verifier: str = ""


def load_web_runtime_config(environ: Mapping[str, str] | None = None) -> WebRuntimeConfig:
    """从环境读取 Web 配置，并保证凭证模式不与通配来源组合。"""
    env = os.environ if environ is None else environ
    debug = parse_bool(env.get("WEALTH_BUTLER_DEBUG"), default=False)
    origins = parse_cors_origins(env.get("WEALTH_BUTLER_CORS_ORIGINS"))
    requested_credentials = parse_bool(
        env.get("WEALTH_BUTLER_CORS_ALLOW_CREDENTIALS"),
        default=True,
    )
    access_log = parse_bool(env.get("WEALTH_BUTLER_ACCESS_LOG"), default=True)
    log_level = env.get("WEALTH_BUTLER_LOG_LEVEL", "debug" if debug else "info").strip().lower()
    if log_level not in {"critical", "error", "warning", "info", "debug", "trace"}:
        raise ValueError(f"无效的日志级别: {log_level!r}")
    return WebRuntimeConfig(
        debug=debug,
        cors_origins=origins,
        cors_allow_credentials=requested_credentials and origins != ("*",),
        access_log=access_log,
        log_level=log_level,
    )


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    try:
        value = default if raw is None or not raw.strip() else int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是正整数") from exc
    if value <= 0:
        raise ValueError(f"{name} 必须是正整数")
    return value


def _non_negative_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    try:
        value = default if raw is None or not raw.strip() else int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是非负整数") from exc
    if value < 0:
        raise ValueError(f"{name} 必须是非负整数")
    return value


def _positive_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    try:
        value = default if raw is None or not raw.strip() else float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是正数") from exc
    if value <= 0:
        raise ValueError(f"{name} 必须是正数")
    return value


def load_operator_runtime_config(
    environ: Mapping[str, str] | None = None,
) -> OperatorRuntimeConfig:
    """读取正式 Operator 配置；开关关闭时不要求任何外部服务配置。"""
    env = os.environ if environ is None else environ
    enabled = parse_bool(env.get("WEALTH_BUTLER_OPERATOR_REAL_ENABLED"), default=False)
    if not enabled:
        return OperatorRuntimeConfig()

    required_names = (
        "DB_HOST",
        "DB_USER",
        "DB_PASSWORD",
        "DB_NAME",
        "REDIS_HOST",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_DEFAULT_MODEL",
        "WEALTH_BUTLER_OPERATOR_COMPLIANCE_EVIDENCE_LOADER",
        "WEALTH_BUTLER_OPERATOR_HOLDING_SUMMARY_LOADER",
        "WEALTH_BUTLER_OPERATOR_PAYEE_VERIFIER",
        "WEALTH_BUTLER_PAYEE_HMAC_KEY",
    )
    missing = [name for name in required_names if not str(env.get(name, "")).strip()]
    if missing:
        raise ValueError("正式 Operator Runtime 缺少配置: " + ", ".join(missing))
    if len(str(env["WEALTH_BUTLER_PAYEE_HMAC_KEY"]).encode("utf-8")) < 32:
        raise ValueError("WEALTH_BUTLER_PAYEE_HMAC_KEY 至少需32字节")
    charset = str(env.get("DB_CHARSET", "utf8mb4")).strip()
    if charset not in {"utf8mb4", "utf8"}:
        raise ValueError("DB_CHARSET 仅支持 utf8mb4 或 utf8")
    return OperatorRuntimeConfig(
        enabled=True,
        mysql_host=str(env["DB_HOST"]).strip(),
        mysql_port=_positive_int(env, "DB_PORT", 3306),
        mysql_user=str(env["DB_USER"]).strip(),
        mysql_password=str(env["DB_PASSWORD"]),
        mysql_database=str(env["DB_NAME"]).strip(),
        mysql_charset=charset,
        mysql_connect_timeout=_positive_int(env, "DB_CONNECT_TIMEOUT", 10),
        redis_host=str(env["REDIS_HOST"]).strip(),
        redis_port=_positive_int(env, "REDIS_PORT", 6379),
        redis_db=_non_negative_int(env, "REDIS_DB", 0),
        redis_password=str(env["REDIS_PASSWORD"]) if env.get("REDIS_PASSWORD") else None,
        redis_socket_timeout=_positive_float(env, "REDIS_SOCKET_TIMEOUT", 5.0),
        llm_api_key=str(env["DEEPSEEK_API_KEY"]),
        llm_base_url=str(env["DEEPSEEK_BASE_URL"]).strip(),
        llm_model=str(env["DEEPSEEK_DEFAULT_MODEL"]).strip(),
        llm_timeout=_positive_float(env, "LLM_TIMEOUT", 30.0),
        compliance_evidence_loader=str(
            env["WEALTH_BUTLER_OPERATOR_COMPLIANCE_EVIDENCE_LOADER"]
        ).strip(),
        holding_summary_loader=str(
            env["WEALTH_BUTLER_OPERATOR_HOLDING_SUMMARY_LOADER"]
        ).strip(),
        payee_verifier=str(env["WEALTH_BUTLER_OPERATOR_PAYEE_VERIFIER"]).strip(),
    )
