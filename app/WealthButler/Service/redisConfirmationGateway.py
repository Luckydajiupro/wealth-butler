"""Operator 二次确认记录的 Redis 原子存储实现。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from typing import Any, Optional

from app.WealthButler.Service.confirmationService import PendingConfirmation
from app.WealthButler.Service.operatorContracts import OperationCommand, OperationResult


_SAVE_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 1 then
    return 0
end
redis.call('HSET', KEYS[1], 'status', ARGV[1], 'payload', ARGV[2])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
return 1
"""

_COMPARE_AND_SET_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then
    return nil
end
if redis.call('HGET', KEYS[1], 'status') ~= ARGV[1] then
    return nil
end
redis.call('HSET', KEYS[1], 'status', ARGV[2], 'payload', ARGV[3])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
return ARGV[3]
"""


class RedisConfirmationGateway:
    """以 Redis Hash + Lua CAS 保存确认状态。

    Lua 将状态比较、状态更新、完整载荷更新和 TTL 刷新合并为一次原子操作，
    从而保证并发确认时只有一个请求能领取 ``待确认`` 指令。
    """

    KEY_PREFIX = "operator:confirmation:"

    def __init__(
        self,
        redis_client: Any = None,
        *,
        completed_ttl_seconds: int = 86400,
        claim_ttl_seconds: int = 300,
    ):
        if completed_ttl_seconds <= 0 or claim_ttl_seconds <= 0:
            raise ValueError("Redis 确认记录 TTL 必须为正整数")
        if redis_client is None:
            from app.Base.Client.redisClient import RedisClient

            redis_client = RedisClient().client
        self.redis = redis_client
        self.completed_ttl_seconds = completed_ttl_seconds
        self.claim_ttl_seconds = claim_ttl_seconds

    def save(self, pending: PendingConfirmation) -> None:
        ttl = self._remaining_ttl(pending)
        saved = self.redis.eval(
            _SAVE_SCRIPT,
            1,
            self._key(pending.token),
            pending.status,
            self._serialize(pending),
            ttl,
        )
        if int(saved or 0) != 1:
            raise RuntimeError("确认令牌已存在，拒绝覆盖")

    def get(
        self,
        token: str,
        now: Optional[datetime] = None,
    ) -> Optional[PendingConfirmation]:
        raw = self.redis.hget(self._key(token), "payload")
        if raw is None:
            return None
        pending = self._deserialize(raw)
        effective_now = now or datetime.now(timezone.utc)
        if pending.status == "待确认" and pending.expires_at <= effective_now:
            self.redis.delete(self._key(token))
            return None
        return pending

    def compare_and_set(
        self,
        token: str,
        expected_status: str,
        target_status: str,
        result: Optional[OperationResult] = None,
        now: Optional[datetime] = None,
    ) -> Optional[PendingConfirmation]:
        current = self.get(token, now)
        if current is None:
            return None
        current.status = target_status
        current.result = result
        ttl = self._target_ttl(current, target_status, now)
        raw = self.redis.eval(
            _COMPARE_AND_SET_SCRIPT,
            1,
            self._key(token),
            expected_status,
            target_status,
            self._serialize(current),
            ttl,
        )
        return self._deserialize(raw) if raw is not None else None

    def _target_ttl(
        self,
        pending: PendingConfirmation,
        target_status: str,
        now: Optional[datetime],
    ) -> int:
        if target_status in {"执行", "已取消"}:
            return self.completed_ttl_seconds
        remaining = self._remaining_ttl(pending, now)
        if target_status == "已确认":
            return max(remaining, self.claim_ttl_seconds)
        return remaining

    @staticmethod
    def _remaining_ttl(
        pending: PendingConfirmation,
        now: Optional[datetime] = None,
    ) -> int:
        effective_now = now or datetime.now(timezone.utc)
        return max(1, int((pending.expires_at - effective_now).total_seconds()))

    @classmethod
    def _key(cls, token: str) -> str:
        if not token or not token.strip():
            raise ValueError("确认令牌不能为空")
        return f"{cls.KEY_PREFIX}{token.strip()}"

    @staticmethod
    def _serialize(pending: PendingConfirmation) -> str:
        payload = {
            "token": pending.token,
            "employee_id": pending.employee_id,
            "customer_id": pending.customer_id,
            "command": {
                "intent": pending.command.intent,
                "params": pending.command.params,
                "confidence": pending.command.confidence,
                "trace_id": pending.command.trace_id,
            },
            "created_at": pending.created_at.isoformat(),
            "expires_at": pending.expires_at.isoformat(),
            "status": pending.status,
            "result": pending.result.to_dict() if pending.result else None,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=_json_default)

    @staticmethod
    def _deserialize(raw: Any) -> PendingConfirmation:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
        command_data = payload["command"]
        result_data = payload.get("result")
        result = OperationResult(**result_data) if result_data else None
        return PendingConfirmation(
            token=payload["token"],
            employee_id=int(payload["employee_id"]),
            customer_id=int(payload["customer_id"]),
            command=OperationCommand(
                intent=command_data["intent"],
                params=command_data.get("params") or {},
                confidence=float(command_data.get("confidence", 1.0)),
                trace_id=command_data["trace_id"],
            ),
            created_at=datetime.fromisoformat(payload["created_at"]),
            expires_at=datetime.fromisoformat(payload["expires_at"]),
            status=payload["status"],
            result=result,
        )


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"不支持的确认记录字段类型: {type(value).__name__}")


__all__ = ["RedisConfirmationGateway"]
