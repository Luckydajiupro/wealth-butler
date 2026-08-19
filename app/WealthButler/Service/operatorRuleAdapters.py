"""业务操作 Agent 的真实合规规则适配器。

本模块只负责确定性规则判断，不负责运行时装配。所有数据读取均可注入，默认
读取现有风评、画像和产品模型；读取失败、数据缺失或格式不合法一律拒绝，
避免金融写操作在信息不完整时误放行。
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Optional

from app.WealthButler.Service.operatorContracts import COMPLIANCE_THRESHOLDS, OperationCommand


RISK_LEVELS = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}
SUITABILITY_MATRIX = {
    "C1": {"allowed": {"R1", "R2"}, "disclosure": set()},
    "C2": {"allowed": {"R1", "R2", "R3"}, "disclosure": set()},
    "C3": {"allowed": {"R1", "R2", "R3"}, "disclosure": {"R4"}},
    "C4": {"allowed": {"R1", "R2", "R3", "R4"}, "disclosure": {"R5"}},
    "C5": {"allowed": set(RISK_LEVELS), "disclosure": set()},
}


def _default_assessment_loader(customer_id: int) -> Any:
    from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel

    return RiskAssessmentModel.find_latest_by_customer_id(customer_id)


def _default_profile_loader(customer_id: int) -> Any:
    from app.WealthButler.Models.customerProfileModel import CustomerProfileModel

    return CustomerProfileModel.find_by_customer_id(customer_id)


def _default_product_loader(product_id: int) -> Any:
    from app.WealthButler.Models.productModel import ProductModel

    return ProductModel.get_by_id(product_id)


def _value(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _decimal(value: Any) -> Optional[Decimal]:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _flags(profile: Any) -> Optional[list[Any]]:
    raw = _value(profile, "fm_flags")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None
    return raw if isinstance(raw, list) else None


def _flag_text(flag: Any) -> str:
    if isinstance(flag, str):
        return flag
    if isinstance(flag, dict):
        return " ".join(str(flag.get(key, "")) for key in ("code", "action", "reason"))
    return ""


class ModelSuitabilityGateway:
    """基于最新风评、画像熔断标记和产品等级执行适当性判断。"""

    def __init__(
        self,
        assessment_loader: Callable[[int], Any] = _default_assessment_loader,
        profile_loader: Callable[[int], Any] = _default_profile_loader,
        product_loader: Callable[[int], Any] = _default_product_loader,
        now_provider: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.assessment_loader = assessment_loader
        self.profile_loader = profile_loader
        self.product_loader = product_loader
        self.now_provider = now_provider

    def check(self, customer_id: int, product_id: int) -> Dict[str, Any]:
        if (
            not isinstance(customer_id, int)
            or isinstance(customer_id, bool)
            or customer_id <= 0
            or not isinstance(product_id, int)
            or isinstance(product_id, bool)
            or product_id <= 0
        ):
            return self._reject("客户ID或产品ID缺失或不合法")
        try:
            assessment = self.assessment_loader(customer_id)
            profile = self.profile_loader(customer_id)
            product = self.product_loader(product_id)
        except Exception:
            return self._reject("适当性数据读取失败，暂不能办理申购")
        if assessment is None:
            return self._reject("客户缺少风险评估，须完成风评后再申购")
        if profile is None:
            return self._reject("客户画像缺失，无法核验硬性熔断规则")
        if product is None:
            return self._reject("产品不存在")

        valid_until = _value(assessment, "valid_until")
        if not isinstance(valid_until, datetime):
            return self._reject("风险评估有效期缺失或格式不合法")
        now = self.now_provider()
        if valid_until.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=valid_until.tzinfo)
        elif valid_until.tzinfo is None and now.tzinfo is not None:
            valid_until = valid_until.replace(tzinfo=now.tzinfo)
        if valid_until <= now:
            return self._reject("风险评估已过期，已冻结新购权限", fm_hits=[{"code": "FM-03", "level": "block"}])

        customer_level = _value(assessment, "risk_level")
        product_level = _value(product, "risk_level")
        if customer_level not in SUITABILITY_MATRIX or product_level not in RISK_LEVELS:
            return self._reject("客户或产品风险等级缺失或不合法")

        raw_flags = _flags(profile)
        if raw_flags is None:
            return self._reject("客户画像缺少熔断检查结果，暂不能办理申购")
        fm_hits, controls, block_reason = self._evaluate_flags(raw_flags, product_level)
        if block_reason:
            return self._reject(block_reason, fm_hits=fm_hits, required_controls=controls)

        professional = _value(assessment, "is_professional_investor") is True
        matrix = SUITABILITY_MATRIX[customer_level]
        exemption_used = False
        if product_level in matrix["allowed"]:
            action = "allow"
        elif product_level in matrix["disclosure"] or professional:
            action = "disclosure"
            exemption_used = professional and product_level not in matrix["disclosure"]
            controls.append("risk_disclosure_signed")
            if professional:
                controls.append("risk_notification_acknowledged")
        else:
            return self._reject(
                f"{customer_level}客户不得购买{product_level}产品",
                fm_hits=fm_hits,
                required_controls=controls,
            )

        controls = list(dict.fromkeys(controls))
        return {
            "passed": True,
            "action": action,
            "reason": "适当性匹配通过" if action == "allow" else "须完成风险揭示后方可申购",
            "customer_risk_level": customer_level,
            "product_risk_level": product_level,
            "professional_investor": professional,
            "exemption_used": exemption_used,
            "requires_disclosure": action == "disclosure",
            "manual_review_required": False,
            "required_controls": controls,
            "fm_hits": fm_hits,
        }

    @staticmethod
    def _evaluate_flags(flags: list[Any], product_level: str) -> tuple[list[dict], list[str], Optional[str]]:
        fm_hits: list[dict] = []
        controls: list[str] = []
        rank = RISK_LEVELS[product_level]
        for flag in flags:
            text = _flag_text(flag)
            if not text:
                return fm_hits, controls, "客户画像包含无法识别的熔断标记"
            code = text[:5] if text.startswith("FM-0") else "UNKNOWN"
            hit = {"code": code, "level": "control", "reason": text}
            if "FM-03" in text:
                hit["level"] = "block"
                fm_hits.append(hit)
                return fm_hits, controls, "风评过期，已冻结新购权限"
            if "FM-04" in text or ("FM-05" in text and any(word in text for word in ("冻结", "盗用"))):
                hit["level"] = "block"
                fm_hits.append(hit)
                return fm_hits, controls, "客户命中不可绕过的交易冻结规则"
            if any(word in text for word in ("禁止交易名单", "虚假信息", "法律禁止")):
                hit["level"] = "block"
                fm_hits.append(hit)
                return fm_hits, controls, "客户命中适当性禁止交易规则"
            if "FM-01" in text:
                if "禁止开户" in text or ("仅允许R1-R2" in text and rank >= 3):
                    hit["level"] = "block"
                    fm_hits.append(hit)
                    return fm_hits, controls, "年龄熔断规则不允许购买该风险等级产品"
                if "R4+需监护人" in text and rank >= 4:
                    controls.append("guardian_consent_signed")
                if "R3+需网点签署" in text and rank >= 3:
                    controls.append("in_person_risk_confirmation_signed")
            if "FM-02" in text:
                if "仅允许R1-R2" in text and rank >= 3:
                    hit["level"] = "block"
                    fm_hits.append(hit)
                    return fm_hits, controls, "收入与资产熔断规则不允许购买该产品"
                if "仅允许R1-R3" in text:
                    if rank >= 4:
                        hit["level"] = "block"
                        fm_hits.append(hit)
                        return fm_hits, controls, "收入与资产熔断规则仅允许购买R1-R3产品"
                    if rank == 3:
                        hit.update({
                            "level": "block",
                            "constraints": {"max_r3_position_pct": "0.30"},
                        })
            fm_hits.append(hit)
        return fm_hits, controls, None

    @staticmethod
    def _reject(
        reason: str,
        fm_hits: Optional[list[dict]] = None,
        required_controls: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        return {
            "passed": False,
            "action": "forbidden",
            "reason": reason,
            "requires_disclosure": False,
            "manual_review_required": False,
            "required_controls": required_controls or [],
            "fm_hits": fm_hits or [],
        }


class ModelPurchaseComplianceGateway:
    """核验风险揭示、双录及披露档位持仓上限。"""

    POSITION_LIMITS = {("C3", "R4"): Decimal("0.20"), ("C4", "R5"): Decimal("0.10")}

    def __init__(
        self,
        suitability_gateway: Optional[ModelSuitabilityGateway] = None,
        evidence_loader: Callable[[int, int], Any] = lambda customer_id, product_id: None,
        holding_summary_loader: Callable[[int, str], Any] = lambda customer_id, risk_level: None,
    ) -> None:
        self.suitability_gateway = suitability_gateway or ModelSuitabilityGateway()
        self.evidence_loader = evidence_loader
        self.holding_summary_loader = holding_summary_loader

    def validate_purchase(
        self,
        customer_id: int,
        product: Dict[str, Any],
        command: OperationCommand,
    ) -> Optional[str]:
        product_id = _value(product, "id", _value(product, "product_id"))
        if not isinstance(product_id, int) or isinstance(product_id, bool) or product_id <= 0:
            return "产品ID缺失或不合法，无法完成合规校验"
        if _value(product, "sale_prohibited") is True:
            return "该产品依法禁止销售"

        decision = self.suitability_gateway.check(customer_id, product_id)
        if not decision.get("passed", False):
            return decision.get("reason", "适当性校验未通过")

        try:
            evidence = self.evidence_loader(customer_id, product_id)
        except Exception:
            return "合规留痕读取失败，暂不能办理申购"
        controls = list(decision.get("required_controls") or [])
        amount = _decimal(command.params.get("amount"))
        if amount is None or amount <= 0:
            return "申购金额缺失或不合法"
        if amount > COMPLIANCE_THRESHOLDS["suitability_double_record_amount"]:
            controls.append("double_record_completed")

        product_type = str(_value(product, "product_type", ""))
        product_level = _value(product, "risk_level")
        # 复杂/私募和豁免超权限购买是无需额外历史数据即可确定的双录触发条件。
        if (
            product_type in {"私募基金", "信托", "结构性存款", "资管计划"}
            or _value(product, "is_complex") is True
            or decision.get("exemption_used")
        ):
            controls.append("double_record_completed")
        evidence_context = evidence if isinstance(evidence, dict) else {}
        if product_level in {"R3", "R4", "R5"} and evidence_context.get("has_prior_r3_plus_purchase") is not True:
            controls.append("double_record_completed")
        age_flag = evidence_context.get("is_age_65_plus")
        if not isinstance(age_flag, bool):
            age = evidence_context.get("customer_age")
            age_flag = age >= 65 if isinstance(age, int) and not isinstance(age, bool) else None
        if product_level != "R1" and age_flag is not False:
            controls.append("double_record_completed")

        if controls:
            if not isinstance(evidence, dict):
                return "缺少风险揭示或双录等合规留痕"
            missing = [control for control in dict.fromkeys(controls) if evidence.get(control) is not True]
            if missing:
                return "合规控件尚未完成：" + "、".join(missing)

        assessment_level = decision.get("customer_risk_level")
        limit = None if decision.get("professional_investor") else self.POSITION_LIMITS.get(
            (assessment_level, product_level)
        )
        if limit is not None:
            try:
                summary = self.holding_summary_loader(customer_id, product_level)
            except Exception:
                return "持仓数据读取失败，无法核验适当性仓位上限"
            if not isinstance(summary, dict):
                return "缺少持仓数据，无法核验适当性仓位上限"
            total = _decimal(summary.get("total_value"))
            risk_value = _decimal(summary.get("risk_level_value"))
            if total is None or risk_value is None or total < 0 or risk_value < 0:
                return "持仓数据缺失或不合法，无法核验适当性仓位上限"
            projected_total = total + amount
            if projected_total <= 0 or (risk_value + amount) / projected_total > limit:
                return f"申购后{product_level}持仓将超过总资产{int(limit * 100)}%上限"
        return None


class ModelOperationRiskGateway:
    """赎回与转账前读取画像熔断状态，按交易类型执行边界规则。"""

    def __init__(
        self,
        profile_loader: Callable[[int], Any] = _default_profile_loader,
        payee_verifier: Callable[[int, Dict[str, Any]], Optional[bool]] = (
            lambda customer_id, payee: bool(payee.get("account") and payee.get("name"))
        ),
    ) -> None:
        self.profile_loader = profile_loader
        self.payee_verifier = payee_verifier

    def validate_redeem(self, customer_id: int, product_id: int, shares: Any) -> Optional[str]:
        share_value = _decimal(shares)
        if (
            not isinstance(customer_id, int)
            or isinstance(customer_id, bool)
            or customer_id <= 0
            or not isinstance(product_id, int)
            or isinstance(product_id, bool)
            or product_id <= 0
            or share_value is None
            or share_value <= 0
        ):
            return "赎回参数缺失或不合法"
        flags, error = self._load_flags(customer_id)
        if error:
            return error
        for flag in flags:
            text = _flag_text(flag)
            # FM-03只冻结新购；到期未重评仍允许赎回存量。
            if "FM-04" in text or ("FM-05" in text and any(word in text for word in ("冻结", "盗用"))):
                return "客户命中全部交易冻结规则，暂不能赎回"
            if "FM-05" in text and "人工回访" in text:
                return "连续大额赎回须完成人工回访确认"
        return None

    def validate_transfer(self, customer_id: int, amount: Any, payee: Dict[str, Any]) -> Optional[str]:
        amount_value = _decimal(amount)
        if (
            not isinstance(customer_id, int)
            or isinstance(customer_id, bool)
            or customer_id <= 0
            or amount_value is None
            or amount_value <= 0
        ):
            return "转账金额缺失或不合法"
        if not isinstance(payee, dict) or not payee.get("account") or not payee.get("name"):
            return "收款方信息缺失或不合法"
        flags, error = self._load_flags(customer_id)
        if error:
            return error
        for flag in flags:
            text = _flag_text(flag)
            if "FM-03" in text:
                return "风评过期后仅允许赎回存量，暂不能转账"
            if "FM-04" in text or ("FM-05" in text and any(word in text for word in ("冻结", "盗用"))):
                return "客户命中交易冻结规则，暂不能转账"
        try:
            verified = self.payee_verifier(customer_id, payee)
        except Exception:
            return "收款方核验失败，暂不能转账"
        if verified is not True:
            return "收款方未通过核验，暂不能转账"
        return None

    def _load_flags(self, customer_id: int) -> tuple[list[Any], Optional[str]]:
        try:
            profile = self.profile_loader(customer_id)
        except Exception:
            return [], "客户风险画像读取失败，暂不能执行交易"
        if profile is None:
            return [], "客户风险画像缺失，暂不能执行交易"
        flags = _flags(profile)
        if flags is None:
            return [], "客户画像缺少熔断检查结果，暂不能执行交易"
        if any(not _flag_text(flag) for flag in flags):
            return [], "客户画像包含无法识别的熔断标记"
        return flags, None
