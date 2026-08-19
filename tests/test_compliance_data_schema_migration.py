"""合规数据表迁移的纯离线安全测试。"""

import pytest

from scripts.migrations.compliance_data_schema_migration import (
    APPLY_CONFIRMATION,
    TABLE_SPECS,
    _validate_existing,
    build_parser,
    execute_migration,
    render_plan,
)


class _AbsentTablesCursor:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        assert sql.lstrip().upper().startswith("SELECT")

    def fetchone(self):
        return (0,)

    def close(self):
        return None


class _DryRunConnection:
    def __init__(self):
        self.db_cursor = _AbsentTablesCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.db_cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_default_plan_is_offline_and_apply_requires_explicit_confirmation():
    args = build_parser().parse_args([])
    assert not args.apply and not args.connect_dry_run and not args.verify
    assert render_plan().startswith("-- DRY RUN ONLY")
    with pytest.raises(SystemExit, match=APPLY_CONFIRMATION):
        from scripts.migrations.compliance_data_schema_migration import main

        main(["--apply"])


def test_connected_dry_run_checks_information_schema_without_ddl_or_commit():
    connection = _DryRunConnection()
    result = execute_migration(connection, dry_run=True)

    assert result == [
        {"table": "biz_compliance_evidence", "status": "would_create"},
        {"table": "fin_verified_payee", "status": "would_create"},
    ]
    assert connection.committed is False and connection.rolled_back is False
    assert all("information_schema.TABLES" in sql for sql, _params in connection.db_cursor.statements)


def test_existing_incompatible_table_fails_closed_instead_of_altering_it():
    payee_spec = next(spec for spec in TABLE_SPECS if spec.name == "fin_verified_payee")
    details = {
        "columns": sorted(payee_spec.required_columns | {"account_number"}),
        "indexes": sorted(payee_spec.required_indexes),
        "rows": 3,
    }
    with pytest.raises(RuntimeError, match="forbidden_columns=.*account_number"):
        _validate_existing(payee_spec, details)


def test_migration_contract_uses_artifact_sha256_and_no_plaintext_payee_columns():
    evidence = next(spec for spec in TABLE_SPECS if spec.name == "biz_compliance_evidence")
    payee = next(spec for spec in TABLE_SPECS if spec.name == "fin_verified_payee")
    assert "artifact_sha256" in evidence.required_columns
    assert "sha256" not in evidence.required_columns
    assert "payee_name_hmac" in payee.required_columns
    assert "payee_name`" not in payee.create_sql
