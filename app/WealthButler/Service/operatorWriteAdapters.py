"""业务操作 Agent 的真实非交易写入 Adapter。

交易写入不属于本模块。所有依赖均可注入，默认实现延迟加载现有 Model、
Service 与 EventBus；任何持久化失败都会抛出异常或返回明确的失败信息。
"""

from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import logging
import re
from typing import Any, Callable, Dict, Optional
from uuid import uuid4


logger = logging.getLogger(__name__)


def _require_saved_id(value: Any, entity: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeError(f"{entity}写入失败")
    return value


def _model_id(model: Any, entity: str) -> int:
    return _require_saved_id(getattr(model, "id", None), entity)


def _order_result(order: Any) -> Dict[str, Any]:
    return {
        "id": _model_id(order, "工单"),
        "order_no": getattr(order, "order_no", None),
        "customer_id": getattr(order, "customer_id", None),
        "order_type": getattr(order, "order_type", None),
        "status": getattr(order, "status", None),
        "handler_id": getattr(order, "handler_id", None),
        "handler_name": getattr(order, "handler_name", None),
        "business_subtype": getattr(order, "business_subtype", None),
        "related_entity_type": getattr(order, "related_entity_type", None),
        "related_entity_id": getattr(order, "related_entity_id", None),
    }


class ModelWorkOrderGateway:
    """使用 WorkOrderModel 创建工单并执行受控状态流转。"""

    _ALLOWED_TRANSITIONS = {
        "待处理": {"处理中", "已驳回"},
        "处理中": {"待审核", "已完成", "已驳回"},
        "待审核": {"处理中", "已完成", "已驳回"},
        "已完成": set(),
        "已驳回": set(),
    }
    _TYPE_MAP = {
        "风控处置": "风控预警",
        "投诉建议": "投诉",
        "其他": "咨询",
    }

    def __init__(
        self,
        work_order_model: Any = None,
        now: Callable[[], datetime] = datetime.now,
        transition_writer: Optional[Callable[[Any, str, Dict[str, Any], Optional[int]], bool]] = None,
    ):
        if work_order_model is None:
            from app.WealthButler.Models.workOrderModel import WorkOrderModel

            work_order_model = WorkOrderModel
        self.work_order_model = work_order_model
        self.now = now
        self.transition_writer = transition_writer or self._atomic_transition_write

    def create_booking(self, customer_id: int, summary: str, product_id: int) -> Dict[str, Any]:
        return self._create(
            customer_id,
            "业务申请",
            summary,
            related_entity_type="product",
            related_entity_id=product_id,
        )

    def create_work_order(self, customer_id: int, order_type: str, summary: str) -> Dict[str, Any]:
        return self._create(customer_id, self._TYPE_MAP.get(order_type, order_type), summary)

    def _create(
        self,
        customer_id: int,
        order_type: str,
        summary: str,
        related_entity_type: Optional[str] = None,
        related_entity_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        now = self.now()
        order = self.work_order_model(
            order_no=f"OP-{now:%Y%m%d%H%M%S}-{uuid4().hex[:8].upper()}",
            order_type=order_type,
            source="系统生成",
            customer_id=customer_id,
            title=(summary.strip() if isinstance(summary, str) and summary.strip() else order_type)[:200],
            description=summary or None,
            intent_summary=summary or None,
            status="待处理",
            priority="中",
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            handle_records={"records": []},
        )
        saved_id = _require_saved_id(order.save(), "工单")
        if getattr(order, "id", None) is None:
            order.id = saved_id
        return _order_result(order)

    def transition(self, work_order_id: int, status: str, note: str) -> Dict[str, Any]:
        return self._transition(work_order_id, status, note, None, require_handler=False)

    def claim(self, work_order_id: int, handler_id: int) -> Dict[str, Any]:
        return self._transition(work_order_id, "处理中", "领取工单", handler_id, require_handler=False)

    def submit_for_review(self, work_order_id: int, handler_id: int, note: str) -> Dict[str, Any]:
        return self._transition(work_order_id, "待审核", note, handler_id, require_handler=True)

    def complete(
        self,
        work_order_id: int,
        handler_id: int,
        related_entity_type: str,
        related_entity_id: int,
        handle_note: str,
    ) -> Dict[str, Any]:
        return self._transition(
            work_order_id,
            "已完成",
            handle_note,
            handler_id,
            require_handler=True,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            completed_at=self.now(),
        )

    def reject(self, work_order_id: int, handler_id: int, handle_note: str) -> Dict[str, Any]:
        order = self._get_order(work_order_id)
        require_handler = getattr(order, "status", None) != "待处理"
        return self._transition(work_order_id, "已驳回", handle_note, handler_id, require_handler=require_handler, order=order)

    def complete_transaction_for_customer(
        self, customer_id: int, handler_id: int, intent: str, transaction_id: int
    ) -> Optional[Dict[str, Any]]:
        """成交后闭环当前员工名下匹配的客户转介工单。"""
        subtype = {"purchase": "申购", "redeem": "赎回", "transfer": "转账"}.get(intent)
        if not subtype:
            return None
        orders = self.work_order_model.find_by_customer_id(customer_id, limit=100)
        for order in orders:
            if getattr(order, "status", None) != "处理中":
                continue
            current_handler = getattr(order, "handler_id", None) or getattr(order, "handled_by", None)
            if current_handler != handler_id:
                continue
            summary = " ".join(str(getattr(order, field, "") or "") for field in ("title", "description", "intent_summary"))
            if subtype not in summary:
                continue
            if intent == "purchase" and "追加申购" in summary:
                # 追加申购同样属于 purchase，避免将普通申购工单误闭环。
                pass
            return self.complete(
                int(order.id), handler_id, "transaction", int(transaction_id),
                f"交易已成交，系统自动完成工单（交易ID {int(transaction_id)}）",
            )
        return None

    def _get_order(self, work_order_id: int) -> Any:
        order = self.work_order_model.get_by_id(work_order_id)
        if not order or getattr(order, "deleted_at", None) is not None:
            raise ValueError("工单不存在")
        return order

    def _transition(
        self,
        work_order_id: int,
        target: str,
        note: str,
        handler_id: Optional[int],
        require_handler: bool,
        order: Any = None,
        **extra_fields: Any,
    ) -> Dict[str, Any]:
        order = order or self._get_order(work_order_id)
        current = getattr(order, "status", None)
        if target not in self._ALLOWED_TRANSITIONS.get(current, set()):
            raise ValueError(f"工单不能从{current}流转到{target}")
        current_handler = getattr(order, "handler_id", None) or getattr(order, "handled_by", None)
        if require_handler and current_handler != handler_id:
            raise ValueError("当前员工不是工单处理人")

        raw_records = getattr(order, "handle_records", None)
        records = list(raw_records.get("records", [])) if isinstance(raw_records, dict) else []
        records.append({
            "status": target,
            "note": note,
            "handler_id": handler_id,
            "handled_at": self.now().isoformat(),
        })
        fields = {"status": target, "handle_records": {"records": records}, **extra_fields}
        if handler_id is not None:
            fields.update({"handler_id": handler_id, "handled_by": handler_id})
        if target == "处理中" and getattr(order, "handled_at", None) is None:
            fields["handled_at"] = self.now()
        expected_handler = handler_id if require_handler else None
        if not self.transition_writer(order, current, fields, expected_handler):
            raise ValueError("工单状态已变化或处理人不匹配，请刷新后重试")
        order.__dict__.update(fields)
        return _order_result(order)

    def _atomic_transition_write(
        self,
        order: Any,
        expected_status: str,
        fields: Dict[str, Any],
        expected_handler: Optional[int],
    ) -> bool:
        """以数据库条件更新实现跨进程 CAS，防止同一工单被并发领取。"""
        self.work_order_model._ensure_table_exists()
        db = self.work_order_model.get_db_connection()
        if db is None:
            raise RuntimeError("工单数据库连接不可用")
        allowed_fields = {
            "status", "handle_records", "handler_id", "handled_by", "handled_at",
            "completed_at", "related_entity_type", "related_entity_id",
        }
        if not fields or set(fields) - allowed_fields:
            raise ValueError("工单状态更新包含未授权字段")
        serialized = []
        for value in fields.values():
            serialized.append(
                json.dumps(value, ensure_ascii=False, default=str)
                if isinstance(value, (dict, list)) else value
            )
        assignments = ",".join(f"`{field}`=%s" for field in fields)
        sql = (
            f"UPDATE `{self.work_order_model.table_alias}` SET {assignments} "
            "WHERE `id`=%s AND `status`=%s AND `deleted_at` IS NULL"
        )
        params = serialized + [getattr(order, "id", None), expected_status]
        if expected_handler is not None:
            sql += " AND COALESCE(`handler_id`, `handled_by`)=%s"
            params.append(expected_handler)
        affected = db.execute(sql, tuple(params))
        if affected is None or affected < 0:
            raise RuntimeError("工单状态更新执行失败")
        return affected == 1


class ServiceRiskAssessmentGateway:
    """使用 RiskAssessService 计算并保存 16 题风评。"""

    def __init__(
        self,
        assessment_service: Any = None,
        assessment_model: Any = None,
        profile_service: Any = None,
        now: Callable[[], datetime] = datetime.now,
    ):
        if assessment_service is None:
            from app.WealthButler.Service.riskAssessService import RiskAssessService

            assessment_service = RiskAssessService
        if assessment_model is None:
            from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel

            assessment_model = RiskAssessmentModel
        if profile_service is None:
            from app.WealthButler.Service.customerProfileService import CustomerProfileService

            profile_service = CustomerProfileService
        self.assessment_service = assessment_service
        self.assessment_model = assessment_model
        self.profile_service = profile_service
        self.now = now

    def submit_assessment(self, customer_id: int, answers: list, is_professional: bool = False) -> Dict[str, Any]:
        normalized = self._normalize_answers(answers)
        total_score, risk_level = self.assessment_service.calculate_risk_level(normalized)
        assessment_time = self.now()
        assessment = self.assessment_model(
            customer_id=customer_id,
            total_score=total_score,
            risk_level=risk_level,
            answers=answers,
            is_professional_investor=is_professional,
            assessment_time=assessment_time,
            valid_until=assessment_time + timedelta(days=365),
        )
        assessment_id = _require_saved_id(assessment.save(), "风险评估")
        if getattr(assessment, "id", None) is None:
            assessment.id = assessment_id

        recalc_profile = None
        recalc_error = None
        try:
            profile = self.profile_service.get_comprehensive_profile(customer_id, updated_reason="风评重做")
            if profile is not None:
                recalc_profile = {
                    "profile_id": getattr(profile, "id", None),
                    "risk_level": getattr(profile, "risk_level", None),
                }
            else:
                recalc_error = "客户画像重算未返回结果"
        except Exception as exc:
            recalc_error = str(exc)
        return {
            "assessment_id": assessment_id,
            "total_score": total_score if isinstance(total_score, Decimal) else Decimal(str(total_score)),
            "risk_level": risk_level,
            "recalc_profile": recalc_profile,
            "profile_recalc_error": recalc_error,
        }

    @staticmethod
    def _normalize_answers(answers: list) -> Dict[int, int]:
        if not isinstance(answers, list) or len(answers) != 16:
            raise ValueError("风险评估必须提交 Q1-Q16 共16题")
        normalized: Dict[int, int] = {}
        for answer in answers:
            if not isinstance(answer, dict):
                raise ValueError("风险评估答案格式不合法")
            match = re.fullmatch(r"Q([1-9]|1[0-6])", str(answer.get("question_id", "")))
            if not match:
                raise ValueError("风险评估 question_id 必须为 Q1-Q16")
            question_id = int(match.group(1))
            if question_id in normalized:
                raise ValueError(f"风险评估答案重复: Q{question_id}")
            if question_id == 7:
                option_ids = answer.get("option_ids")
                if not isinstance(option_ids, list) or not option_ids:
                    raise ValueError("Q7 必须提供非空 option_ids")
                selected = max(option_ids)
            else:
                selected = answer.get("option_index", answer.get("option_id"))
            if isinstance(selected, bool) or not isinstance(selected, int) or selected < 0:
                raise ValueError(f"Q{question_id} 选项必须为非负整数索引")
            normalized[question_id] = selected
        if set(normalized) != set(range(1, 17)):
            raise ValueError("风险评估必须完整提交 Q1-Q16")
        return normalized


class AuthCustomerInfoGateway:
    """在 CUSTOMER 身份边界内复用 AuthService 更新联系方式。"""

    def __init__(self, auth_service: Any = None, user_model: Any = None):
        if auth_service is None:
            from app.Base.Service.authService import AuthService

            auth_service = AuthService
        if user_model is None:
            from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel

            user_model = BaseUserExtModel
        self.auth_service = auth_service
        self.user_model = user_model

    def update_contact(self, customer_id: int, phone: Optional[str], email: Optional[str]) -> Dict[str, Any]:
        customer = self.user_model.get_by_id(customer_id)
        if not customer or getattr(customer, "deleted_at", None) is not None:
            raise ValueError("客户不存在")
        if getattr(customer, "status", None) != "active" or getattr(customer, "user_type", None) != "CUSTOMER":
            raise ValueError("仅允许更新有效客户的联系方式")
        if phone is None and email is None:
            raise ValueError("至少需要提供手机号或邮箱")
        success, message = self.auth_service.update_profile(customer_id, phone=phone, email=email)
        if not success:
            raise RuntimeError(message or "客户联系方式更新失败")
        persisted = self.user_model.get_by_id(customer_id)
        if not persisted:
            raise RuntimeError("联系方式更新后无法读取客户记录")
        if phone is not None and getattr(persisted, "phone", None) != phone:
            raise RuntimeError("手机号更新未持久化")
        if email is not None and getattr(persisted, "email", None) != email:
            raise RuntimeError("邮箱更新未持久化")
        return {
            "customer_id": customer_id,
            "updated_fields": [name for name, value in (("phone", phone), ("email", email)) if value is not None],
            "phone_masked": self._mask_phone(phone) if phone is not None else None,
            "email_masked": self._mask_email(email) if email is not None else None,
        }

    @staticmethod
    def _mask_phone(phone: str) -> str:
        value = str(phone)
        return "*" * max(len(value) - 4, 0) + value[-4:]

    @staticmethod
    def _mask_email(email: str) -> str:
        value = str(email)
        if "@" not in value:
            return "***"
        local, domain = value.rsplit("@", 1)
        return (local[:1] + "***" if local else "***") + "@" + domain


class RepositoryRiskAlertGateway:
    """通过 RiskAlertRepository 写入人工可疑交易预警。"""

    def __init__(self, repository: Any = None, user_model: Any = None, now: Callable[[], datetime] = datetime.now):
        if repository is None:
            from app.WealthButler.Repository.riskAlertRepository import RiskAlertRepository

            repository = RiskAlertRepository
        if user_model is None:
            from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel

            user_model = BaseUserExtModel
        self.repository = repository
        self.user_model = user_model
        self.now = now

    def report_suspicious_transaction(
        self,
        reporter_id: int,
        customer_id: int,
        severity: str,
        description: str,
        related_transaction_id: Optional[int],
        evidence_refs: Optional[list],
    ) -> Dict[str, Any]:
        if severity not in {"low", "medium", "high"}:
            raise ValueError("人工可疑上报严重性仅支持 low、medium、high")
        reporter = self.user_model.get_by_id(reporter_id)
        if not reporter or getattr(reporter, "user_type", None) != "EMPLOYEE" or getattr(reporter, "status", None) != "active" or getattr(reporter, "deleted_at", None) is not None:
            raise ValueError("上报人不是有效员工")
        details = {
            "source": "manual",
            "reporter_id": reporter_id,
            "reporter_role": getattr(reporter, "employee_role", None),
            "reason": description,
            "evidence_refs": evidence_refs or [],
            "reported_at": self.now().isoformat(),
        }
        alert = self.repository.create(
            customer_id=customer_id,
            rule_id="MANUAL",
            rule_name="人工可疑上报",
            severity=severity,
            confidence=Decimal("1.000"),
            trigger_details=details,
            related_transaction_id=related_transaction_id,
        )
        if alert is None:
            raise RuntimeError("人工可疑预警写入失败")
        return {
            "alert_id": _model_id(alert, "风险预警"),
            "rule_id": "MANUAL",
            "rule_name": "人工可疑上报",
            "severity": severity,
            "confidence": Decimal("1.000"),
            "status": getattr(alert, "status", "待处理"),
            "related_transaction_id": related_transaction_id,
        }


class EventBusPublisherGateway:
    """对现有 EventBus 的抛异常式发布封装。"""

    def __init__(self, event_bus: Any = None, validator: Optional[Callable[[str, dict], Any]] = None):
        if event_bus is None:
            from app.WealthButler.EventBus.eventBus import EventBus

            event_bus = EventBus
        if validator is None:
            from app.WealthButler.EventBus.schemas import validate_event

            validator = validate_event
        self.event_bus = event_bus
        self.validator = validator

    def publish(self, stream_key: str, event_type: str, payload: Dict[str, Any], source_agent: str, trace_id: str) -> str:
        self.validator(event_type, payload)
        message_id = self.event_bus.publish(stream_key, event_type, payload, source_agent, trace_id)
        if not message_id:
            raise RuntimeError("EventBus.publish 返回空 message_id")
        return message_id.decode() if isinstance(message_id, bytes) else str(message_id)

    def enqueue_retry(
        self,
        stream_key: str,
        event_type: str,
        payload: Dict[str, Any],
        source_agent: str,
        trace_id: str,
        failure_reason: str,
    ) -> str:
        retry_payload = {
            "original_stream": stream_key,
            "original_event_type": event_type,
            "original_payload": payload,
            "original_source_agent": source_agent,
            "failure_reason": failure_reason,
        }
        message_id = self.event_bus.publish(
            f"{stream_key}:retry",
            "operator_event_retry",
            retry_payload,
            "operator_agent",
            trace_id,
        )
        if not message_id:
            raise RuntimeError("EventBus retry 写入返回空 message_id")
        return message_id.decode() if isinstance(message_id, bytes) else str(message_id)

    def replay_retry(self, retry_payload: Dict[str, Any], trace_id: str) -> str:
        """重放持久化的补发信封。"""
        if not isinstance(retry_payload, dict):
            raise ValueError("retry payload 必须为对象")
        required = {
            "original_stream",
            "original_event_type",
            "original_payload",
            "original_source_agent",
        }
        if required - set(retry_payload):
            raise ValueError("retry payload 缺少原事件字段")
        return self.publish(
            retry_payload["original_stream"],
            retry_payload["original_event_type"],
            retry_payload["original_payload"],
            retry_payload["original_source_agent"],
            trace_id,
        )

    def handle_retry_event(self, event_type: str, payload: Dict[str, Any], trace_id: str) -> bool:
        """适配 EventBus.consume 的 handler 合同，成功重放后才允许 ACK。"""
        if event_type != "operator_event_retry":
            return False
        self.replay_retry(payload, trace_id)
        return True


class LoggingOperationAuditGateway:
    """仅记录字段名和脱敏结果的结构化操作审计。"""

    _SAFE_PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

    def __init__(self, sink: Optional[Callable[[str], Any]] = None):
        self.sink = sink or (lambda payload: logger.info("operator_audit %s", payload))

    @staticmethod
    def _reference(kind: str, value: Any) -> Optional[str]:
        if value is None:
            return None
        return hashlib.sha256(f"operator-audit:{kind}:{value}".encode("utf-8")).hexdigest()[:16]

    def record(self, entry: Dict[str, Any]) -> None:
        parameter_names = entry.get("parameter_names") or []
        if not isinstance(parameter_names, list):
            raise ValueError("审计 parameter_names 必须为数组")
        safe_names = sorted({name for name in parameter_names if isinstance(name, str) and self._SAFE_PARAMETER_NAME.fullmatch(name)})
        sanitized = {
            "employee_ref": self._reference("employee", entry.get("employee_id")),
            "customer_ref": self._reference("customer", entry.get("customer_id")),
            "intent": str(entry.get("intent", ""))[:64],
            "trace_ref": self._reference("trace", entry.get("trace_id")),
            "parameter_names": safe_names,
            "success": bool(entry.get("success", False)),
            "result_code": str(entry.get("result_code", ""))[:64],
        }
        result = self.sink(json.dumps(sanitized, ensure_ascii=False, sort_keys=True))
        if result is False:
            raise RuntimeError("操作审计写入失败")


class MySQLOperationAuditGateway:
    """向 ``biz_operation_audit`` 追加写入脱敏审计记录。

    连接由集成层显式注入，每次 ``record`` 使用独立事务。只保存
    参数名，不保存手机号、账号、问卷答案等参数值。
    """

    def __init__(self, connection_provider: Callable[[], Any]):
        if not callable(connection_provider):
            raise TypeError("connection_provider 必须可调用")
        self.connection_provider = connection_provider

    def record(self, entry: Dict[str, Any]) -> None:
        parameter_names = entry.get("parameter_names") or []
        if not isinstance(parameter_names, list):
            raise ValueError("审计 parameter_names 必须为数组")
        safe_names = sorted({
            name for name in parameter_names
            if isinstance(name, str) and LoggingOperationAuditGateway._SAFE_PARAMETER_NAME.fullmatch(name)
        })
        employee_id = entry.get("employee_id")
        customer_id = entry.get("customer_id")
        if isinstance(employee_id, bool) or not isinstance(employee_id, int) or employee_id <= 0:
            raise ValueError("审计 employee_id 必须为正整数")
        if customer_id is not None and (
            isinstance(customer_id, bool) or not isinstance(customer_id, int) or customer_id <= 0
        ):
            raise ValueError("审计 customer_id 必须为正整数或空")
        trace_id = str(entry.get("trace_id") or "").strip()
        intent = str(entry.get("intent") or "").strip()
        result_code = str(entry.get("result_code") or "").strip()
        if not trace_id or len(trace_id) > 64:
            raise ValueError("审计 trace_id 必须为1-64字符")
        if not intent or len(intent) > 64 or not result_code or len(result_code) > 64:
            raise ValueError("审计 intent/result_code 必须为1-64字符")

        connection = self.connection_provider()
        if connection is None:
            raise RuntimeError("MySQL audit connection provider returned None")
        cursor = None
        try:
            connection.begin()
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO `biz_operation_audit` "
                "(`audit_event_id`, `trace_id`, `employee_id`, `customer_id`, `intent`, "
                "`parameter_names`, `success`, `result_code`, `failure_code`, `failure_reason`) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(uuid4()), trace_id, employee_id, customer_id, intent,
                    json.dumps(safe_names, ensure_ascii=False),
                    1 if entry.get("success") else 0,
                    result_code,
                    None if entry.get("success") else result_code,
                    None,
                ),
            )
            if getattr(cursor, "rowcount", 1) != 1:
                raise RuntimeError("操作审计写入未成功")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor is not None:
                cursor.close()
            connection.close()


__all__ = [
    "ModelWorkOrderGateway",
    "ServiceRiskAssessmentGateway",
    "AuthCustomerInfoGateway",
    "RepositoryRiskAlertGateway",
    "EventBusPublisherGateway",
    "LoggingOperationAuditGateway",
    "MySQLOperationAuditGateway",
]
