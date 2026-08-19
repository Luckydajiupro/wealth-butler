"""Operator 正式运行时的合规只读 Loader。

Loader 只依赖现有 Model 和 Python 标准库，并支持注入替代读取器，便于在不连接
真实数据库的情况下验证 fail-closed 行为。任何缺失、过期、撤销或格式异常都不
会被解释为合规通过。
"""

from __future__ import annotations

import hmac
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Mapping, Optional

from app.WealthButler.Utils.payeeFingerprint import (
    fingerprint,
    normalize_account,
    normalize_name,
)


EVIDENCE_CONTROLS = {
    "risk_disclosure_signed": "RISK_DISCLOSURE_SIGNED",
    "risk_notification_acknowledged": "RISK_NOTIFICATION_ACKNOWLEDGED",
    "guardian_consent_signed": "GUARDIAN_CONSENT_SIGNED",
    "in_person_risk_confirmation_signed": "IN_PERSON_RISK_CONFIRMATION_SIGNED",
    "double_record_completed": "DOUBLE_RECORD_COMPLETED",
}
PAYEE_HMAC_KEY_ENV = "WEALTH_BUTLER_PAYEE_HMAC_KEY"


def _value(record: Any, name: str, default: Any = None) -> Any:
    return record.get(name, default) if isinstance(record, Mapping) else getattr(record, name, default)


def _now_compatible(value: datetime, now: datetime) -> tuple[datetime, datetime]:
    if value.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=value.tzinfo)
    elif value.tzinfo is None and now.tzinfo is not None:
        value = value.replace(tzinfo=now.tzinfo)
    return value, now


def _is_unexpired(valid_until: Any, now: datetime) -> bool:
    if not isinstance(valid_until, datetime):
        return False
    valid_until, now = _now_compatible(valid_until, now)
    return valid_until > now


def _is_evidence_effective(valid_until: Any, now: datetime) -> bool:
    # 合规证据表明确约定 NULL 表示长期有效；收款方表不采用这一宽松语义。
    return valid_until is None or _is_unexpired(valid_until, now)


def _default_evidence_finder(customer_id: int, product_id: int, evidence_type: str) -> Any:
    # 延迟导入避免模块加载时触发 Model/数据库初始化。
    from app.WealthButler.Models.complianceEvidenceModel import ComplianceEvidenceModel

    return ComplianceEvidenceModel.find_latest_by_customer_product_type(
        customer_id, product_id, evidence_type
    )


def _default_double_record_context(customer_id: int) -> dict[str, Any]:
    from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel
    from app.WealthButler.Models.productModel import ProductModel
    from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel
    from app.WealthButler.Models.transactionModel import TransactionModel

    user = BaseUserExtModel.get_by_id(customer_id)
    if user is None:
        raise RuntimeError("客户不存在")
    extra_data = _value(user, "extra_data")
    birthday = extra_data.get("birthday") if isinstance(extra_data, Mapping) else None
    age: Optional[int] = None
    try:
        age = _calculate_age(birthday, date.today())
        is_age_65_plus: Optional[bool] = age >= 65
    except ValueError:
        assessment = RiskAssessmentModel.find_latest_by_customer_id(customer_id)
        is_age_65_plus = _is_age_65_plus_from_answers(_value(assessment, "answers"))
    has_prior = False
    for transaction in TransactionModel.find_by_customer_id(customer_id, limit=1000):
        if _value(transaction, "transaction_type") != "申购" or _value(transaction, "status") != "成交":
            continue
        product_id = _value(transaction, "product_id")
        product = ProductModel.get_by_id(product_id) if _positive_int(product_id) else None
        if _value(product, "risk_level") in {"R3", "R4", "R5"}:
            has_prior = True
            break
    result: dict[str, Any] = {
        "is_age_65_plus": is_age_65_plus,
        "has_prior_r3_plus_purchase": has_prior,
    }
    if age is not None:
        result["customer_age"] = age
    return result


class ModelComplianceEvidenceLoader:
    """读取每种证据的最新追加事件，仅 ISSUED 且未过期视为有效。"""

    def __init__(
        self,
        evidence_finder: Callable[[int, int, str], Any] = _default_evidence_finder,
        context_loader: Callable[[int], Mapping[str, Any]] = _default_double_record_context,
        now_provider: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._evidence_finder = evidence_finder
        self._context_loader = context_loader
        self._now_provider = now_provider

    def __call__(self, customer_id: int, product_id: int) -> dict[str, Any]:
        if not _positive_int(customer_id) or not _positive_int(product_id):
            raise ValueError("customer_id 和 product_id 必须为正整数")
        now = self._now_provider()
        result: dict[str, Any] = {}
        for control, evidence_type in EVIDENCE_CONTROLS.items():
            try:
                record = self._evidence_finder(customer_id, product_id, evidence_type)
                result[control] = bool(
                    record is not None
                    and _value(record, "evidence_type") == evidence_type
                    and _value(record, "action") == "ISSUED"
                    and _is_evidence_effective(_value(record, "valid_until"), now)
                )
            except Exception:
                # 单类证据读取异常不能污染其他结果，但该控件必须保持 fail-closed。
                result[control] = False
        try:
            context = self._context_loader(customer_id)
            age = context.get("customer_age")
            is_age_65_plus = context.get("is_age_65_plus")
            prior = context.get("has_prior_r3_plus_purchase")
            if isinstance(age, int) and not isinstance(age, bool) and age >= 0:
                result["customer_age"] = age
            if isinstance(prior, bool):
                result["has_prior_r3_plus_purchase"] = prior
            if isinstance(is_age_65_plus, bool):
                result["is_age_65_plus"] = is_age_65_plus
        except Exception:
            # 上下文缺失时不伪造默认值，规则层会保守要求双录。
            pass
        return result


def _default_holdings_loader(customer_id: int) -> Iterable[Any]:
    from app.WealthButler.Models.holdingsModel import HoldingsModel

    return HoldingsModel.find_by_customer_id(customer_id)


def _default_product_loader(product_id: int) -> Any:
    from app.WealthButler.Models.productModel import ProductModel

    return ProductModel.get_by_id(product_id)


class ModelHoldingSummaryLoader:
    """使用 Decimal 汇总客户有效持仓及指定风险等级持仓市值。"""

    def __init__(
        self,
        holdings_loader: Callable[[int], Iterable[Any]] = _default_holdings_loader,
        product_loader: Callable[[int], Any] = _default_product_loader,
    ) -> None:
        self._holdings_loader = holdings_loader
        self._product_loader = product_loader

    def __call__(self, customer_id: int, risk_level: str) -> dict[str, Decimal]:
        if not _positive_int(customer_id) or risk_level not in {"R1", "R2", "R3", "R4", "R5"}:
            raise ValueError("客户ID或风险等级不合法")
        holdings = self._holdings_loader(customer_id)
        if holdings is None:
            raise RuntimeError("持仓读取返回空结果")
        total = Decimal("0")
        risk_total = Decimal("0")
        for holding in holdings:
            if _value(holding, "deleted_at") is not None:
                continue
            value = _strict_decimal(_value(holding, "current_value"), "持仓市值")
            if value < 0:
                raise ValueError("持仓市值不能为负数")
            product_id = _value(holding, "product_id")
            if not _positive_int(product_id):
                raise ValueError("持仓产品ID不合法")
            product = self._product_loader(product_id)
            if product is None:
                # 产品缺失会导致风险档位无法归类，不能仅计入总额后继续放行。
                raise RuntimeError("持仓关联产品缺失")
            product_risk = _value(product, "risk_level")
            if product_risk not in {"R1", "R2", "R3", "R4", "R5"}:
                raise ValueError("持仓关联产品风险等级不合法")
            total += value
            if product_risk == risk_level:
                risk_total += value
        return {"total_value": total, "risk_level_value": risk_total}


def _default_payee_finder(customer_id: int, account_hmac: str, payee_name_hmac: str) -> Any:
    from app.WealthButler.Models.verifiedPayeeModel import VerifiedPayeeModel

    # 名称摘要必须由 Loader 自己 constant-time 复核，Model 只需按客户+账号定位。
    return VerifiedPayeeModel.find_by_fingerprint(customer_id, account_hmac)


class HMACVerifiedPayeeLoader:
    """以环境密钥生成精确指纹并核验已验证收款方。"""

    def __init__(
        self,
        payee_finder: Callable[[int, str, str], Any] = _default_payee_finder,
        secret_provider: Callable[[], Optional[str]] = lambda: os.environ.get(PAYEE_HMAC_KEY_ENV),
        now_provider: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._payee_finder = payee_finder
        self._secret_provider = secret_provider
        self._now_provider = now_provider

    def __call__(self, customer_id: int, payee: Mapping[str, Any]) -> bool:
        if not _positive_int(customer_id) or not isinstance(payee, Mapping):
            return False
        account = payee.get("account")
        name = payee.get("name")
        if not isinstance(account, str) or not account.strip() or not isinstance(name, str) or not name.strip():
            return False
        secret = self._secret_provider()
        if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
            # 与受控写入端采用同一强度门槛，且绝不回退到明文或固定默认密钥。
            return False
        try:
            account_value = normalize_account(account)
            name_value = normalize_name(name)
            account_hmac = fingerprint(secret, "account", customer_id, account_value)
            name_hmac = fingerprint(secret, "name", customer_id, name_value)
        except (TypeError, ValueError):
            return False
        try:
            record = self._payee_finder(customer_id, account_hmac, name_hmac)
        except Exception:
            return False
        return bool(
            record is not None
            and _value(record, "status") == "VERIFIED"
            and _is_unexpired(_value(record, "valid_until"), self._now_provider())
            and hmac.compare_digest(str(_value(record, "account_hmac", "")), account_hmac)
            and hmac.compare_digest(str(_value(record, "payee_name_hmac", "")), name_hmac)
        )
def _calculate_age(raw_birthday: Any, today: date) -> int:
    if isinstance(raw_birthday, datetime):
        birthday = raw_birthday.date()
    elif isinstance(raw_birthday, date):
        birthday = raw_birthday
    elif isinstance(raw_birthday, str):
        try:
            birthday = date.fromisoformat(raw_birthday)
        except ValueError as exc:
            raise ValueError("客户生日格式不合法") from exc
    else:
        raise ValueError("客户生日缺失")
    if birthday > today:
        raise ValueError("客户生日不能晚于当前日期")
    return today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))


def _is_age_65_plus_from_answers(answers: Any) -> Optional[bool]:
    if isinstance(answers, Mapping):
        selected = answers.get("Q1", answers.get(1, answers.get("1")))
        return _q1_selected_is_65_plus(selected)
    if not isinstance(answers, list):
        return None
    for answer in answers:
        if not isinstance(answer, Mapping):
            continue
        if str(answer.get("question_id", "")).upper() not in {"Q1", "1"}:
            continue
        label = answer.get("option_label", answer.get("label"))
        if isinstance(label, str):
            normalized = label.replace("周岁", "岁").replace(" ", "")
            if "65岁以上" in normalized or "65+" in normalized:
                return True
        return _q1_selected_is_65_plus(answer.get("option_index", answer.get("option_id")))
    return None


def _q1_selected_is_65_plus(selected: Any) -> Optional[bool]:
    if isinstance(selected, bool) or not isinstance(selected, int):
        return None
    if 0 <= selected <= 5:
        return selected == 5
    return None


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _strict_decimal(value: Any, field_name: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}不是有效 Decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field_name}不是有限 Decimal")
    return result


__all__ = [
    "EVIDENCE_CONTROLS",
    "HMACVerifiedPayeeLoader",
    "ModelComplianceEvidenceLoader",
    "ModelHoldingSummaryLoader",
    "PAYEE_HMAC_KEY_ENV",
]

# 配置项可直接使用 module:attribute；实例创建本身不连接数据库或读取密钥。
compliance_evidence_loader = ModelComplianceEvidenceLoader()
holding_summary_loader = ModelHoldingSummaryLoader()
payee_verifier = HMACVerifiedPayeeLoader()
