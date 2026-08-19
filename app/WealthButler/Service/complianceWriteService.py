"""合规证据与受信收款方的受控写入业务逻辑。"""

from __future__ import annotations

import hmac
import os
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from uuid import uuid4

from app.WealthButler.Service.operatorComplianceLoaders import EVIDENCE_CONTROLS
from app.WealthButler.Utils.payeeFingerprint import (
    fingerprint,
    normalize_account,
    normalize_name,
)


_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_MINIO_URI_PATTERN = re.compile(r"^minio://[a-z0-9][a-z0-9.-]{1,62}/[^\s?#]+$")
_ALLOWED_EVIDENCE_TYPES = frozenset(EVIDENCE_CONTROLS.values())


class ControlledWriteError(RuntimeError):
    """携带稳定错误码，供 API 层映射 HTTP 状态。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _write_succeeded(result: Any) -> bool:
    return result not in (None, False, -1)


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else value


def _db_datetime(value: datetime) -> datetime:
    """统一为 UTC naive DATETIME，避免带/不带时区输入比较失败。"""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ComplianceEvidenceService:
    """以追加事件维护合规证据，不覆盖既有签发记录。"""

    def __init__(self, model_class: Any = None):
        if model_class is None:
            # Model 由数据层任务提供，延迟导入避免模块导入时触发建表或连接。
            from app.WealthButler.Models.complianceEvidenceModel import ComplianceEvidenceModel

            model_class = ComplianceEvidenceModel
        self.model_class = model_class

    def issue(
        self,
        *,
        customer_id: int,
        product_id: int,
        evidence_type: str,
        artifact_uri: str,
        artifact_sha256: str,
        completed_at: datetime,
        valid_until: datetime,
        verification_method: str,
        verified_by: int,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        completed_at = _db_datetime(completed_at)
        valid_until = _db_datetime(valid_until)
        evidence_type = evidence_type.strip()
        verification_method = verification_method.strip()
        if customer_id <= 0 or product_id <= 0 or verified_by <= 0:
            raise ControlledWriteError("INVALID_CONTEXT", "客户、产品和核验员工标识必须有效")
        if not evidence_type or not verification_method:
            raise ControlledWriteError("INVALID_CONTEXT", "证据类型和核验方式不能为空")
        if evidence_type not in _ALLOWED_EVIDENCE_TYPES:
            raise ControlledWriteError("UNSUPPORTED_EVIDENCE_TYPE", "不支持的合规证据类型")
        if not _MINIO_URI_PATTERN.fullmatch(artifact_uri):
            raise ControlledWriteError("INVALID_ARTIFACT", "证据必须使用有效的 MinIO 对象引用")
        if not _SHA256_PATTERN.fullmatch(artifact_sha256):
            raise ControlledWriteError("INVALID_DIGEST", "artifact_sha256 必须为完整 SHA256")
        if valid_until <= completed_at:
            raise ControlledWriteError("INVALID_VALIDITY", "证据有效期必须晚于完成时间")
        evidence_id = str(uuid4())
        event = self.model_class(
            event_id=str(uuid4()),
            evidence_id=evidence_id,
            action="ISSUED",
            customer_id=customer_id,
            product_id=product_id,
            evidence_type=evidence_type,
            artifact_uri=artifact_uri,
            artifact_sha256=artifact_sha256.lower(),
            completed_at=completed_at,
            valid_until=valid_until,
            verified_by=verified_by,
            verification_method=verification_method,
            trace_id=str(uuid4()),
            metadata=dict(metadata or {}),
        )
        if not _write_succeeded(event.save()):
            raise ControlledWriteError("WRITE_FAILED", "合规证据签发失败")
        return self._public_event(event)

    def revoke(self, *, evidence_id: str, reason: str, verified_by: int) -> dict[str, Any]:
        reason = reason.strip()
        if not evidence_id.strip() or not reason or verified_by <= 0:
            raise ControlledWriteError("INVALID_CONTEXT", "证据标识、撤销原因和核验员工必须有效")
        current = self.model_class.find_latest_by_evidence_id(evidence_id)
        if current is None:
            raise ControlledWriteError("NOT_FOUND", "合规证据不存在")
        if getattr(current, "action", None) == "REVOKED":
            raise ControlledWriteError("ALREADY_REVOKED", "合规证据已撤销")
        # 撤销是新事件而不是 UPDATE，保留签发人、原始对象摘要和完整审计链。
        event = self.model_class(
            event_id=str(uuid4()),
            evidence_id=current.evidence_id,
            action="REVOKED",
            customer_id=current.customer_id,
            product_id=current.product_id,
            evidence_type=current.evidence_type,
            artifact_uri=current.artifact_uri,
            artifact_sha256=current.artifact_sha256,
            # 撤销时刻由服务端生成，不能复制签发时间或接受客户端伪造。
            completed_at=_utcnow(),
            valid_until=current.valid_until,
            verified_by=verified_by,
            verification_method="MANUAL_REVOCATION",
            trace_id=str(uuid4()),
            metadata={"revocation_reason": reason},
        )
        if not _write_succeeded(event.save()):
            raise ControlledWriteError("WRITE_FAILED", "合规证据撤销失败")
        return self._public_event(event)

    @staticmethod
    def _public_event(event: Any) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "evidence_id": event.evidence_id,
            "action": event.action,
            "customer_id": event.customer_id,
            "product_id": event.product_id,
            "evidence_type": event.evidence_type,
            "artifact_uri": event.artifact_uri,
            "artifact_sha256": event.artifact_sha256,
            "completed_at": _iso(event.completed_at),
            "valid_until": _iso(event.valid_until),
            "verified_by": event.verified_by,
            "verification_method": event.verification_method,
            "trace_id": event.trace_id,
        }


class VerifiedPayeeService:
    """用不可逆指纹维护收款方核验状态。"""

    def __init__(
        self,
        model_class: Any = None,
        *,
        hmac_key: Optional[str] = None,
        environ: Optional[Mapping[str, str]] = None,
    ):
        env = os.environ if environ is None else environ
        secret = hmac_key if hmac_key is not None else env.get("WEALTH_BUTLER_PAYEE_HMAC_KEY")
        if not secret or len(secret.encode("utf-8")) < 32:
            raise ControlledWriteError(
                "HMAC_KEY_UNAVAILABLE",
                "收款方 HMAC 密钥未配置或强度不足",
            )
        if model_class is None:
            # 延迟导入确保无请求时不初始化数据层。
            from app.WealthButler.Models.verifiedPayeeModel import VerifiedPayeeModel

            model_class = VerifiedPayeeModel
        self.model_class = model_class
        self._secret = secret

    def verify(
        self,
        *,
        customer_id: int,
        account: str,
        payee_name: str,
        verification_method: str,
        valid_until: datetime,
        verified_by: int,
    ) -> dict[str, Any]:
        account_value = normalize_account(account)
        name_value = normalize_name(payee_name)
        verification_method = verification_method.strip()
        valid_until = _db_datetime(valid_until)
        if customer_id <= 0 or verified_by <= 0 or not verification_method:
            raise ControlledWriteError("INVALID_CONTEXT", "客户、核验员工和核验方式必须有效")
        if not re.fullmatch(r"[A-Za-z0-9]{4,128}", account_value) or not name_value:
            raise ControlledWriteError("INVALID_PAYEE", "收款账号或收款方名称不合法")
        now = _utcnow()
        if valid_until <= now:
            raise ControlledWriteError("INVALID_VALIDITY", "收款方核验有效期必须晚于当前时间")
        account_hmac = fingerprint(self._secret, "account", customer_id, account_value)
        name_hmac = fingerprint(self._secret, "name", customer_id, name_value)
        existing = self.model_class.find_by_fingerprint(customer_id, account_hmac)
        if existing is not None and not hmac.compare_digest(
            str(getattr(existing, "payee_name_hmac", "")),
            name_hmac,
        ):
            # 同一账号绑定的姓名指纹不一致时拒绝覆盖，避免只凭账号放行转账。
            raise ControlledWriteError("PAYEE_NAME_MISMATCH", "收款方名称与既有核验记录不一致")
        values = {
            "account_last4": account_value[-4:],
            "verification_method": verification_method,
            "status": "VERIFIED",
            "verified_by": verified_by,
            "verified_at": now,
            "valid_until": valid_until,
            "trace_id": str(uuid4()),
        }
        if existing is None:
            payee = self.model_class(
                customer_id=customer_id,
                account_hmac=account_hmac,
                payee_name_hmac=name_hmac,
                **values,
            )
            result = payee.save()
        else:
            payee = existing
            result = payee.update(**values)
            for key, value in values.items():
                setattr(payee, key, value)
        if not _write_succeeded(result):
            raise ControlledWriteError("WRITE_FAILED", "收款方核验写入失败")
        return self._public_payee(payee)

    def revoke(self, *, payee_id: int, verified_by: int) -> dict[str, Any]:
        if payee_id <= 0 or verified_by <= 0:
            raise ControlledWriteError("INVALID_CONTEXT", "收款方记录和核验员工标识必须有效")
        payee = self.model_class.get_by_id(payee_id)
        if payee is None:
            raise ControlledWriteError("NOT_FOUND", "收款方核验记录不存在")
        if getattr(payee, "status", None) == "REVOKED":
            raise ControlledWriteError("ALREADY_REVOKED", "收款方核验已撤销")
        values = {
            "status": "REVOKED",
            "verified_by": verified_by,
            "trace_id": str(uuid4()),
        }
        result = payee.update(**values)
        for key, value in values.items():
            setattr(payee, key, value)
        if not _write_succeeded(result):
            raise ControlledWriteError("WRITE_FAILED", "收款方核验撤销失败")
        return self._public_payee(payee)

    @staticmethod
    def _public_payee(payee: Any) -> dict[str, Any]:
        # 返回值刻意不包含原账号、姓名或 HMAC；调用方只能看到末四位。
        return {
            "id": getattr(payee, "id", None),
            "customer_id": payee.customer_id,
            "account_last4": payee.account_last4,
            "verification_method": payee.verification_method,
            "status": payee.status,
            "verified_by": payee.verified_by,
            "verified_at": _iso(payee.verified_at),
            "valid_until": _iso(payee.valid_until),
            "trace_id": payee.trace_id,
        }


__all__ = [
    "ComplianceEvidenceService",
    "ControlledWriteError",
    "VerifiedPayeeService",
]
