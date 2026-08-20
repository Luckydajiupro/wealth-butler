"""合规证据与收款方核验的强权限写入接口。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import logging
import os
import tempfile
from uuid import uuid4
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

from app.Base.Models.roleModel import Permission
from app.Base.RicUtils.httpUtils import HttpResponse
from app.Base.Service.authService import AuthService
from app.WealthButler.Api.operatorApiSupport import get_authenticated_employee
from app.WealthButler.Api.operatorApiSupport import get_authenticated_user
from app.WealthButler.Api.operatorApiSupport import ensure_employee_identity
from app.WealthButler.Api.operatorApiSupport import ensure_employee_user
from app.WealthButler.Service.complianceWriteService import (
    ComplianceEvidenceService,
    ControlledWriteError,
    VerifiedPayeeService,
)
from app.WealthButler.Service.operatorAccessService import OperatorAccessService


router = APIRouter(prefix="/api/compliance", tags=["合规受控写入"])
logger = logging.getLogger(__name__)


class _ControlledRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceIssueRequest(_ControlledRequest):
    customer_id: int = Field(..., gt=0)
    product_id: int = Field(..., gt=0)
    evidence_type: str = Field(..., min_length=1, max_length=64)
    artifact_uri: str = Field(..., min_length=10, max_length=1024)
    artifact_sha256: str = Field(..., min_length=64, max_length=64)
    completed_at: datetime
    valid_until: datetime
    verification_method: str = Field(..., min_length=1, max_length=64)


class SimulatedDoubleRecordRequest(_ControlledRequest):
    customer_id: int = Field(..., gt=0)
    product_id: int = Field(..., gt=0)
    workorder_id: int | None = Field(None, gt=0)


class RevokeRequest(_ControlledRequest):
    reason: str = Field(..., min_length=1, max_length=500)


class PayeeVerifyRequest(_ControlledRequest):
    customer_id: int = Field(..., gt=0)
    account: str = Field(..., min_length=4, max_length=128)
    payee_name: str = Field(..., min_length=1, max_length=128)
    verification_method: str = Field(..., min_length=1, max_length=64)
    valid_until: datetime


def get_compliance_writer(current_user: Any = Depends(get_authenticated_user)) -> Any:
    """受控写入要求员工身份及现有最高风控处置权限。"""
    ensure_employee_identity(current_user)
    allowed = AuthService.has_permission(
        current_user.id,
        Permission.RISK_OVERRIDE,
        getattr(current_user, "source_module", None),
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="需要风控处置权限（risk:override）")
    return current_user


def _response(call):
    try:
        return HttpResponse.ok(data=call())
    except ControlledWriteError as exc:
        status = {
            "NOT_FOUND": 404,
            "ALREADY_REVOKED": 409,
            "WRITE_FAILED": 503,
            "HMAC_KEY_UNAVAILABLE": 503,
        }.get(exc.code, 400)
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/evidence")
def issue_evidence(
    request: EvidenceIssueRequest,
    current_user: Any = Depends(get_compliance_writer),
):
    return _response(lambda: ComplianceEvidenceService().issue(
        customer_id=request.customer_id,
        product_id=request.product_id,
        evidence_type=request.evidence_type,
        artifact_uri=request.artifact_uri,
        artifact_sha256=request.artifact_sha256,
        completed_at=request.completed_at,
        valid_until=request.valid_until,
        verification_method=request.verification_method,
        verified_by=current_user.id,
    ))


@router.post("/test/double-record")
def issue_simulated_double_record(
    request: SimulatedDoubleRecordRequest,
    current_user: Any = Depends(get_authenticated_employee),
):
    """发起本地联调专用双录证据，仍经过正式证据表和 Loader。"""
    if os.getenv("WEALTH_BUTLER_SIMULATED_COMPLIANCE_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="测试双录流程未启用")
    ensure_employee_user(current_user)
    if not OperatorAccessService.can_access_customer(current_user.id, request.customer_id):
        raise HTTPException(status_code=403, detail="该客户不在当前客户经理的办理范围内")
    now = datetime.now(timezone.utc)
    trace_id = str(uuid4())
    payload = {
        "simulation": True,
        "evidence_type": "DOUBLE_RECORD_COMPLETED",
        "customer_id": request.customer_id,
        "product_id": request.product_id,
        "workorder_id": request.workorder_id,
        "operator_id": current_user.id,
        "completed_at": now.isoformat(),
    }
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    bucket = "fin-compliance-evidence"
    object_name = f"simulated-double-record/customer-{request.customer_id}/{trace_id}.json"
    try:
        from app.Base.Client.minioClient import default_minio_client
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
            handle.write(body)
            temp_path = handle.name
        try:
            stored_name = default_minio_client.upload_file(bucket, object_name, temp_path, "application/json")
        finally:
            os.unlink(temp_path)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="测试双录证据归档失败") from exc
    if not stored_name:
        raise HTTPException(status_code=503, detail="测试双录证据归档失败")
    result = ComplianceEvidenceService().issue(
        customer_id=request.customer_id,
        product_id=request.product_id,
        evidence_type="DOUBLE_RECORD_COMPLETED",
        artifact_uri=f"minio://{bucket}/{stored_name}",
        artifact_sha256=digest,
        completed_at=now,
        valid_until=now + timedelta(days=1),
        verification_method="SIMULATED_CUSTOMER_DOUBLE_RECORD",
        verified_by=current_user.id,
        metadata={**payload, "trace_id": trace_id},
    )
    try:
        from app.Base.Client.redisClient import redis_client
        notification = {
            "id": f"compliance-evidence:{trace_id}",
            "type": "compliance_evidence",
            "customer_id": request.customer_id,
            "workorder_id": request.workorder_id,
            "product_id": request.product_id,
            "evidence_type": "DOUBLE_RECORD_COMPLETED",
            "status": "已完成",
            "operator_id": current_user.id,
            "operator_name": getattr(current_user, "username", None),
            "message": "客户经理已完成测试双录并归档合规证据，可继续进行后续业务确认。",
            "created_at": now.isoformat(),
        }
        key = f"notifications:user:{request.customer_id}"
        redis_client.client.lpush(key, json.dumps(notification, ensure_ascii=False))
        redis_client.client.ltrim(key, 0, 99)
        redis_client.client.expire(key, 7 * 24 * 3600)
    except Exception:
        logger.exception("测试双录客户通知写入失败: customer_id=%s", request.customer_id)
    return _response(lambda: result)


@router.post("/evidence/{evidence_id}/revoke")
def revoke_evidence(
    request: RevokeRequest,
    evidence_id: str = Path(..., min_length=1, max_length=64),
    current_user: Any = Depends(get_compliance_writer),
):
    return _response(lambda: ComplianceEvidenceService().revoke(
        evidence_id=evidence_id,
        reason=request.reason,
        verified_by=current_user.id,
    ))


@router.post("/payees/verify")
def verify_payee(
    request: PayeeVerifyRequest,
    current_user: Any = Depends(get_compliance_writer),
):
    return _response(lambda: VerifiedPayeeService().verify(
        customer_id=request.customer_id,
        account=request.account,
        payee_name=request.payee_name,
        verification_method=request.verification_method,
        valid_until=request.valid_until,
        verified_by=current_user.id,
    ))


@router.post("/payees/{payee_id}/revoke")
def revoke_payee(
    payee_id: int = Path(..., gt=0),
    current_user: Any = Depends(get_compliance_writer),
):
    return _response(lambda: VerifiedPayeeService().revoke(
        payee_id=payee_id,
        verified_by=current_user.id,
    ))


def register_compliance_write_api(app: Any) -> None:
    app.include_router(router)


__all__ = ["register_compliance_write_api"]
