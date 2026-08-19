"""MySQLTransactionGateway 的纯离线 DB-API 事务测试。"""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import json
from threading import Barrier, Lock, Thread

import pytest

from app.WealthButler.Service.operatorContracts import IdempotencyConflictError, OperationCommand
from app.WealthButler.Service.operatorMySQLTransactionGateway import MySQLTransactionGateway


class MemoryStore:
    def __init__(self):
        self.transactions = []
        self.holdings = {}
        self.customers = {10: {"id": 10}}
        self.products = {8: {"risk_level": "R2"}}
        self.assessments = {}
        self.profiles = {10: {"id": 1, "asset_allocation": {"total_assets": "2000000.00", "currency": "CNY"}}}
        self.next_transaction_id = 1


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = None
        self.lastrowid = None
        self.rowcount = 0
        self.closed = False

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self.connection.statements.append((normalized, params))
        store = self.connection.working
        if normalized.startswith("SELECT `id` FROM `base_user`"):
            self.connection.acquire_customer_lock()
            self.result = deepcopy(store.customers.get(params[0]))
        elif normalized.startswith("SELECT `id`, `asset_allocation` FROM `fin_customer_profile`"):
            self.result = deepcopy(store.profiles.get(params[0]))
        elif normalized.startswith("SELECT COALESCE(SUM(`current_value`)"):
            customer_id = params[0]
            total = sum(
                (row["current_value"] for row in store.holdings.values() if row["customer_id"] == customer_id),
                Decimal("0"),
            )
            self.result = {"holding_total": total}
        elif normalized.startswith("SELECT `id`, `employee_id`"):
            idempotency_key, trace_id = params
            self.result = next(
                (
                    deepcopy(row)
                    for row in store.transactions
                    if row["idempotency_key"] == idempotency_key or row["trace_id"] == trace_id
                ),
                None,
            )
        elif normalized.startswith("SELECT `risk_level` FROM `fin_product`"):
            self.result = deepcopy(store.products.get(params[0]))
        elif normalized.startswith("SELECT `risk_level`, `is_professional_investor`"):
            self.result = deepcopy(store.assessments.get(params[0]))
        elif normalized.startswith("SELECT `h`.`id`, `h`.`current_value`"):
            customer_id = params[0]
            self.result = [
                {
                    "id": row["id"],
                    "current_value": row["current_value"],
                    "risk_level": store.products[row["product_id"]]["risk_level"],
                }
                for row in store.holdings.values()
                if row["customer_id"] == customer_id
            ]
        elif normalized.startswith("SELECT `id`, `customer_id`, `product_id`, `shares`"):
            self.result = deepcopy(store.holdings.get((params[0], params[1])))
        elif normalized.startswith("INSERT INTO `fin_transaction`"):
            (
                customer_id,
                employee_id,
                product_id,
                transaction_type,
                amount,
                shares,
                nav,
                fee,
                counterparty_account,
                counterparty_name,
                channel,
                trace_id,
                idempotency_key,
            ) = params
            if any(
                row["idempotency_key"] == idempotency_key or row["trace_id"] == trace_id
                for row in store.transactions
            ):
                raise RuntimeError(1062, "Duplicate entry")
            transaction_id = store.next_transaction_id
            store.next_transaction_id += 1
            store.transactions.append(
                {
                    "id": transaction_id,
                    "employee_id": employee_id,
                    "customer_id": customer_id,
                    "product_id": product_id,
                    "transaction_type": transaction_type,
                    "amount": amount,
                    "shares": shares,
                    "nav": nav,
                    "fee": fee,
                    "counterparty_account": counterparty_account,
                    "counterparty_name": counterparty_name,
                    "channel": channel,
                    "status": "成交",
                    "trace_id": trace_id,
                    "idempotency_key": idempotency_key,
                }
            )
            self.lastrowid = transaction_id
            self.rowcount = 1
        elif normalized.startswith("UPDATE `fin_holdings`"):
            shares, cost, value, profit, ratio, holding_id = params
            key = next(key for key, row in store.holdings.items() if row["id"] == holding_id)
            store.holdings[key].update(
                shares=shares,
                cost_amount=cost,
                current_value=value,
                profit_loss=profit,
                profit_ratio=ratio,
            )
            self.rowcount = 1
        elif normalized.startswith("INSERT INTO `fin_holdings`"):
            customer_id, product_id, shares, cost, value, profit, ratio = params
            key = (customer_id, product_id)
            store.holdings[key] = {
                "id": max((row["id"] for row in store.holdings.values()), default=0) + 1,
                "customer_id": customer_id,
                "product_id": product_id,
                "shares": shares,
                "cost_amount": cost,
                "current_value": value,
                "profit_loss": profit,
                "profit_ratio": ratio,
            }
            self.rowcount = 1
        elif normalized.startswith("UPDATE `fin_customer_profile` SET `asset_allocation`"):
            allocation_json, profile_id = params
            profile = next(row for row in store.profiles.values() if row["id"] == profile_id)
            profile["asset_allocation"] = json.loads(allocation_json)
            self.rowcount = 1
        else:
            raise AssertionError(f"unexpected SQL: {normalized}")

    def fetchone(self):
        if isinstance(self.result, list):
            return deepcopy(self.result[0] if self.result else None)
        return deepcopy(self.result)

    def fetchall(self):
        return deepcopy(self.result if isinstance(self.result, list) else [])

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, shared, customer_lock):
        self.shared = shared
        self.customer_lock = customer_lock
        self.locked = False
        self.working = None
        self.statements = []
        self.begun = False
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def begin(self):
        self.begun = True
        self.working = deepcopy(self.shared)

    def cursor(self):
        assert self.begun
        return FakeCursor(self)

    def acquire_customer_lock(self):
        self.customer_lock.acquire()
        self.locked = True
        # InnoDB 的加锁读能看到锁等待期间已提交的数据，刷新快照模拟该语义。
        self.working = deepcopy(self.shared)

    def commit(self):
        self.shared.transactions = self.working.transactions
        self.shared.holdings = self.working.holdings
        self.shared.customers = self.working.customers
        self.shared.products = self.working.products
        self.shared.assessments = self.working.assessments
        self.shared.profiles = self.working.profiles
        self.shared.next_transaction_id = self.working.next_transaction_id
        self.committed = True
        self._release_lock()

    def rollback(self):
        self.rolled_back = True
        self._release_lock()

    def _release_lock(self):
        if self.locked:
            self.locked = False
            self.customer_lock.release()

    def close(self):
        self.closed = True


class ConnectionProvider:
    def __init__(self, store):
        self.store = store
        self.connections = []
        self.customer_lock = Lock()

    def __call__(self):
        connection = FakeConnection(self.store, self.customer_lock)
        self.connections.append(connection)
        return connection


def purchase(trace_id="trace-purchase", amount="100.00"):
    return OperationCommand(
        intent="purchase",
        params={"product_id": 8, "amount": amount, "channel": "APP"},
        trace_id=trace_id,
    )


def purchase_execution(amount="100.00"):
    return {
        "product_id": 8,
        "risk_level": "R2",
        "amount": Decimal(amount),
        "shares": Decimal(amount) / Decimal("2"),
        "nav": Decimal("2"),
    }


def test_purchase_locks_then_commits_transaction_and_new_holding():
    store = MemoryStore()
    provider = ConnectionProvider(store)
    gateway = MySQLTransactionGateway(provider)

    result = gateway.execute(3, 10, purchase(), purchase_execution())

    connection = provider.connections[0]
    assert connection.begun and connection.committed and not connection.rolled_back and connection.closed
    sql = [statement for statement, _params in connection.statements]
    assert sql[0].startswith("SELECT `id` FROM `base_user`")
    assert any("FROM `fin_holdings`" in statement and statement.endswith("FOR UPDATE") for statement in sql)
    assert sql.index(next(item for item in sql if "FROM `fin_holdings`" in item)) < sql.index(
        next(item for item in sql if item.startswith("INSERT INTO `fin_transaction`"))
    )
    assert result["transaction_id"] == 1
    assert result["idempotency_key"] == "trace-purchase"
    assert store.transactions[0]["employee_id"] == 3
    assert store.holdings[(10, 8)]["shares"] == Decimal("50.0000")
    assert store.holdings[(10, 8)]["cost_amount"] == Decimal("100.00")
    assert result["available_balance_after"] == "1999900.00"
    assert store.profiles[10]["asset_allocation"]["available_balance"] == "1999900.00"


def test_concurrent_c3_r4_purchases_are_serialized_and_only_one_crosses_cap():
    store = MemoryStore()
    store.products = {8: {"risk_level": "R4"}, 9: {"risk_level": "R2"}}
    store.assessments[10] = {
        "risk_level": "C3",
        "is_professional_investor": 0,
        "valid_until": datetime(2027, 1, 1),
    }
    store.holdings = {
        (10, 8): {
            "id": 1, "customer_id": 10, "product_id": 8, "shares": Decimal("100"),
            "cost_amount": Decimal("100000"), "current_value": Decimal("100000"),
        },
        (10, 9): {
            "id": 2, "customer_id": 10, "product_id": 9, "shares": Decimal("800"),
            "cost_amount": Decimal("800000"), "current_value": Decimal("800000"),
        },
    }
    provider = ConnectionProvider(store)
    gateway = MySQLTransactionGateway(provider)
    barrier = Barrier(3)
    results = []

    def run(trace_id):
        barrier.wait()
        try:
            results.append(gateway.execute(3, 10, purchase(trace_id, "100000"), purchase_execution("100000")))
        except Exception as exc:
            results.append(exc)

    threads = [Thread(target=run, args=(f"concurrent-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)

    assert sum(isinstance(item, dict) for item in results) == 1
    errors = [item for item in results if isinstance(item, Exception)]
    assert len(errors) == 1 and "超过总资产20%上限" in str(errors[0])
    assert len(store.transactions) == 1


def test_same_request_replays_without_second_transaction_or_holding_change():
    store = MemoryStore()
    provider = ConnectionProvider(store)
    gateway = MySQLTransactionGateway(provider)
    first = gateway.execute(3, 10, purchase(), purchase_execution())
    holding_after_first = deepcopy(store.holdings[(10, 8)])

    replay = gateway.execute(3, 10, purchase(), purchase_execution())

    assert replay["transaction_id"] == first["transaction_id"]
    assert replay["idempotent_replay"] is True
    assert len(store.transactions) == 1
    assert store.holdings[(10, 8)] == holding_after_first
    assert provider.connections[-1].committed is True


def test_same_idempotency_key_with_different_request_rolls_back_and_conflicts():
    store = MemoryStore()
    provider = ConnectionProvider(store)
    gateway = MySQLTransactionGateway(provider)
    gateway.execute(3, 10, purchase(), purchase_execution())

    with pytest.raises(IdempotencyConflictError, match="幂等键"):
        gateway.execute(3, 10, purchase(amount="120.00"), purchase_execution(amount="120.00"))

    assert len(store.transactions) == 1
    assert provider.connections[-1].rolled_back is True
    assert provider.connections[-1].committed is False


def test_redeem_with_insufficient_shares_rolls_back_everything():
    store = MemoryStore()
    store.holdings[(10, 8)] = {
        "id": 4,
        "customer_id": 10,
        "product_id": 8,
        "shares": Decimal("5"),
        "cost_amount": Decimal("10"),
        "current_value": Decimal("10"),
    }
    before = deepcopy(store.holdings)
    provider = ConnectionProvider(store)
    gateway = MySQLTransactionGateway(provider)
    command = OperationCommand(intent="redeem", params={"product_id": 8, "shares": "6"}, trace_id="trace-redeem")
    execution = {"product_id": 8, "amount": Decimal("12"), "shares": Decimal("6"), "nav": Decimal("2")}

    with pytest.raises(ValueError, match="可赎回份额不足"):
        gateway.execute(3, 10, command, execution)

    assert provider.connections[0].rolled_back is True
    assert provider.connections[0].committed is False
    assert store.holdings == before
    assert store.transactions == []


def test_redeem_uses_execution_fields_and_commits_locked_holding_change():
    store = MemoryStore()
    store.holdings[(10, 8)] = {
        "id": 4,
        "customer_id": 10,
        "product_id": 8,
        "shares": Decimal("10"),
        "cost_amount": Decimal("20"),
        "current_value": Decimal("20"),
    }
    provider = ConnectionProvider(store)
    gateway = MySQLTransactionGateway(provider)
    command = OperationCommand(intent="redeem", params={"product_id": 8, "shares": "3"}, trace_id="trace-redeem-ok")
    execution = {"product_id": 8, "amount": Decimal("6"), "shares": Decimal("3"), "nav": Decimal("2")}

    result = gateway.execute(3, 10, command, execution)

    assert result["transaction_type"] == "赎回"
    assert result["amount"] == "6.00" and result["shares"] == "3.0000"
    assert store.holdings[(10, 8)]["shares"] == Decimal("7.0000")
    assert store.holdings[(10, 8)]["cost_amount"] == Decimal("14.00")
    assert store.profiles[10]["asset_allocation"]["available_balance"] == "1999986.00"
    assert provider.connections[0].committed is True


def test_transfer_persists_counterparty_without_touching_holdings():
    store = MemoryStore()
    provider = ConnectionProvider(store)
    gateway = MySQLTransactionGateway(provider)
    command = OperationCommand(
        intent="transfer",
        params={
            "amount": "500.00",
            "counterparty_account": "62220001",
            "counterparty_name": "张三",
            "channel": "网银",
        },
        trace_id="trace-transfer",
    )

    result = gateway.execute(3, 10, command, {"amount": Decimal("500.00")})

    assert result["transaction_type"] == "转账"
    assert result["product_id"] is None and result["shares"] is None
    assert store.transactions[0]["counterparty_account"] == "62220001"
    assert store.transactions[0]["counterparty_name"] == "张三"
    assert result["available_balance_after"] == "1999500.00"
    assert store.profiles[10]["asset_allocation"]["total_assets"] == "1999500.00"
    assert store.holdings == {}
    assert not any(
        sql.startswith(("UPDATE `fin_holdings`", "INSERT INTO `fin_holdings`"))
        for sql, _params in provider.connections[0].statements
    )


def test_transfer_with_insufficient_mock_balance_rolls_back_without_transaction():
    store = MemoryStore()
    store.profiles[10]["asset_allocation"] = {
        "total_assets": "100.00",
        "available_balance": "100.00",
        "currency": "CNY",
    }
    provider = ConnectionProvider(store)
    gateway = MySQLTransactionGateway(provider)
    command = OperationCommand(
        intent="transfer",
        params={"amount": "101.00", "counterparty_account": "62220001", "counterparty_name": "张三"},
        trace_id="trace-transfer-insufficient",
    )

    with pytest.raises(ValueError, match="模拟可用资金不足"):
        gateway.execute(3, 10, command, {"amount": Decimal("101.00")})

    assert store.transactions == []
    assert store.profiles[10]["asset_allocation"]["available_balance"] == "100.00"
    assert provider.connections[0].rolled_back is True
