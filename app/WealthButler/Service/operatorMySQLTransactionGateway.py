"""Operator 交易与持仓的 MySQL 事务 Adapter。

本模块不导入项目全局 MySQL Client。调用方必须显式注入一个
``connection_provider``，每次调用返回支持 DB-API 的新连接。连接的 cursor
必须返回 mapping row（例如 PyMySQL ``DictCursor``）。

事件发布不属于本 Adapter；``OperationService`` 只在本事务提交后发布事件。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import os
from typing import Any, Callable, Dict, Mapping, Optional

from app.WealthButler.Service.operatorContracts import IdempotencyConflictError, OperationCommand


_INTENT_TO_TRANSACTION_TYPE = {
    "purchase": "申购",
    "redeem": "赎回",
    "transfer": "转账",
}


def _decimal(value: Any, field_name: str, *, positive: bool = False) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}必须是有效 Decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        qualifier = "大于0的" if positive else "有限"
        raise ValueError(f"{field_name}必须是{qualifier} Decimal")
    return result


def _row_value(row: Mapping[str, Any], key: str) -> Any:
    if not isinstance(row, Mapping):
        raise TypeError("MySQLTransactionGateway 需要 mapping cursor")
    return row.get(key)


class MySQLTransactionGateway:
    """在单个 MySQL 事务中写入交易并变更持仓。"""

    POSITION_LIMITS = {("C3", "R4"): Decimal("0.20"), ("C4", "R5"): Decimal("0.10")}

    def __init__(self, connection_provider: Callable[[], Any]):
        if not callable(connection_provider):
            raise TypeError("connection_provider 必须可调用")
        self._connection_provider = connection_provider

    def get_available_balance(self, customer_id: int) -> Optional[Decimal]:
        """Read the same simulated cash source used by transaction execution."""
        connection = self._connection_provider()
        if connection is None:
            raise RuntimeError("MySQL connection provider returned None")
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT `asset_allocation` FROM `fin_customer_profile` "
                "WHERE `customer_id` = %s LIMIT 1",
                (customer_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            raw = _row_value(row, "asset_allocation")
            if isinstance(raw, str):
                try:
                    allocation = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError("客户资产配置不是有效JSON") from exc
            elif isinstance(raw, Mapping):
                allocation = dict(raw)
            else:
                allocation = {}
            raw_balance = allocation.get("available_balance", allocation.get("cash_reserve"))
            if raw_balance is not None:
                return _decimal(raw_balance, "模拟可用资金")
            raw_total_assets = allocation.get("total_assets")
            if raw_total_assets is not None:
                cursor.execute(
                    "SELECT COALESCE(SUM(`current_value`), 0) AS `holding_total` FROM `fin_holdings` "
                    "WHERE `customer_id` = %s AND `deleted_at` IS NULL",
                    (customer_id,),
                )
                holding_row = cursor.fetchone()
                holding_total = _decimal(_row_value(holding_row, "holding_total") if holding_row else "0", "持仓总市值")
                return max(Decimal("0"), _decimal(raw_total_assets, "客户总资产") - holding_total)
            if os.getenv("WEALTH_BUTLER_SIMULATED_COMPLIANCE_ENABLED", "false").lower() == "true":
                return _decimal(os.getenv("WEALTH_BUTLER_SIMULATED_INITIAL_CASH", "100000.00"), "测试模拟现金", positive=True)
            return None
        finally:
            if cursor is not None:
                cursor.close()
            connection.close()

    def execute(
        self,
        employee_id: int,
        customer_id: int,
        command: OperationCommand,
        execution: Dict[str, Any],
    ) -> Dict[str, Any]:
        request = self._normalize_request(employee_id, customer_id, command, execution)
        connection = self._connection_provider()
        if connection is None:
            raise RuntimeError("MySQL connection provider returned None")
        cursor = None
        try:
            connection.begin()
            cursor = connection.cursor()
            # 同一客户的交易先锁客户主记录，确保不同产品的并发申购也按顺序复核总仓位。
            self._lock_customer(cursor, customer_id)
            previous = self._find_existing(cursor, request["idempotency_key"], request["trace_id"], for_update=True)
            if previous:
                replay = self._replay_or_conflict(previous, request)
                connection.commit()
                return replay

            cash_account = self._lock_and_calculate_cash(cursor, request)
            holding_before = None
            holding_after = None
            if request["intent"] in {"purchase", "redeem"}:
                if request["intent"] == "purchase":
                    self._validate_position_limit(cursor, request)
                holding_before = self._lock_holding(cursor, customer_id, int(request["product_id"]))
                holding_after = self._calculate_holding(request, holding_before)

            transaction_id = self._insert_transaction(cursor, request)
            if holding_after is not None:
                self._persist_holding(cursor, holding_before, holding_after)
            self._persist_cash_allocation(cursor, cash_account)
            connection.commit()
            result = self._transaction_result(transaction_id, request, holding_after, idempotent_replay=False)
            result["available_balance_after"] = f"{cash_account['available_balance']:.2f}"
            return result
        except Exception as exc:
            connection.rollback()
            if self._is_duplicate_key_error(exc):
                return self._load_after_duplicate(request)
            raise
        finally:
            if cursor is not None:
                cursor.close()
            connection.close()

    def _load_after_duplicate(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """并发插入被唯一索引拒绝后，用新连接读取已提交结果。"""
        connection = self._connection_provider()
        if connection is None:
            raise RuntimeError("MySQL connection provider returned None during idempotent replay")
        cursor = None
        try:
            connection.begin()
            cursor = connection.cursor()
            previous = self._find_existing(cursor, request["idempotency_key"], request["trace_id"], for_update=False)
            if not previous:
                raise RuntimeError("幂等唯一索引冲突，但未查到原交易")
            replay = self._replay_or_conflict(previous, request)
            connection.commit()
            return replay
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor is not None:
                cursor.close()
            connection.close()

    @staticmethod
    def _normalize_request(
        employee_id: int,
        customer_id: int,
        command: OperationCommand,
        execution: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(employee_id, int) or isinstance(employee_id, bool) or employee_id <= 0:
            raise ValueError("employee_id 必须为正整数")
        if not isinstance(customer_id, int) or isinstance(customer_id, bool) or customer_id <= 0:
            raise ValueError("customer_id 必须为正整数")
        if command.intent not in _INTENT_TO_TRANSACTION_TYPE:
            raise ValueError("不支持的交易意图")
        trace_id = str(command.trace_id or "").strip()
        if not trace_id or len(trace_id) > 64:
            raise ValueError("trace_id 必须为1-64字符")
        idempotency_key = str(execution.get("idempotency_key") or trace_id).strip()
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("idempotency_key 必须为1-128字符")

        amount = _decimal(execution.get("amount"), "交易金额", positive=True).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        request: Dict[str, Any] = {
            "employee_id": employee_id,
            "customer_id": customer_id,
            "intent": command.intent,
            "transaction_type": _INTENT_TO_TRANSACTION_TYPE[command.intent],
            "amount": amount,
            "product_id": None,
            "shares": None,
            "nav": None,
            "fee": _decimal(execution.get("fee", "0"), "手续费").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "counterparty_account": None,
            "counterparty_name": None,
            "channel": command.params.get("channel"),
            "trace_id": trace_id,
            "idempotency_key": idempotency_key,
        }
        if request["fee"] < 0:
            raise ValueError("手续费不能为负数")
        if command.intent in {"purchase", "redeem"}:
            product_id = execution.get("product_id")
            if not isinstance(product_id, int) or isinstance(product_id, bool) or product_id <= 0:
                raise ValueError("product_id 必须为正整数")
            request.update(
                product_id=product_id,
                shares=_decimal(execution.get("shares"), "交易份额", positive=True).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                ),
                nav=_decimal(execution.get("nav"), "交易净值", positive=True).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                ),
            )
        else:
            account = command.params.get("counterparty_account")
            name = command.params.get("counterparty_name")
            if not isinstance(account, str) or not account.strip():
                raise ValueError("转账对手方账号不能为空")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("转账对手方名称不能为空")
            request["counterparty_account"] = account.strip()
            request["counterparty_name"] = name.strip()
        return request

    @staticmethod
    def _lock_customer(cursor: Any, customer_id: int) -> None:
        cursor.execute(
            "SELECT `id` FROM `base_user` WHERE `id` = %s AND `user_type` = 'CUSTOMER' "
            "AND `status` = 'active' AND `deleted_at` IS NULL FOR UPDATE",
            (customer_id,),
        )
        row = cursor.fetchone()
        if not row or _row_value(row, "id") != customer_id:
            raise ValueError("客户不存在、未启用或已删除")

    @staticmethod
    def _lock_and_calculate_cash(cursor: Any, request: Dict[str, Any]) -> Dict[str, Any]:
        """在画像 JSON 内维护模拟可用资金，与交易和持仓处于同一事务。"""
        cursor.execute(
            "SELECT `id`, `asset_allocation` FROM `fin_customer_profile` "
            "WHERE `customer_id` = %s LIMIT 1 FOR UPDATE",
            (request["customer_id"],),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("客户缺少资产画像，无法初始化模拟可用资金")
        raw = _row_value(row, "asset_allocation")
        if isinstance(raw, str):
            try:
                allocation = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("客户资产配置不是有效JSON") from exc
        elif isinstance(raw, Mapping):
            allocation = dict(raw)
        else:
            allocation = {}

        raw_total_assets = allocation.get("total_assets")
        raw_balance = allocation.get("available_balance", allocation.get("cash_reserve"))
        if raw_total_assets is None or raw_balance is None:
            cursor.execute(
                "SELECT COALESCE(SUM(`current_value`), 0) AS `holding_total` FROM `fin_holdings` "
                "WHERE `customer_id` = %s AND `deleted_at` IS NULL",
                (request["customer_id"],),
            )
            holding_row = cursor.fetchone()
            holding_total = _decimal(_row_value(holding_row, "holding_total") if holding_row else "0", "持仓总市值")
            if raw_total_assets is not None:
                total_assets = _decimal(raw_total_assets, "客户总资产")
                available = max(Decimal("0"), total_assets - holding_total) if raw_balance is None else _decimal(raw_balance, "模拟可用资金")
            elif raw_balance is not None:
                available = _decimal(raw_balance, "模拟可用资金")
                total_assets = holding_total + available
            else:
                if os.getenv("WEALTH_BUTLER_SIMULATED_COMPLIANCE_ENABLED", "false").lower() != "true":
                    raise ValueError("客户资产画像缺少总资产或可用资金")
                # 测试账户历史种子只有配置比例；首次模拟成交时以持仓市值加测试现金初始化。
                available = _decimal(os.getenv("WEALTH_BUTLER_SIMULATED_INITIAL_CASH", "100000.00"), "测试模拟现金", positive=True)
                total_assets = holding_total + available
        else:
            total_assets = _decimal(raw_total_assets, "客户总资产")
            available = _decimal(raw_balance, "模拟可用资金")
        if total_assets < 0:
            raise ValueError("客户总资产不能为负数")
        if available < 0:
            raise ValueError("模拟可用资金不能为负数")

        fee = request["fee"]
        if request["intent"] in {"purchase", "transfer"}:
            required = request["amount"] + fee
            if available < required:
                raise ValueError("模拟可用资金不足")
            available -= required
        else:
            available += request["amount"] - fee

        if request["intent"] == "transfer":
            total_assets -= request["amount"] + fee
            if total_assets < 0:
                raise ValueError("转账后客户总资产不能为负数")
        allocation["available_balance"] = f"{available:.2f}"
        allocation["cash_reserve"] = f"{available:.2f}"
        allocation["total_assets"] = f"{total_assets:.2f}"
        allocation["currency"] = allocation.get("currency") or "CNY"
        return {
            "profile_id": int(_row_value(row, "id")),
            "allocation": allocation,
            "available_balance": available,
        }

    @staticmethod
    def _persist_cash_allocation(cursor: Any, cash_account: Dict[str, Any]) -> None:
        cursor.execute(
            "UPDATE `fin_customer_profile` SET `asset_allocation` = %s, "
            "`updated_reason` = '事件', `updated_at` = CURRENT_TIMESTAMP WHERE `id` = %s",
            (json.dumps(cash_account["allocation"], ensure_ascii=False), cash_account["profile_id"]),
        )
        if getattr(cursor, "rowcount", 1) != 1:
            raise RuntimeError("模拟资金账户更新未命中客户画像")

    @classmethod
    def _validate_position_limit(cls, cursor: Any, request: Dict[str, Any]) -> None:
        cursor.execute(
            "SELECT `risk_level` FROM `fin_product` WHERE `id` = %s AND `status` = '在售' LIMIT 1",
            (request["product_id"],),
        )
        product = cursor.fetchone()
        product_level = _row_value(product, "risk_level") if product else None
        if product_level not in {"R4", "R5"}:
            return

        cursor.execute(
            "SELECT `risk_level`, `is_professional_investor`, `valid_until` "
            "FROM `fin_risk_assessment` WHERE `customer_id` = %s AND `valid_until` > NOW() "
            "ORDER BY `assessment_time` DESC, `id` DESC LIMIT 1 FOR UPDATE",
            (request["customer_id"],),
        )
        assessment = cursor.fetchone()
        if not assessment:
            raise ValueError("客户缺少风险评估，无法完成事务内仓位复核")
        if _row_value(assessment, "is_professional_investor") in (True, 1):
            return
        customer_level = _row_value(assessment, "risk_level")
        limit = cls.POSITION_LIMITS.get((customer_level, product_level))
        if limit is None:
            return

        cursor.execute(
            "SELECT `h`.`id`, `h`.`current_value`, `p`.`risk_level` FROM `fin_holdings` AS `h` "
            "JOIN `fin_product` AS `p` ON `p`.`id` = `h`.`product_id` "
            "WHERE `h`.`customer_id` = %s AND `h`.`deleted_at` IS NULL FOR UPDATE",
            (request["customer_id"],),
        )
        rows = cursor.fetchall() or []
        total = Decimal("0")
        risk_total = Decimal("0")
        for row in rows:
            value = _decimal(_row_value(row, "current_value"), "持仓市值")
            if value < 0:
                raise ValueError("持仓市值不能为负数")
            total += value
            if _row_value(row, "risk_level") == product_level:
                risk_total += value
        projected_total = total + request["amount"]
        if projected_total <= 0 or (risk_total + request["amount"]) / projected_total > limit:
            raise ValueError(f"申购后{product_level}持仓将超过总资产{int(limit * 100)}%上限")

    @staticmethod
    def _find_existing(cursor: Any, idempotency_key: str, trace_id: str, *, for_update: bool) -> Optional[Mapping[str, Any]]:
        suffix = " FOR UPDATE" if for_update else ""
        cursor.execute(
            "SELECT `id`, `employee_id`, `customer_id`, `product_id`, `transaction_type`, "
            "`amount`, `shares`, `nav`, `fee`, `counterparty_account`, `counterparty_name`, "
            "`channel`, `status`, `trace_id`, `idempotency_key` FROM `fin_transaction` "
            "WHERE `idempotency_key` = %s OR `trace_id` = %s ORDER BY `id` ASC LIMIT 1" + suffix,
            (idempotency_key, trace_id),
        )
        return cursor.fetchone()

    @staticmethod
    def _lock_holding(cursor: Any, customer_id: int, product_id: int) -> Optional[Mapping[str, Any]]:
        cursor.execute(
            "SELECT `id`, `customer_id`, `product_id`, `shares`, `cost_amount`, `current_value` "
            "FROM `fin_holdings` WHERE `customer_id` = %s AND `product_id` = %s FOR UPDATE",
            (customer_id, product_id),
        )
        return cursor.fetchone()

    @staticmethod
    def _calculate_holding(request: Dict[str, Any], before: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        before_shares = _decimal(_row_value(before, "shares") if before else "0", "持仓份额")
        before_cost = _decimal(_row_value(before, "cost_amount") if before else "0", "持仓成本")
        before_value = _decimal(_row_value(before, "current_value") if before else "0", "持仓市值")
        shares = request["shares"]
        amount = request["amount"]
        if request["intent"] == "purchase":
            after_shares = before_shares + shares
            after_cost = before_cost + amount + request["fee"]
            after_value = before_value + amount
        else:
            if not before or shares > before_shares:
                raise ValueError("可赎回份额不足")
            after_shares = before_shares - shares
            ratio = after_shares / before_shares
            after_cost = (before_cost * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            after_value = max(Decimal("0"), before_value - amount)
        profit_loss = after_value - after_cost
        profit_ratio = Decimal("0") if after_cost == 0 else (profit_loss / after_cost).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        return {
            "id": _row_value(before, "id") if before else None,
            "customer_id": request["customer_id"],
            "product_id": request["product_id"],
            "shares": after_shares.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "cost_amount": after_cost,
            "current_value": after_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "profit_loss": profit_loss.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "profit_ratio": profit_ratio,
        }

    @staticmethod
    def _insert_transaction(cursor: Any, request: Dict[str, Any]) -> int:
        cursor.execute(
            "INSERT INTO `fin_transaction` "
            "(`customer_id`, `employee_id`, `product_id`, `transaction_type`, `amount`, `shares`, "
            "`nav`, `fee`, `counterparty_account`, `counterparty_name`, `channel`, `status`, "
            "`trace_id`, `idempotency_key`, `transaction_time`) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '成交', %s, %s, NOW())",
            (
                request["customer_id"], request["employee_id"], request["product_id"],
                request["transaction_type"], request["amount"], request["shares"], request["nav"],
                request["fee"], request["counterparty_account"], request["counterparty_name"],
                request["channel"], request["trace_id"], request["idempotency_key"],
            ),
        )
        transaction_id = getattr(cursor, "lastrowid", None)
        if not transaction_id:
            raise RuntimeError("交易插入后未返回主键")
        return int(transaction_id)

    @staticmethod
    def _persist_holding(cursor: Any, before: Optional[Mapping[str, Any]], after: Dict[str, Any]) -> None:
        values = (
            after["shares"], after["cost_amount"], after["current_value"],
            after["profit_loss"], after["profit_ratio"],
        )
        if before:
            cursor.execute(
                "UPDATE `fin_holdings` SET `shares` = %s, `cost_amount` = %s, `current_value` = %s, "
                "`profit_loss` = %s, `profit_ratio` = %s, `updated_at` = CURRENT_TIMESTAMP WHERE `id` = %s",
                (*values, after["id"]),
            )
            if getattr(cursor, "rowcount", 1) != 1:
                raise RuntimeError("持仓更新未命中唯一记录")
        else:
            cursor.execute(
                "INSERT INTO `fin_holdings` (`customer_id`, `product_id`, `shares`, `cost_amount`, "
                "`current_value`, `profit_loss`, `profit_ratio`) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (after["customer_id"], after["product_id"], *values),
            )

    @classmethod
    def _replay_or_conflict(cls, previous: Mapping[str, Any], request: Dict[str, Any]) -> Dict[str, Any]:
        comparable = {
            "employee_id": request["employee_id"],
            "customer_id": request["customer_id"],
            "product_id": request["product_id"],
            "transaction_type": request["transaction_type"],
            "amount": request["amount"],
            "shares": request["shares"],
            "nav": request["nav"],
            "fee": request["fee"],
            "counterparty_account": request["counterparty_account"],
            "counterparty_name": request["counterparty_name"],
            "channel": request["channel"],
        }
        for field, expected in comparable.items():
            actual = _row_value(previous, field)
            if field in {"amount", "shares", "nav", "fee"}:
                actual = None if actual is None else _decimal(actual, field)
                expected = None if expected is None else _decimal(expected, field)
            if actual != expected:
                raise IdempotencyConflictError("幂等键已用于不同请求")
        return cls._transaction_result(int(_row_value(previous, "id")), request, None, idempotent_replay=True)

    @staticmethod
    def _transaction_result(
        transaction_id: int,
        request: Dict[str, Any],
        holding_after: Optional[Dict[str, Any]],
        *,
        idempotent_replay: bool,
    ) -> Dict[str, Any]:
        result = {
            "transaction_id": transaction_id,
            "customer_id": request["customer_id"],
            "product_id": request["product_id"],
            "amount": f"{request['amount']:.2f}",
            "shares": None if request["shares"] is None else f"{request['shares']:.4f}",
            "transaction_type": request["transaction_type"],
            "status": "成交",
            "employee_id": request["employee_id"],
            "trace_id": request["trace_id"],
            "idempotency_key": request["idempotency_key"],
            "holding_after": holding_after,
        }
        if idempotent_replay:
            result["idempotent_replay"] = True
        return result

    @staticmethod
    def _is_duplicate_key_error(exc: Exception) -> bool:
        error_code = exc.args[0] if getattr(exc, "args", ()) else None
        return error_code == 1062 or "duplicate" in str(exc).casefold()


__all__ = ["MySQLTransactionGateway"]
