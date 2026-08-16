"""业务操作二次确认状态机及其可替换存储边界。"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Callable, Dict, Optional, Protocol
from uuid import uuid4

from app.WealthButler.Service.operatorContracts import OperationCommand, OperationResult


@dataclass
class PendingConfirmation:
    token: str
    employee_id: int
    customer_id: int
    command: OperationCommand
    created_at: datetime
    expires_at: datetime
    status: str = "待确认"
    result: Optional[OperationResult] = None


class ConfirmationGateway(Protocol):
    """确认记录存储契约；真实 Redis 实现必须保留原子领取与 TTL 语义。"""

    def save(self, pending: PendingConfirmation) -> None: ...

    def get(self, token: str, now: Optional[datetime] = None) -> Optional[PendingConfirmation]: ...

    def compare_and_set(
        self,
        token: str,
        expected_status: str,
        target_status: str,
        result: Optional[OperationResult] = None,
        now: Optional[datetime] = None,
    ) -> Optional[PendingConfirmation]: ...


class InMemoryConfirmationGateway:
    """阶段 3 的内存存储 Adapter，模拟 Redis 的原子状态转换。"""

    def __init__(self):
        self._records: Dict[str, PendingConfirmation] = {}
        self._lock = RLock()

    def save(self, pending: PendingConfirmation) -> None:
        with self._lock:
            self._records[pending.token] = deepcopy(pending)

    def get(self, token: str, now: Optional[datetime] = None) -> Optional[PendingConfirmation]:
        with self._lock:
            pending = self._records.get(token)
            if pending and self._is_expired_before_claim(pending, now):
                del self._records[token]
                return None
            return deepcopy(pending) if pending else None

    def compare_and_set(
        self,
        token: str,
        expected_status: str,
        target_status: str,
        result: Optional[OperationResult] = None,
        now: Optional[datetime] = None,
    ) -> Optional[PendingConfirmation]:
        with self._lock:
            pending = self._records.get(token)
            if pending and self._is_expired_before_claim(pending, now):
                del self._records[token]
                return None
            if not pending or pending.status != expected_status:
                return None
            pending.status = target_status
            pending.result = deepcopy(result) if result else None
            return deepcopy(pending)

    @staticmethod
    def _is_expired_before_claim(pending: PendingConfirmation, now: Optional[datetime]) -> bool:
        # TTL 仅约束尚未确认的指令；已领取的交易必须完成状态落库，不能在执行中被清理。
        return pending.status == "待确认" and now is not None and pending.expires_at <= now


class ConfirmationService:
    """共享申购和转账的确认状态机。"""

    def __init__(
        self,
        ttl_seconds: int = 600,
        now: Optional[Callable[[], datetime]] = None,
        confirmation_gateway: Optional[ConfirmationGateway] = None,
    ):
        self.ttl_seconds = ttl_seconds
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.confirmation_gateway = confirmation_gateway or InMemoryConfirmationGateway()

    def create(self, employee_id: int, customer_id: int, command: OperationCommand) -> PendingConfirmation:
        now = self._now()
        pending = PendingConfirmation(
            token=str(uuid4()),
            employee_id=employee_id,
            customer_id=customer_id,
            command=command,
            created_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
        )
        self.confirmation_gateway.save(pending)
        return pending

    def get_pending(self, token: str) -> Optional[PendingConfirmation]:
        return self.confirmation_gateway.get(token, self._now())

    def cancel(self, token: str, employee_id: int, customer_id: int) -> OperationResult:
        pending = self.confirmation_gateway.get(token, self._now())
        error = self._validate_context_and_expiry(pending, employee_id, customer_id)
        if error:
            return error
        if pending.status != "待确认":
            return self._state_error(token, employee_id, customer_id)
        cancelled = self.confirmation_gateway.compare_and_set(token, "待确认", "已取消", now=self._now())
        if not cancelled:
            return self._state_error(token, employee_id, customer_id)
        return OperationResult(True, "CONFIRMATION_CANCELLED", "操作已取消", metadata={"confirm_token": token})

    def confirm(
        self,
        token: str,
        employee_id: int,
        customer_id: int,
        executor: Callable[[int, int, OperationCommand], OperationResult],
    ) -> OperationResult:
        pending = self.confirmation_gateway.get(token, self._now())
        error = self._validate_context_and_expiry(pending, employee_id, customer_id)
        if error:
            return error
        if pending.status == "执行" and pending.result:
            return pending.result
        if pending.status != "待确认":
            return self._state_error(token, employee_id, customer_id)

        claimed = self.confirmation_gateway.compare_and_set(token, "待确认", "已确认", now=self._now())
        if not claimed:
            return self._state_error(token, employee_id, customer_id)

        try:
            result = executor(employee_id, customer_id, claimed.command)
        except Exception:
            # 未知异常可能发生在下游已提交写入之后，不能解除领取后自动重试而造成重复成交。
            result = OperationResult(
                False,
                "CONFIRMATION_EXECUTION_UNKNOWN",
                "确认执行状态待核验，请勿重复提交",
            )
            target_status = "执行"
        else:
            target_status = "执行" if result.success else "待确认"

        finalized = self.confirmation_gateway.compare_and_set(
            token,
            "已确认",
            target_status,
            result if target_status == "执行" else None,
            now=self._now(),
        )
        if not finalized:
            return self._state_error(token, employee_id, customer_id)
        return result

    def _validate_context_and_expiry(
        self,
        pending: Optional[PendingConfirmation],
        employee_id: int,
        customer_id: int,
    ) -> Optional[OperationResult]:
        if not pending:
            return OperationResult(False, "CONFIRMATION_NOT_FOUND", "确认令牌不存在或已失效")
        if pending.employee_id != employee_id or pending.customer_id != customer_id:
            return OperationResult(False, "CONFIRMATION_CONTEXT_MISMATCH", "确认人与原操作上下文不匹配")
        if pending.status == "待确认" and pending.expires_at <= self._now():
            return OperationResult(False, "CONFIRMATION_EXPIRED", "确认令牌已过期，请重新发起操作")
        return None

    def _state_error(self, token: str, employee_id: int, customer_id: int) -> OperationResult:
        current = self.confirmation_gateway.get(token, self._now())
        context_error = self._validate_context_and_expiry(current, employee_id, customer_id)
        if context_error:
            return context_error
        if current.status == "执行" and current.result:
            return current.result
        if not current:
            return OperationResult(False, "CONFIRMATION_NOT_FOUND", "确认令牌不存在或已失效")
        if current.status == "已确认":
            return OperationResult(False, "CONFIRMATION_IN_PROGRESS", "确认操作正在执行，请稍后查询结果")
        return OperationResult(False, "CONFIRMATION_INVALID_STATE", f"确认令牌当前状态为{current.status}")
