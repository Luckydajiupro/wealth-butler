from scripts.migrations.phase4_seed_prerequisite_migration import (
    APPLY_CONFIRMATION,
    COLUMNS,
    INDEXES,
    render_plan,
)


def test_migration_offline_plan_lists_every_step():
    plan = render_plan()
    assert "no database connection opened" in plan
    assert all(f"{step.table}.{step.column}" in plan for step in COLUMNS)
    assert all(f"{step.table}.{step.name}" in plan for step in INDEXES)
    assert APPLY_CONFIRMATION == "APPLY_PHASE4_SEED_PREREQUISITES"


def test_existing_row_compatibility_uses_nullable_or_safe_defaults():
    for step in COLUMNS:
        assert " NULL" in step.definition or " DEFAULT " in step.definition
