"""业务操作 Agent 的确定性编排服务。

此层不直接访问数据库或 Redis。跨模块能力全部由 Adapter 注入，便于阶段 1
离线测试和最终联调替换真实实现。
"""

from decimal import Decimal
from typing import Any, Dict, Optional

from app.WealthButler.Service.confirmationService import ConfirmationService
from app.WealthButler.Service.operatorAdapters import (
    AdvisorQualificationGateway,
    CustomerGateway,
    CustomerInfoGateway,
    EventPublisher,
    HoldingGateway,
    OperationAuditGateway,
    OperationRiskGateway,
    PermissionGateway,
    PurchaseComplianceGateway,
    ProductGateway,
    RiskAlertGateway,
    RiskAssessmentGateway,
    SuitabilityGateway,
    TransactionGateway,
    WorkOrderGateway,
)
from app.WealthButler.Service.operatorContracts import (
    CONFIRMATION_THRESHOLDS,
    IdempotencyConflictError,
    INTENT_PERMISSIONS,
    OperationCommand,
    OperationResult,
    to_decimal,
)


class OperationService:
    """业务操作的校验、确认与提交编排。"""

    def __init__(
        self,
        permission_gateway: PermissionGateway,
        customer_gateway: CustomerGateway,
        advisor_qualification_gateway: AdvisorQualificationGateway,
        product_gateway: ProductGateway,
        suitability_gateway: SuitabilityGateway,
        purchase_compliance_gateway: PurchaseComplianceGateway,
        holding_gateway: HoldingGateway,
        transaction_gateway: TransactionGateway,
        work_order_gateway: WorkOrderGateway,
        risk_assessment_gateway: RiskAssessmentGateway,
        customer_info_gateway: CustomerInfoGateway,
        risk_alert_gateway: RiskAlertGateway,
        event_publisher: EventPublisher,
        operation_risk_gateway: OperationRiskGateway,
        operation_audit_gateway: OperationAuditGateway,
        confirmation_service: Optional[ConfirmationService] = None,
    ):
        self.permission_gateway = permission_gateway
        self.customer_gateway = customer_gateway
        self.advisor_qualification_gateway = advisor_qualification_gateway
        self.product_gateway = product_gateway
        self.suitability_gateway = suitability_gateway
        self.purchase_compliance_gateway = purchase_compliance_gateway
        self.holding_gateway = holding_gateway
        self.transaction_gateway = transaction_gateway
        self.work_order_gateway = work_order_gateway
        self.risk_assessment_gateway = risk_assessment_gateway
        self.customer_info_gateway = customer_info_gateway
        self.risk_alert_gateway = risk_alert_gateway
        self.event_publisher = event_publisher
        self.operation_risk_gateway = operation_risk_gateway
        self.operation_audit_gateway = operation_audit_gateway
        self.confirmation_service = confirmation_service or ConfirmationService()

    def submit(self, employee_id: int, customer_id: int, command: OperationCommand) -> OperationResult:
        """提交一条已解析命令；命中确认阈值时只创建令牌。"""
        result = self._submit(employee_id, customer_id, command)
        return self._audit_result(employee_id, customer_id, command, result)

    def _submit(self, employee_id: int, customer_id: int, command: OperationCommand) -> OperationResult:
        authorization_error = self.authorize(employee_id, command.intent, command.trace_id)
        if authorization_error:
            return authorization_error
        if customer_id <= 0:
            return self._fail("INVALID_CUSTOMER", "客户ID必须为正整数", command)
        if not self.customer_gateway.exists(customer_id):
            return self._fail("CUSTOMER_NOT_FOUND", "客户不存在", command)

        preflight = self._preflight(employee_id, customer_id, command)
        if preflight:
            return preflight

        if self._requires_confirmation(command):
            pending = self.confirmation_service.create(employee_id, customer_id, command)
            return OperationResult(
                True,
                "CONFIRMATION_REQUIRED",
                "操作需要线下确认后再执行",
                metadata={
                    "confirm_required": True,
                    "confirm_token": pending.token,
                    "pending_action": command.intent,
                    "trace_id": command.trace_id,
                },
            )
        return self._execute_after_preflight(employee_id, customer_id, command)

    def authorize(self, employee_id: int, intent: str, trace_id: str) -> Optional[OperationResult]:
        """按已识别意图执行动态 RBAC，供 Agent 在参数追问前调用。"""
        permission = INTENT_PERMISSIONS.get(intent)
        command = OperationCommand(intent=intent, params={}, trace_id=trace_id)
        if not permission:
            return self._fail("UNKNOWN_INTENT", "不支持的业务操作意图", command)
        if not self.permission_gateway.has_permission(employee_id, permission):
            return self._fail("PERMISSION_DENIED", "当前员工无此操作权限", command)
        return None

    def confirm(self, token: str, employee_id: int, customer_id: int) -> OperationResult:
        """确认待确认动作；状态机保证同一令牌最多成交一次。"""
        pending = self.confirmation_service.get_pending(token)
        result = self.confirmation_service.confirm(
            token,
            employee_id,
            customer_id,
            self._execute_confirmed,
        )
        command = pending.command if pending else OperationCommand("confirmation", {}, trace_id="")
        return self._audit_result(employee_id, customer_id, command, result)

    def cancel(self, token: str, employee_id: int, customer_id: int) -> OperationResult:
        pending = self.confirmation_service.get_pending(token)
        result = self.confirmation_service.cancel(token, employee_id, customer_id)
        command = pending.command if pending else OperationCommand("confirmation", {}, trace_id="")
        return self._audit_result(employee_id, customer_id, command, result)

    def _preflight(self, employee_id: int, customer_id: int, command: OperationCommand) -> Optional[OperationResult]:
        if command.intent == "purchase":
            return self._preflight_purchase(employee_id, customer_id, command)
        if command.intent == "redeem":
            return self._preflight_redeem(customer_id, command)
        if command.intent == "transfer":
            return self._preflight_transfer(customer_id, command)
        if command.intent == "reassess":
            return self._validate_assessment(command)
        if command.intent == "update_info":
            return self._validate_contact(command)
        if command.intent == "suspicious_report":
            return self._validate_suspicious_report(command)
        if command.intent == "workorder_create":
            return self._require(command, "order_type")
        return None

    def _preflight_purchase(self, employee_id: int, customer_id: int, command: OperationCommand) -> Optional[OperationResult]:
        required = self._require(command, "product_id", "amount")
        if required:
            return required
        try:
            amount = to_decimal(command.params["amount"], "申购金额")
        except ValueError as exc:
            return self._fail("INVALID_AMOUNT", str(exc), command)
        if amount <= 0:
            return self._fail("INVALID_AMOUNT", "申购金额必须大于0", command)

        product = self.product_gateway.get_product(int(command.params["product_id"]))
        if not product:
            return self._fail("PRODUCT_NOT_FOUND", "产品不存在", command)
        if product.get("status") != "在售":
            return self._fail("PRODUCT_NOT_ON_SALE", "产品当前不在售", command)
        if amount < to_decimal(product.get("min_investment", "0"), "起投金额"):
            return self._fail("MINIMUM_INVESTMENT_NOT_MET", "申购金额低于产品起投金额", command)

        advisor_error = self._check_advisor_qualification(employee_id, product, command)
        if advisor_error:
            return advisor_error

        if product.get("admission_tier") == "仅预约":
            return self._create_booking(employee_id, customer_id, product, amount, command)

        suitability = self.suitability_gateway.check(customer_id, int(command.params["product_id"]))
        if not suitability.get("passed", False):
            controls = suitability.get("required_controls", [])
            if suitability.get("manual_review_required", False):
                work_order_id = command.params.get("work_order_id")
                if work_order_id:
                    try:
                        self.work_order_gateway.submit_for_review(
                            int(work_order_id), employee_id, "适当性人工控件待核验"
                        )
                    except (TypeError, ValueError) as exc:
                        return self._fail("WORK_ORDER_TRANSITION_REJECTED", str(exc), command)
                return OperationResult(
                    False,
                    "MANUAL_REVIEW_REQUIRED",
                    suitability.get("reason", "需要人工审核"),
                    metadata={"required_controls": controls, "trace_id": command.trace_id},
                )
            return self._fail("SUITABILITY_REJECTED", suitability.get("reason", "适当性校验未通过"), command)

        r3_error = self._check_fm02_r3_limit(customer_id, product, amount, suitability, command)
        if r3_error:
            return r3_error
        compliance_reason = self.purchase_compliance_gateway.validate_purchase(customer_id, product, command)
        if compliance_reason:
            return self._fail("PURCHASE_COMPLIANCE_REJECTED", compliance_reason, command)
        return None

    def _preflight_redeem(self, customer_id: int, command: OperationCommand) -> Optional[OperationResult]:
        required = self._require(command, "product_id", "shares")
        if required:
            return required
        try:
            shares = to_decimal(command.params["shares"], "赎回份额")
        except ValueError as exc:
            return self._fail("INVALID_SHARES", str(exc), command)
        if shares <= 0:
            return self._fail("INVALID_SHARES", "赎回份额必须大于0", command)
        position = self.holding_gateway.get_position(customer_id, int(command.params["product_id"]))
        available_shares = to_decimal(position.get("shares", "0"), "可赎回份额")
        if available_shares <= 0:
            return self._fail("REDEEMABLE_HOLDING_NOT_FOUND", "客户没有可赎回持仓", command)
        if shares > available_shares:
            return self._fail("INSUFFICIENT_REDEEMABLE_SHARES", "赎回份额超过当前可赎回份额", command)
        reason = self.operation_risk_gateway.validate_redeem(customer_id, int(command.params["product_id"]), shares)
        return self._fail("REDEEM_REJECTED", reason, command) if reason else None

    def _preflight_transfer(self, customer_id: int, command: OperationCommand) -> Optional[OperationResult]:
        required = self._require(command, "amount", "counterparty_account", "counterparty_name")
        if required:
            return required
        try:
            amount = to_decimal(command.params["amount"], "转账金额")
        except ValueError as exc:
            return self._fail("INVALID_AMOUNT", str(exc), command)
        if amount <= 0:
            return self._fail("INVALID_AMOUNT", "转账金额必须大于0", command)
        allowed_fields = {"amount", "counterparty_account", "counterparty_name", "channel"}
        forbidden_fields = set(command.params) - allowed_fields
        if forbidden_fields:
            return self._fail("TRANSFER_FIELD_FORBIDDEN", "转账请求包含不允许的字段", command)
        if not isinstance(command.params["counterparty_account"], str) or not command.params["counterparty_account"].strip():
            return self._fail("INVALID_COUNTERPARTY_ACCOUNT", "收款账号格式不合法", command)
        if not isinstance(command.params["counterparty_name"], str) or not command.params["counterparty_name"].strip():
            return self._fail("INVALID_COUNTERPARTY_NAME", "收款人名称格式不合法", command)
        if command.params.get("channel") is not None and not isinstance(command.params["channel"], str):
            return self._fail("INVALID_TRANSFER_CHANNEL", "转账渠道格式不合法", command)
        payee = {"account": command.params["counterparty_account"], "name": command.params["counterparty_name"], "channel": command.params.get("channel")}
        reason = self.operation_risk_gateway.validate_transfer(customer_id, amount, payee)
        return self._fail("TRANSFER_REJECTED", reason, command) if reason else None

    def _validate_assessment(self, command: OperationCommand) -> Optional[OperationResult]:
        required = self._require(command, "answers")
        if required:
            return required
        answers = command.params["answers"]
        question_ids = [item.get("question_id") for item in answers] if isinstance(answers, list) else []
        expected = {f"Q{index}" for index in range(1, 17)}
        if len(question_ids) != 16 or set(question_ids) != expected:
            return self._fail("INVALID_ASSESSMENT_ANSWERS", "风评重做必须提交Q1-Q16共16题答案", command)
        q7 = next(item for item in answers if item.get("question_id") == "Q7")
        if not isinstance(q7.get("option_ids"), list):
            return self._fail("INVALID_ASSESSMENT_ANSWERS", "Q7必须使用option_ids数组", command)
        return None

    def _validate_contact(self, command: OperationCommand) -> Optional[OperationResult]:
        if not command.params.get("phone") and not command.params.get("email"):
            return self._fail("CONTACT_REQUIRED", "至少需要提供手机号或邮箱", command)
        forbidden = set(command.params) - {"phone", "email"}
        if forbidden:
            return self._fail("CONTACT_FIELD_FORBIDDEN", "联系方式更新仅允许phone和email字段", command)
        return None

    def _validate_suspicious_report(self, command: OperationCommand) -> Optional[OperationResult]:
        description = command.params.get("description")
        severity = command.params.get("severity", "medium")
        if not isinstance(description, str) or not description.strip():
            return self._fail("REPORT_REASON_REQUIRED", "可疑上报原因不能为空", command)
        if severity not in {"low", "medium", "high"}:
            return self._fail("INVALID_REPORT_SEVERITY", "严重性仅支持low、medium或high", command)
        for ref in command.params.get("evidence_refs") or []:
            if not isinstance(ref, dict) or ref.get("type") not in {"transaction", "conversation"} or ref.get("id") is None:
                return self._fail("INVALID_EVIDENCE_REFERENCE", "证据必须为transaction或conversation类型化引用", command)
        return None

    def _execute_after_preflight(self, employee_id: int, customer_id: int, command: OperationCommand) -> OperationResult:
        if command.intent in {"purchase", "redeem", "transfer"}:
            return self._execute_transaction(employee_id, customer_id, command)
        if command.intent == "reassess":
            result = self.risk_assessment_gateway.submit_assessment(customer_id, command.params["answers"], is_professional=False)
            message = "问卷已保存，画像稍后重算" if result.get("recalc_profile") is None else "风评重做完成"
            return self._ok("ASSESSMENT_SAVED", message, command, result)
        if command.intent == "update_info":
            result = self.customer_info_gateway.update_contact(customer_id, command.params.get("phone"), command.params.get("email"))
            return self._ok("CONTACT_UPDATED", "联系方式已更新", command, result)
        if command.intent == "product_query":
            if command.params.get("product_id") is not None:
                product = self.product_gateway.get_product(int(command.params["product_id"]))
                return self._fail("PRODUCT_NOT_FOUND", "产品不存在", command) if not product else self._ok("PRODUCT_FOUND", "产品查询成功", command, product)
            result = self.product_gateway.list_products(**command.params)
            return self._ok("PRODUCT_LISTED", "产品列表查询成功", command, result)
        if command.intent == "suspicious_report":
            result = self.risk_alert_gateway.report_suspicious_transaction(
                reporter_id=employee_id,
                customer_id=customer_id,
                severity=command.params.get("severity", "medium"),
                description=command.params["description"].strip(),
                related_transaction_id=command.params.get("related_transaction_id"),
                evidence_refs=command.params.get("evidence_refs"),
            )
            return self._ok("SUSPICIOUS_REPORT_CREATED", "人工可疑上报已提交", command, result)
        if command.intent == "workorder_create":
            result = self.work_order_gateway.create_work_order(customer_id, command.params["order_type"], command.params.get("intent_summary", ""))
            return self._ok("WORK_ORDER_CREATED", "工单已创建", command, result)
        return self._fail("UNKNOWN_INTENT", "不支持的业务操作意图", command)

    def _execute_confirmed(self, employee_id: int, customer_id: int, command: OperationCommand) -> OperationResult:
        """确认前重新校验权限和业务 Gate，避免令牌成为绕过入口。"""
        authorization_error = self.authorize(employee_id, command.intent, command.trace_id)
        if authorization_error:
            return authorization_error
        if not self.customer_gateway.exists(customer_id):
            return self._fail("CUSTOMER_NOT_FOUND", "客户不存在", command)
        preflight = self._preflight(employee_id, customer_id, command)
        if preflight:
            return preflight
        return self._execute_after_preflight(employee_id, customer_id, command)

    def _execute_transaction(self, employee_id: int, customer_id: int, command: OperationCommand) -> OperationResult:
        execution, execution_error = self._build_transaction_execution(command)
        if execution_error:
            return execution_error
        try:
            transaction = self.transaction_gateway.execute(employee_id, customer_id, command, execution)
        except IdempotencyConflictError:
            return self._fail("IDEMPOTENCY_CONFLICT", "同一请求标识不能用于不同操作参数", command)
        except Exception:
            return self._fail("TRANSACTION_FAILED", "交易执行失败", command)
        if transaction.get("status") != "成交":
            return self._fail("TRANSACTION_FAILED", "交易未成交", command)
        if transaction.get("idempotent_replay"):
            return self._ok("TRANSACTION_IDEMPOTENT_REPLAY", "请求已处理，已返回原交易结果", command, transaction)

        payload = {"customer_id": customer_id, "transaction_id": transaction["transaction_id"]}
        if command.intent != "transfer":
            payload["product_id"] = transaction.get("product_id")
        else:
            payload["product_id"] = None
        if transaction.get("amount") is not None:
            payload["amount"] = f"{to_decimal(transaction['amount'], '交易金额'):.2f}"
        payload["transaction_type"] = transaction["transaction_type"]
        try:
            self.event_publisher.publish("stream:large_transaction", "large_transaction", payload, "operator_agent", command.trace_id)
        except Exception as exc:
            # 交易已提交，事件失败只能记录为可审计失败，不能伪造回滚。
            try:
                self.event_publisher.enqueue_retry(
                    "stream:large_transaction",
                    "large_transaction",
                    payload,
                    "operator_agent",
                    command.trace_id,
                    str(exc),
                )
            except Exception:
                pass
            return self._ok(
                "TRANSACTION_SUCCEEDED_EVENT_PENDING",
                "交易已成交，风控事件待补发",
                command,
                transaction,
                {"event_pending": True},
            )
        return self._ok("TRANSACTION_SUCCEEDED", "交易已成交", command, transaction)

    def _build_transaction_execution(self, command: OperationCommand) -> tuple[Optional[Dict[str, Any]], Optional[OperationResult]]:
        if command.intent == "transfer":
            return {"amount": to_decimal(command.params["amount"], "转账金额")}, None
        product = self.product_gateway.get_product(int(command.params["product_id"]))
        if not product:
            return None, self._fail("PRODUCT_NOT_FOUND", "产品不存在", command)
        try:
            nav = to_decimal(product.get("nav"), "产品净值")
        except ValueError as exc:
            return None, self._fail("PRODUCT_NAV_UNAVAILABLE", str(exc), command)
        if nav <= 0:
            return None, self._fail("PRODUCT_NAV_UNAVAILABLE", "产品净值必须大于0", command)

        if command.intent == "purchase":
            amount = to_decimal(command.params["amount"], "申购金额")
            shares = (amount / nav).quantize(Decimal("0.000001"))
        else:
            shares = to_decimal(command.params["shares"], "赎回份额")
            amount = (shares * nav).quantize(Decimal("0.01"))
        return {
            "product_id": int(command.params["product_id"]),
            "risk_level": product.get("risk_level"),
            "amount": amount,
            "shares": shares,
            "nav": nav,
        }, None

    def _create_booking(self, employee_id: int, customer_id: int, product: Dict[str, Any], amount: Decimal, command: OperationCommand) -> OperationResult:
        summary = f"预约申购{product.get('product_name', '产品')}（{product.get('risk_level', '')}），意向金额{amount:.2f}元，待资格初核"
        work_order_id = command.params.get("work_order_id")
        if work_order_id:
            try:
                order = self.work_order_gateway.submit_for_review(int(work_order_id), employee_id, summary)
            except (TypeError, ValueError) as exc:
                return self._fail("WORK_ORDER_TRANSITION_REJECTED", str(exc), command)
        else:
            order = self.work_order_gateway.create_booking(customer_id, summary, int(command.params["product_id"]))
        return self._ok("BOOKING_CREATED", "产品仅可预约，已提交资格初核", command, order, {"admission_tier": "仅预约", "work_order_id": order["id"]})

    def _check_advisor_qualification(self, employee_id: int, product: Dict[str, Any], command: OperationCommand) -> Optional[OperationResult]:
        """员工侧资质独立于客户适当性，缺失或未知等级按拒绝处理。"""
        maximum_risk_level = {"初级": 2, "中级": 3, "高级": 5}
        advisor_level = self.advisor_qualification_gateway.get_advisor_level(employee_id)
        if advisor_level not in maximum_risk_level:
            return self._fail("ADVISOR_LEVEL_UNAVAILABLE", "无法确认理财顾问执业等级，暂不能办理申购", command)
        risk_level = product.get("risk_level")
        if not isinstance(risk_level, str) or risk_level not in {"R1", "R2", "R3", "R4", "R5"}:
            return self._fail("PRODUCT_RISK_LEVEL_INVALID", "产品风险等级不合法，暂不能办理申购", command)
        if int(risk_level[1]) > maximum_risk_level[advisor_level]:
            return self._fail(
                "ADVISOR_QUALIFICATION_REJECTED",
                f"{advisor_level}理财顾问仅可销售R1-R{maximum_risk_level[advisor_level]}产品",
                command,
            )
        return None

    def claim_referral_work_order(self, work_order_id: int, handler_id: int, trace_id: str = "") -> OperationResult:
        return self._run_work_order_action(
            "WORK_ORDER_CLAIMED", "工单已领取", work_order_id, handler_id, trace_id, self.work_order_gateway.claim
        )

    def submit_referral_work_order_for_review(self, work_order_id: int, handler_id: int, handle_note: str, trace_id: str = "") -> OperationResult:
        return self._run_work_order_action(
            "WORK_ORDER_REVIEW_SUBMITTED", "工单已提交审核", work_order_id, handler_id, trace_id,
            self.work_order_gateway.submit_for_review, handle_note,
        )

    def complete_referral_work_order(
        self,
        work_order_id: int,
        handler_id: int,
        related_entity_type: str,
        related_entity_id: int,
        handle_note: str,
        trace_id: str = "",
    ) -> OperationResult:
        return self._run_work_order_action(
            "WORK_ORDER_COMPLETED", "工单已完成", work_order_id, handler_id, trace_id,
            self.work_order_gateway.complete, related_entity_type, related_entity_id, handle_note,
        )

    def reject_referral_work_order(self, work_order_id: int, handler_id: int, handle_note: str, trace_id: str = "") -> OperationResult:
        return self._run_work_order_action(
            "WORK_ORDER_REJECTED", "工单已驳回", work_order_id, handler_id, trace_id,
            self.work_order_gateway.reject, handle_note,
        )

    def _run_work_order_action(self, code: str, message: str, work_order_id: int, handler_id: int, trace_id: str, action: Any, *args: Any) -> OperationResult:
        command = OperationCommand(intent="workorder_create", params={}, trace_id=trace_id)
        try:
            order = action(work_order_id, handler_id, *args)
        except (TypeError, ValueError) as exc:
            return self._fail("WORK_ORDER_TRANSITION_REJECTED", str(exc), command)
        return self._ok(code, message, command, order)

    def _audit_result(
        self,
        employee_id: int,
        customer_id: int,
        command: OperationCommand,
        result: OperationResult,
    ) -> OperationResult:
        """审计只保存字段名与结果，避免账号、证据和联系方式进入日志明文。"""
        entry = {
            "employee_id": employee_id,
            "customer_id": customer_id,
            "intent": command.intent,
            "trace_id": command.trace_id,
            "parameter_names": sorted(command.params.keys()),
            "success": result.success,
            "result_code": result.code,
        }
        try:
            self.operation_audit_gateway.record(entry)
        except Exception:
            # 审计下游不可用不能把已确定的业务结果改写为失败。
            pass
        return result

    def _check_fm02_r3_limit(self, customer_id: int, product: Dict[str, Any], amount: Decimal, suitability: Dict[str, Any], command: OperationCommand) -> Optional[OperationResult]:
        if product.get("risk_level") != "R3":
            return None
        fm02 = next((item for item in suitability.get("fm_hits", []) if item.get("code") == "FM-02" and item.get("level") == "block"), None)
        if not fm02:
            return None
        constraints = fm02.get("constraints")
        if not constraints:
            return self._fail("FM_CONSTRAINTS_MISSING", "FM-02缺少结构化约束，按最严规则拒绝", command)
        limit = constraints.get("max_r3_position_pct")
        if limit is None:
            max_level = constraints.get("max_product_risk_level")
            if max_level in {"R1", "R2"}:
                return self._fail("FM02_RISK_LEVEL_REJECTED", "FM-02限制仅允许购买R1-R2产品", command)
            return None
        asset_basis = to_decimal(constraints.get("asset_basis_amount", "0"), "FM-02资产基数")
        projected_total = max(asset_basis, to_decimal(self.holding_gateway.current_total_value(customer_id), "当前总持仓") + amount)
        projected_r3 = to_decimal(self.holding_gateway.current_r3_value(customer_id), "当前R3持仓") + amount
        if projected_total <= 0:
            return self._fail("FM02_ASSET_BASIS_INVALID", "无法确定有效的资产基数", command)
        if projected_r3 / projected_total > to_decimal(limit, "FM-02仓位上限"):
            return self._fail("FM02_POSITION_LIMIT_EXCEEDED", "R3产品预计持仓超过总资产30%", command)
        return None

    def _requires_confirmation(self, command: OperationCommand) -> bool:
        threshold = CONFIRMATION_THRESHOLDS.get(command.intent)
        if threshold is None:
            return False
        return to_decimal(command.params["amount"], "操作金额") > threshold

    def _require(self, command: OperationCommand, *fields: str) -> Optional[OperationResult]:
        missing = [
            field
            for field in fields
            if command.params.get(field) is None or command.params.get(field) == ""
        ]
        if missing:
            return self._fail("MISSING_PARAMS", "缺少必要参数：" + "、".join(missing), command, {"missing_params": missing})
        return None

    def _ok(self, code: str, message: str, command: OperationCommand, data: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> OperationResult:
        final_metadata = {"trace_id": command.trace_id}
        if metadata:
            final_metadata.update(metadata)
        return OperationResult(True, code, message, data=data, metadata=final_metadata)

    def _fail(self, code: str, message: str, command: OperationCommand, metadata: Optional[Dict[str, Any]] = None) -> OperationResult:
        final_metadata = {"trace_id": command.trace_id}
        if metadata:
            final_metadata.update(metadata)
        return OperationResult(False, code, message, metadata=final_metadata)
