"""业务操作 Agent 的确定性输入策略。

同一策略同时服务于 NL2API 和 APIExecutor，避免模型解析入口与直接执行入口
对参数白名单产生分叉。
"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any, Dict, Tuple

from app.WealthButler.Service.operatorContracts import INTENT_PERMISSIONS, to_decimal


INTENT_REQUIRED_PARAMS = {
    "purchase": ("product_id", "amount"),
    "redeem": ("product_id", "shares"),
    "transfer": ("amount", "counterparty_account", "counterparty_name"),
    "reassess": ("answers",),
    "update_info": (),
    "product_query": (),
    "suspicious_report": ("description",),
    "workorder_create": ("order_type",),
}

INTENT_ALLOWED_PARAMS = {
    "purchase": {"product_id", "amount", "work_order_id"},
    "redeem": {"product_id", "shares"},
    "transfer": {"amount", "counterparty_account", "counterparty_name", "channel"},
    "reassess": {"answers"},
    "update_info": {"phone", "email"},
    "product_query": {"product_id", "product_type", "risk_level", "status", "keyword", "page", "per_page"},
    "suspicious_report": {"description", "severity", "related_transaction_id", "evidence_refs"},
    "workorder_create": {"order_type", "intent_summary"},
}

CONTEXT_PROTECTED_FIELDS = {
    "customer_id",
    "employee_id",
    "trace_id",
    "confirm_token",
    "permission",
    "permissions",
    "role",
    "idempotency_key",
}

PRODUCT_TYPES = {"公募基金", "私募基金", "银行理财", "保险", "信托", "结构性存款"}
PRODUCT_RISK_LEVELS = {"R1", "R2", "R3", "R4", "R5"}
PRODUCT_STATUSES = {"在售", "已下架", "封闭期"}
REPORT_SEVERITIES = {"low", "medium", "high"}
WORK_ORDER_TYPES = {"客户转介", "风控处置", "投诉建议", "其他"}


class OperationInputPolicy:
    """归一化已识别意图的参数，不负责从自然语言猜测业务事实。"""

    @classmethod
    def normalize(cls, intent: str, raw_params: Any) -> Dict[str, Any]:
        if intent not in INTENT_PERMISSIONS:
            return {"params": {}, "missing_params": [], "errors": [cls._error("UNKNOWN_INTENT", "intent", "不支持的业务操作意图")]}
        if not isinstance(raw_params, dict):
            return {"params": {}, "missing_params": [], "errors": [cls._error("PARAMS_INVALID", "params", "参数必须是对象")]}

        raw = dict(raw_params)
        protected = sorted(set(raw) & CONTEXT_PROTECTED_FIELDS)
        unknown = sorted(set(raw) - INTENT_ALLOWED_PARAMS[intent] - CONTEXT_PROTECTED_FIELDS)
        errors = [cls._error("CONTEXT_FIELD_FORBIDDEN", field, "该字段必须由可信会话上下文提供") for field in protected]
        errors.extend(cls._error("PARAMETER_FORBIDDEN", field, "该意图不允许该字段") for field in unknown)
        if errors:
            return {"params": {}, "missing_params": [], "errors": errors}

        normalized: Dict[str, Any] = {}
        for field, value in raw.items():
            try:
                normalized[field] = cls._normalize_field(intent, field, value)
            except ValueError as exc:
                errors.append(cls._error("PARAMETER_INVALID", field, str(exc)))

        if errors:
            return {"params": {}, "missing_params": [], "errors": errors}

        if intent == "product_query" and "product_id" in normalized and len(normalized) > 1:
            return {
                "params": {},
                "missing_params": [],
                "errors": [cls._error("PARAMETER_COMBINATION_INVALID", "product_id", "产品详情查询不能同时携带列表筛选条件")],
            }

        missing = [field for field in INTENT_REQUIRED_PARAMS[intent] if normalized.get(field) in (None, "")]
        return {"params": normalized, "missing_params": missing, "errors": []}

    @classmethod
    def _normalize_field(cls, intent: str, field: str, value: Any) -> Any:
        if value is None:
            return None
        if field in {"product_id", "work_order_id", "related_transaction_id", "page", "per_page"}:
            return cls._positive_integer(value, field)
        if field == "amount":
            return cls._currency(value, field)
        if field == "shares":
            return cls._positive_decimal(value, field)
        if field in {"counterparty_account", "counterparty_name", "channel", "phone", "email", "description", "intent_summary", "keyword"}:
            return cls._trimmed_string(value, field)
        if field == "answers":
            if not isinstance(value, list):
                raise ValueError("必须是答案数组")
            if any(
                not isinstance(answer, dict)
                or not isinstance(answer.get("question_id"), str)
                or not answer["question_id"].strip()
                for answer in value
            ):
                raise ValueError("每题答案必须是包含非空question_id的对象")
            return deepcopy(value)
        if field == "evidence_refs":
            if not isinstance(value, list):
                raise ValueError("必须是证据引用数组")
            return deepcopy(value)
        if field == "severity":
            return cls._enum(value, field, REPORT_SEVERITIES)
        if field == "order_type":
            return cls._enum(value, field, WORK_ORDER_TYPES)
        if field == "product_type":
            return cls._enum(value, field, PRODUCT_TYPES)
        if field == "risk_level":
            return cls._enum(value, field, PRODUCT_RISK_LEVELS)
        if field == "status":
            return cls._enum(value, field, PRODUCT_STATUSES)
        raise ValueError("不支持该参数")

    @staticmethod
    def _positive_integer(value: Any, field: str) -> int:
        if isinstance(value, bool) or isinstance(value, float):
            raise ValueError("必须是正整数")
        try:
            result = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("必须是正整数") from exc
        if result <= 0 or str(result) != str(value).strip().lstrip("+"):
            raise ValueError("必须是正整数")
        return result

    @staticmethod
    def _currency(value: Any, field: str) -> str:
        try:
            amount = to_decimal(value, field)
            rounded = amount.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("必须是大于0且最多两位小数的金额") from exc
        if amount <= 0 or amount != rounded:
            raise ValueError("必须是大于0且最多两位小数的金额")
        return f"{amount:.2f}"

    @staticmethod
    def _positive_decimal(value: Any, field: str) -> str:
        amount = to_decimal(value, field)
        if amount <= 0:
            raise ValueError("必须是大于0的数值")
        return format(amount, "f")

    @staticmethod
    def _trimmed_string(value: Any, field: str) -> str:
        if not isinstance(value, str):
            raise ValueError("必须是非空字符串")
        return value.strip()

    @staticmethod
    def _enum(value: Any, field: str, allowed: set[str]) -> str:
        normalized = OperationInputPolicy._trimmed_string(value, field)
        if normalized not in allowed:
            raise ValueError("取值不在允许枚举内")
        return normalized

    @staticmethod
    def _error(code: str, field: str, message: str) -> Dict[str, str]:
        return {"code": code, "field": field, "message": message}


def is_valid_confidence(value: Any) -> Tuple[bool, float]:
    """解析置信度；无效值一律按不可信处理。"""
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return False, 0.0
    return isfinite(confidence) and 0 <= confidence <= 1, confidence
