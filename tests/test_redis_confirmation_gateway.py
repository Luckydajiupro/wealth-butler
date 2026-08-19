"""Redis 二次确认 Gateway 的离线原子语义测试。"""

from datetime import datetime, timedelta, timezone
from threading import Lock, Thread

from app.WealthButler.Service.confirmationService import PendingConfirmation
from app.WealthButler.Service.operatorContracts import OperationCommand, OperationResult
from app.WealthButler.Service.redisConfirmationGateway import RedisConfirmationGateway


class FakeAtomicRedis:
    """仅实现 Gateway 使用的 Redis 命令，eval 在锁内模拟 Lua 原子执行。"""

    def __init__(self):
        self.records = {}
        self.ttls = {}
        self.lock = Lock()

    def eval(self, script, key_count, key, *args):
        assert key_count == 1
        with self.lock:
            if "EXISTS', KEYS[1]) == 1" in script:
                if key in self.records:
                    return 0
                status, payload, ttl = args
                self.records[key] = {"status": status, "payload": payload}
                self.ttls[key] = int(ttl)
                return 1

            expected, target, payload, ttl = args
            record = self.records.get(key)
            if record is None or record["status"] != expected:
                return None
            record.update(status=target, payload=payload)
            self.ttls[key] = int(ttl)
            return payload

    def hget(self, key, field):
        record = self.records.get(key)
        return record.get(field) if record else None

    def delete(self, key):
        self.records.pop(key, None)
        self.ttls.pop(key, None)


def _pending(now: datetime) -> PendingConfirmation:
    return PendingConfirmation(
        token="token-1",
        employee_id=8,
        customer_id=1001,
        command=OperationCommand(
            intent="purchase",
            params={"product_id": 1, "amount": "12000.00"},
            confidence=0.96,
            trace_id="trace-1",
        ),
        created_at=now,
        expires_at=now + timedelta(minutes=10),
    )


def test_round_trip_preserves_confirmation_context():
    now = datetime.now(timezone.utc)
    redis = FakeAtomicRedis()
    gateway = RedisConfirmationGateway(redis)

    gateway.save(_pending(now))
    restored = gateway.get("token-1", now)

    assert restored is not None
    assert restored.employee_id == 8
    assert restored.customer_id == 1001
    assert restored.command.params["amount"] == "12000.00"
    assert redis.ttls["operator:confirmation:token-1"] <= 600


def test_save_refuses_to_overwrite_existing_token():
    now = datetime.now(timezone.utc)
    redis = FakeAtomicRedis()
    gateway = RedisConfirmationGateway(redis)
    pending = _pending(now)
    gateway.save(pending)

    try:
        gateway.save(pending)
    except RuntimeError as exc:
        assert "拒绝覆盖" in str(exc)
    else:
        raise AssertionError("重复 token 必须被拒绝")


def test_compare_and_set_allows_only_one_concurrent_claim():
    now = datetime.now(timezone.utc)
    redis = FakeAtomicRedis()
    gateway = RedisConfirmationGateway(redis)
    gateway.save(_pending(now))
    claimed = []

    def claim():
        claimed.append(
            gateway.compare_and_set("token-1", "待确认", "已确认", now=now)
        )

    threads = [Thread(target=claim), Thread(target=claim)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(item is not None for item in claimed) == 1


def test_completed_result_is_retained_for_idempotent_replay():
    now = datetime.now(timezone.utc)
    redis = FakeAtomicRedis()
    gateway = RedisConfirmationGateway(redis, completed_ttl_seconds=7200)
    gateway.save(_pending(now))
    assert gateway.compare_and_set("token-1", "待确认", "已确认", now=now)

    result = OperationResult(
        True,
        "TRANSACTION_COMPLETED",
        "成交",
        data={"transaction_id": 99},
    )
    completed = gateway.compare_and_set(
        "token-1", "已确认", "执行", result=result, now=now
    )

    assert completed is not None
    assert completed.result is not None
    assert completed.result.data["transaction_id"] == 99
    assert redis.ttls["operator:confirmation:token-1"] == 7200


def test_expired_pending_record_is_deleted():
    now = datetime.now(timezone.utc)
    redis = FakeAtomicRedis()
    gateway = RedisConfirmationGateway(redis)
    pending = _pending(now - timedelta(minutes=11))
    gateway.save(pending)

    assert gateway.get("token-1", now) is None
    assert "operator:confirmation:token-1" not in redis.records
