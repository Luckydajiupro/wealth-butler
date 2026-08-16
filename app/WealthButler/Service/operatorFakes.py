"""阶段 1 离线测试使用的内存 Adapter。"""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
from threading import RLock
from typing import Any, Dict, Optional, Set, Tuple

from app.WealthButler.Service.operatorContracts import IdempotencyConflictError, OperationCommand


class FakePermissionGateway:
    def __init__(self, permissions: Optional[Dict[int, Set[str]]] = None):
        self.permissions = permissions or {}

    def has_permission(self, employee_id: int, permission: str) -> bool:
        return permission in self.permissions.get(employee_id, set())


class FakeCustomerGateway:
    def __init__(self, customer_ids: Optional[Set[int]] = None):
        self.customer_ids = customer_ids or set()

    def exists(self, customer_id: int) -> bool:
        return customer_id in self.customer_ids


class FakeAdvisorQualificationGateway:
    def __init__(self, advisor_levels: Optional[Dict[int, Optional[str]]] = None):
        self.advisor_levels = advisor_levels or {}

    def get_advisor_level(self, employee_id: int) -> Optional[str]:
        return self.advisor_levels.get(employee_id)


class FakeProductGateway:
    def __init__(self, products: Optional[Dict[int, Dict[str, Any]]] = None):
        self.products = products or {}

    def get_product(self, product_id: int) -> Optional[Dict[str, Any]]:
        product = self.products.get(product_id)
        return deepcopy(product) if product else None

    def list_products(self, **filters: Any) -> Dict[str, Any]:
        items = list(self.products.values())
        for field in ("product_type", "risk_level", "status"):
            if filters.get(field) is not None:
                items = [item for item in items if item.get(field) == filters[field]]
        keyword = filters.get("keyword")
        if keyword:
            items = [item for item in items if keyword in item.get("product_name", "")]
        page = int(filters.get("page", 1))
        per_page = int(filters.get("per_page", 20))
        start = (page - 1) * per_page
        return {"items": deepcopy(items[start:start + per_page]), "total": len(items), "page": page, "per_page": per_page}


class FakeSuitabilityGateway:
    def __init__(self, results: Optional[Dict[Tuple[int, int], Dict[str, Any]]] = None):
        self.results = results or {}

    def check(self, customer_id: int, product_id: int) -> Dict[str, Any]:
        default = {
            "passed": True,
            "reason": "适当性校验通过",
            "requires_disclosure": False,
            "position_limit_pct": None,
            "admission_tier": "可执行",
            "required_controls": [],
            "manual_review_required": False,
            "fm_hits": [],
        }
        default.update(self.results.get((customer_id, product_id), {}))
        return deepcopy(default)


class FakePurchaseComplianceGateway:
    def __init__(self, reject_reasons: Optional[Dict[Tuple[int, int], str]] = None):
        self.reject_reasons = reject_reasons or {}

    def validate_purchase(self, customer_id: int, product: Dict[str, Any], command: OperationCommand) -> Optional[str]:
        return self.reject_reasons.get((customer_id, int(product["product_id"])))


class FakeHoldingGateway:
    def __init__(
        self,
        total_values: Optional[Dict[int, Any]] = None,
        r3_values: Optional[Dict[int, Any]] = None,
        positions: Optional[Dict[Tuple[int, int], Dict[str, Any]]] = None,
    ):
        self.total_values = total_values or {}
        self.r3_values = r3_values or {}
        self.positions = deepcopy(positions or {})

    def current_total_value(self, customer_id: int) -> Decimal:
        return Decimal(str(self.total_values.get(customer_id, "0")))

    def current_r3_value(self, customer_id: int) -> Decimal:
        return Decimal(str(self.r3_values.get(customer_id, "0")))

    def get_position(self, customer_id: int, product_id: int) -> Dict[str, Any]:
        position = self.positions.get((customer_id, product_id))
        if not position:
            return {
                "customer_id": customer_id,
                "product_id": product_id,
                "shares": "0.000000",
                "current_value": "0.00",
                "average_cost": "0.00",
            }
        return deepcopy(position)

    def apply_transaction(
        self,
        customer_id: int,
        product_id: int,
        transaction_type: str,
        shares: Decimal,
        amount: Decimal,
        risk_level: Optional[str],
    ) -> Dict[str, Any]:
        """先完成所有份额计算，再一次性更新内存持仓，模拟同一事务边界。"""
        key = (customer_id, product_id)
        before = self.get_position(customer_id, product_id)
        before_shares = Decimal(str(before["shares"]))
        before_value = Decimal(str(before["current_value"]))
        before_cost = Decimal(str(before["average_cost"]))

        if transaction_type == "purchase":
            after_shares = before_shares + shares
            after_value = before_value + amount
            average_cost = (before_cost * before_shares + amount) / after_shares
            value_delta = amount
        elif transaction_type == "redeem":
            if shares > before_shares:
                raise ValueError("可赎回份额不足")
            after_shares = before_shares - shares
            after_value = max(Decimal("0"), before_value - amount)
            average_cost = Decimal("0") if after_shares == 0 else before_cost
            value_delta = -amount
        else:
            raise ValueError("不支持的持仓变动类型")

        position = {
            "customer_id": customer_id,
            "product_id": product_id,
            "shares": f"{after_shares.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP):.6f}",
            "current_value": f"{after_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}",
            "average_cost": f"{average_cost.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP):.6f}",
        }
        self.positions[key] = position
        self.total_values[customer_id] = self.current_total_value(customer_id) + value_delta
        if risk_level == "R3":
            self.r3_values[customer_id] = self.current_r3_value(customer_id) + value_delta
        return deepcopy(position)


class FakeTransactionGateway:
    def __init__(self, holding_gateway: FakeHoldingGateway):
        self.holding_gateway = holding_gateway
        self.transactions = []
        self.fail_reason: Optional[str] = None
        self._transactions_by_trace: Dict[str, Dict[str, Any]] = {}
        self._lock = RLock()

    def execute(
        self,
        employee_id: int,
        customer_id: int,
        command: OperationCommand,
        execution: Dict[str, Any],
    ) -> Dict[str, Any]:
        with self._lock:
            request_fingerprint = self._request_fingerprint(employee_id, customer_id, command, execution)
            previous = self._transactions_by_trace.get(command.trace_id)
            if previous:
                if previous["request_fingerprint"] != request_fingerprint:
                    raise IdempotencyConflictError("幂等键已用于不同请求")
                replay = deepcopy(previous["transaction"])
                replay["idempotent_replay"] = True
                return replay
            if self.fail_reason:
                raise RuntimeError(self.fail_reason)

            transaction_type = {"purchase": "申购", "redeem": "赎回", "transfer": "转账"}[command.intent]
            amount = Decimal(str(execution["amount"]))
            holding_after = None
            if command.intent in {"purchase", "redeem"}:
                holding_after = self.holding_gateway.apply_transaction(
                    customer_id=customer_id,
                    product_id=int(execution["product_id"]),
                    transaction_type=command.intent,
                    shares=Decimal(str(execution["shares"])),
                    amount=amount,
                    risk_level=execution.get("risk_level"),
                )
            transaction = {
                "transaction_id": len(self.transactions) + 1,
                "customer_id": customer_id,
                "product_id": execution.get("product_id"),
                "amount": f"{amount:.2f}",
                "shares": execution.get("shares"),
                "transaction_type": transaction_type,
                "status": "成交",
                "employee_id": employee_id,
                "trace_id": command.trace_id,
                "intent": command.intent,
                "holding_after": holding_after,
            }
            self.transactions.append(transaction)
            self._transactions_by_trace[command.trace_id] = {
                "request_fingerprint": request_fingerprint,
                "transaction": transaction,
            }
            return deepcopy(transaction)

    @staticmethod
    def _request_fingerprint(
        employee_id: int,
        customer_id: int,
        command: OperationCommand,
        execution: Dict[str, Any],
    ) -> str:
        payload = {
            "employee_id": employee_id,
            "customer_id": customer_id,
            "intent": command.intent,
            "params": command.params,
            "execution": execution,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


class FakeWorkOrderGateway:
    _ALLOWED_TRANSITIONS = {
        "待处理": {"处理中", "已驳回"},
        "处理中": {"待审核", "已完成", "已驳回"},
        "待审核": {"处理中", "已完成", "已驳回"},
        "已完成": set(),
        "已驳回": set(),
    }

    def __init__(self):
        self.orders: Dict[int, Dict[str, Any]] = {}
        self.transitions = []

    def create_booking(self, customer_id: int, summary: str, product_id: int) -> Dict[str, Any]:
        order = self.create_work_order(customer_id, "业务申请", summary)
        order["product_id"] = product_id
        self.orders[order["id"]]["product_id"] = product_id
        return order

    def create_work_order(self, customer_id: int, order_type: str, summary: str) -> Dict[str, Any]:
        order_id = len(self.orders) + 1
        order = {"id": order_id, "customer_id": customer_id, "order_type": order_type, "summary": summary, "status": "待处理"}
        self.orders[order_id] = order
        return deepcopy(order)

    def transition(self, work_order_id: int, status: str, note: str) -> Dict[str, Any]:
        order = self._get_order(work_order_id)
        self._transition(order, status, note, None)
        return deepcopy(order)

    def claim(self, work_order_id: int, handler_id: int) -> Dict[str, Any]:
        order = self._get_order(work_order_id)
        self._transition(order, "处理中", "领取工单", handler_id)
        return deepcopy(order)

    def submit_for_review(self, work_order_id: int, handler_id: int, note: str) -> Dict[str, Any]:
        order = self._get_order(work_order_id)
        self._ensure_handler(order, handler_id)
        self._transition(order, "待审核", note, handler_id)
        return deepcopy(order)

    def complete(
        self,
        work_order_id: int,
        handler_id: int,
        related_entity_type: str,
        related_entity_id: int,
        handle_note: str,
    ) -> Dict[str, Any]:
        order = self._get_order(work_order_id)
        self._ensure_handler(order, handler_id)
        order["related_entity_type"] = related_entity_type
        order["related_entity_id"] = related_entity_id
        self._transition(order, "已完成", handle_note, handler_id)
        return deepcopy(order)

    def reject(self, work_order_id: int, handler_id: int, handle_note: str) -> Dict[str, Any]:
        order = self._get_order(work_order_id)
        if order.get("status") != "待处理":
            self._ensure_handler(order, handler_id)
        self._transition(order, "已驳回", handle_note, handler_id)
        return deepcopy(order)

    def _get_order(self, work_order_id: int) -> Dict[str, Any]:
        order = self.orders.get(work_order_id)
        if not order:
            raise ValueError("工单不存在")
        return order

    def _ensure_handler(self, order: Dict[str, Any], handler_id: int) -> None:
        if order.get("handler_id") != handler_id:
            raise ValueError("当前员工不是工单处理人")

    def _transition(self, order: Dict[str, Any], target_status: str, note: str, handler_id: Optional[int]) -> None:
        current_status = order["status"]
        if target_status not in self._ALLOWED_TRANSITIONS.get(current_status, set()):
            raise ValueError(f"工单不能从{current_status}流转到{target_status}")
        if handler_id is not None:
            order["handler_id"] = handler_id
        order["status"] = target_status
        order.setdefault("handle_records", []).append(
            {"status": target_status, "note": note, "handler_id": handler_id}
        )
        self.transitions.append((order["id"], target_status, note))


class FakeRiskAssessmentGateway:
    def __init__(self, result: Optional[Dict[str, Any]] = None):
        self.result = result or {"risk_level": "C3", "recalc_profile": {"risk_level": "C3"}}
        self.calls = []

    def submit_assessment(self, customer_id: int, answers: list, is_professional: bool = False) -> Dict[str, Any]:
        self.calls.append((customer_id, deepcopy(answers), is_professional))
        return deepcopy(self.result)


class FakeCustomerInfoGateway:
    def __init__(self):
        self.updates = []

    def update_contact(self, customer_id: int, phone: Optional[str], email: Optional[str]) -> Dict[str, Any]:
        update = {"customer_id": customer_id, "phone": phone, "email": email}
        self.updates.append(update)
        return deepcopy(update)


class FakeRiskAlertGateway:
    def __init__(self, reporter_roles: Optional[Dict[int, str]] = None):
        self.reports = []
        self.reporter_roles = reporter_roles or {8: "理财顾问"}

    def report_suspicious_transaction(self, reporter_id: int, customer_id: int, severity: str, description: str, related_transaction_id: Optional[int], evidence_refs: Optional[list]) -> Dict[str, Any]:
        report = {
            "alert_id": len(self.reports) + 1,
            "rule_id": "MANUAL",
            "rule_name": "人工可疑上报",
            "severity": severity,
            "confidence": "1.000",
            "status": "待处理",
            "work_order_id": None,
            "trigger_details": {
                "source": "manual",
                "reporter_id": reporter_id,
                "reporter_role": self.reporter_roles.get(reporter_id, "未知员工角色"),
                "reason": description,
                "evidence_refs": evidence_refs or [],
                "reported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            "related_transaction_id": related_transaction_id,
        }
        self.reports.append(report)
        return deepcopy(report)


class FakeEventPublisher:
    def __init__(self):
        self.events = []
        self.pending_events = []
        self.fail_reason: Optional[str] = None

    def publish(self, stream_key: str, event_type: str, payload: Dict[str, Any], source_agent: str, trace_id: str) -> str:
        if self.fail_reason:
            raise RuntimeError(self.fail_reason)
        self.events.append({"stream_key": stream_key, "event_type": event_type, "payload": deepcopy(payload), "source_agent": source_agent, "trace_id": trace_id})
        return str(len(self.events))

    def enqueue_retry(
        self,
        stream_key: str,
        event_type: str,
        payload: Dict[str, Any],
        source_agent: str,
        trace_id: str,
        failure_reason: str,
    ) -> str:
        self.pending_events.append(
            {
                "stream_key": stream_key,
                "event_type": event_type,
                "payload": deepcopy(payload),
                "source_agent": source_agent,
                "trace_id": trace_id,
                "failure_reason": failure_reason,
            }
        )
        return str(len(self.pending_events))


class FakeOperationAuditGateway:
    def __init__(self):
        self.records = []
        self.fail_reason: Optional[str] = None

    def record(self, entry: Dict[str, Any]) -> None:
        if self.fail_reason:
            raise RuntimeError(self.fail_reason)
        self.records.append(deepcopy(entry))


class FakeOperationRiskGateway:
    def __init__(self, redeem_reason: Optional[str] = None, transfer_reason: Optional[str] = None):
        self.redeem_reason = redeem_reason
        self.transfer_reason = transfer_reason

    def validate_redeem(self, customer_id: int, product_id: int, shares: Any) -> Optional[str]:
        return self.redeem_reason

    def validate_transfer(self, customer_id: int, amount: Any, payee: Dict[str, Any]) -> Optional[str]:
        return self.transfer_reason
