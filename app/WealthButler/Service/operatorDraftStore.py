"""会话级业务操作草稿，隔离多轮参数收集。"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass
class OperationDraft:
    intent: str
    params: Dict[str, Any]
    expires_at: datetime


class OperatorDraftStore:
    """进程内短期草稿；身份边界始终包含员工和客户，不信任会话名本身。"""

    def __init__(self, ttl_seconds: int = 600, now: Optional[Callable[[], datetime]] = None):
        if ttl_seconds <= 0:
            raise ValueError("操作草稿 TTL 必须为正整数")
        self.ttl_seconds = ttl_seconds
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._records: Dict[Tuple[int, int, str], OperationDraft] = {}
        self._lock = RLock()

    def get(self, employee_id: int, customer_id: int, session_key: str) -> Optional[OperationDraft]:
        key = self._key(employee_id, customer_id, session_key)
        with self._lock:
            draft = self._records.get(key)
            if draft and draft.expires_at <= self._now():
                self._records.pop(key, None)
                return None
            return deepcopy(draft) if draft else None

    def save(self, employee_id: int, customer_id: int, session_key: str, intent: str, params: Dict[str, Any]) -> None:
        key = self._key(employee_id, customer_id, session_key)
        with self._lock:
            self._records[key] = OperationDraft(
                intent=intent,
                params=deepcopy(params),
                expires_at=self._now() + timedelta(seconds=self.ttl_seconds),
            )

    def clear(self, employee_id: int, customer_id: int, session_key: str) -> None:
        with self._lock:
            self._records.pop(self._key(employee_id, customer_id, session_key), None)

    @staticmethod
    def _key(employee_id: int, customer_id: int, session_key: str) -> Tuple[int, int, str]:
        if employee_id <= 0 or customer_id <= 0:
            raise ValueError("操作草稿身份上下文不合法")
        normalized = str(session_key or "default").strip()[:128] or "default"
        return employee_id, customer_id, normalized
