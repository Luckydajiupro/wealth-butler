"""Operator Schema 迁移计划的纯离线测试。"""

import pytest

from scripts.migrations.operator_schema_migration import (
    APPLY_CONFIRMATION,
    build_parser,
    execute_migration,
    inspect_operator_schema,
    main,
    migration_steps,
    render_plan,
)


REQUIRED_TRANSACTION_COLUMNS = {
    "employee_id",
    "trace_id",
    "idempotency_key",
    "failure_code",
    "failure_reason",
    "updated_at",
}


class _DryRunCursor:
    def __init__(self):
        self.statements = []
        self._last_sql = ""
        self.has_idempotency_column = False

    def execute(self, sql, params=()):
        if "AS duplicates" in sql and not self.has_idempotency_column:
            raise AssertionError("dry-run referenced idempotency_key before the pending column exists")
        self._last_sql = sql
        self.statements.append((sql, params))

    def fetchone(self):
        if "information_schema.TABLES" in self._last_sql and "fin_transaction" in str(self.statements[-1][1]):
            return (1,)
        if "AS duplicates" in self._last_sql:
            return (0,)
        return (0,)

    def close(self):
        return None


class _DryRunConnection:
    def __init__(self):
        self.db_cursor = _DryRunCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.db_cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _InspectionCursor:
    def __init__(self):
        self.responses = iter(
            [
                [(1282,)],
                [],
                [("PRIMARY", 0, "id"), ("idx_customer_id", 1, "customer_id")],
                [(0,)],
            ]
        )
        self.current = []

    def execute(self, sql, params=()):
        self.current = next(self.responses)

    def fetchone(self):
        return self.current[0] if self.current else None

    def fetchall(self):
        return self.current

    def close(self):
        return None


class _InspectionConnection:
    def cursor(self):
        return _InspectionCursor()


def test_plan_contains_required_transaction_fields_and_audit_table():
    steps = migration_steps()
    transaction_columns = {
        step.name.rsplit(".", 1)[-1]
        for step in steps
        if step.name.startswith("column:fin_transaction.")
    }
    assert transaction_columns == REQUIRED_TRANSACTION_COLUMNS
    assert any(step.name == "table:biz_operation_audit" for step in steps)
    assert any("UNIQUE KEY `uk_fin_transaction_idempotency_key`" in (step.ddl_sql or "") for step in steps)
    assert any("UNIQUE KEY `uk_fin_transaction_trace_id`" in (step.ddl_sql or "") for step in steps)
    assert any("UNIQUE KEY `uk_operation_audit_event_id`" in (step.ddl_sql or "") for step in steps)


def test_every_mutating_step_has_information_schema_check():
    for step in migration_steps():
        if step.ddl_sql:
            assert "information_schema." in step.check_sql
    rendered = render_plan()
    assert rendered.startswith("-- DRY RUN ONLY")
    assert rendered.index("-- CHECK:") < rendered.index("ALTER TABLE `fin_transaction`")


def test_default_cli_mode_is_dry_run_and_apply_needs_confirmation():
    args = build_parser().parse_args([])
    assert args.apply is False
    assert args.connect_dry_run is False
    assert args.confirm == ""
    confirmed = build_parser().parse_args(["--apply", "--confirm", APPLY_CONFIRMATION])
    assert confirmed.apply is True


def test_connected_dry_run_is_mutually_exclusive_with_apply():
    connected = build_parser().parse_args(["--connect-dry-run"])
    assert connected.connect_dry_run is True
    assert connected.apply is False
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--connect-dry-run", "--apply"])
    verified = build_parser().parse_args(["--verify"])
    assert verified.verify is True
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--verify", "--apply"])


def test_apply_is_rejected_before_driver_import_without_confirmation():
    with pytest.raises(SystemExit, match=f"--confirm {APPLY_CONFIRMATION}"):
        main(["--apply"])


def test_dry_run_checks_schema_without_executing_or_committing_ddl():
    connection = _DryRunConnection()
    results = execute_migration(connection, dry_run=True)

    assert any(item["status"] == "would_apply" for item in results)
    assert any(
        item["status"] == "would_check_after_dependencies"
        and item["name"] == "precondition:fin_transaction.idempotency_key_duplicates"
        for item in results
    )
    assert any(
        item["status"] == "would_check_after_dependencies"
        and item["name"] == "column:biz_operation_audit.audit_event_id"
        for item in results
    )
    assert all(
        statement.lstrip().upper().startswith("SELECT")
        for statement, _params in connection.db_cursor.statements
    )
    assert connection.committed is False
    assert connection.rolled_back is False


def test_read_only_inspection_reports_baseline_without_requiring_target_objects():
    snapshot = inspect_operator_schema(_InspectionConnection())

    assert snapshot["fin_transaction_rows"] == 1282
    assert snapshot["target_transaction_columns"] == []
    assert snapshot["duplicate_non_null_keys"] == {
        "idempotency_key": None,
        "trace_id": None,
    }
    assert snapshot["audit_table_exists"] is False
    assert snapshot["transaction_indexes"][0] == {
        "name": "PRIMARY",
        "unique": True,
        "columns": ["id"],
    }
