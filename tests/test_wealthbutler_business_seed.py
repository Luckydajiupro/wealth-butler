"""真实业务种子脚本的离线安全测试。"""

import subprocess
import sys

import pytest

from scripts.seed_wealthbutler_business_data import (
    APPLY_CONFIRMATION,
    CUSTOMERS,
    EMPLOYEES,
    NAMESPACE,
    PRODUCTS,
    ROLE_PERMISSIONS,
    SEED_ENUM_VALUES,
    build_parser,
    render_plan,
    validate_seed_password,
    validate_enum_contracts,
)


def test_default_mode_is_offline_dry_run():
    args = build_parser().parse_args([])
    assert not any((args.connect_dry_run, args.apply, args.verify, args.rollback))
    plan = render_plan()
    assert "no database connection opened" in plan
    assert NAMESPACE in plan
    assert APPLY_CONFIRMATION in plan


def test_script_entrypoint_runs_from_repository_root_without_network():
    completed = subprocess.run(
        [sys.executable, "scripts/seed_wealthbutler_business_data.py"],
        check=False, capture_output=True, text=True,
    )
    assert completed.returncode == 0
    assert "no database connection opened" in completed.stdout


def test_legacy_random_supplement_generator_is_disabled():
    completed = subprocess.run(
        [sys.executable, "scripts/generate_supplement_data.py"],
        check=False, capture_output=True, text=True,
    )
    assert completed.returncode != 0
    assert "已停用" in completed.stderr


def test_seed_contract_uses_stable_natural_keys():
    assert [item["username"] for item in CUSTOMERS[:4]] == [
        "wb_seed_c1_elderly", "wb_seed_c3_balanced",
        "wb_seed_c4_professional", "wb_seed_c5_aggressive",
    ]
    assert len(CUSTOMERS) == 180
    assert {level: sum(item["risk_level"] == level for item in CUSTOMERS) for level in ("C1", "C2", "C3", "C4", "C5")} == {
        "C1": 36, "C2": 42, "C3": 48, "C4": 36, "C5": 18,
    }
    assert len(EMPLOYEES) == 30
    role_counts = {role: sum(item[4] == role for item in EMPLOYEES) for role in (
        "advisor", "operator", "risk_officer", "business_admin",
    )}
    assert role_counts == {"advisor": 12, "operator": 6, "risk_officer": 7, "business_admin": 5}
    assert {item[4] for item in EMPLOYEES} <= set(ROLE_PERMISSIONS)
    assert [item[0] for item in PRODUCTS[:5]] == [
        "WBSEED-R1-CASH", "WBSEED-R2-BOND", "WBSEED-R3-MIX",
        "WBSEED-R4-EQUITY", "WBSEED-R5-PRIVATE",
    ]
    assert len(PRODUCTS) == 55


def test_seed_assigns_advisors_and_never_creates_identity_free_workorders():
    source = __import__("inspect").getsource(
        __import__("scripts.seed_wealthbutler_business_data", fromlist=["apply_seed"]).apply_seed
    )
    assert '"advisor_id": users[advisor_keys[customer_index % len(advisor_keys)]]' in source
    assert '"customer_name": customer["name"]' in source
    assert '"order_type": "客户转介"' in source
    assert '"customer_id": users[customer["username"]]' in source


@pytest.mark.parametrize("password", [None, "short", "lowercase-only-password", "NoSymbol123456789012345"])
def test_weak_seed_password_is_rejected_without_echo(password):
    with pytest.raises(ValueError) as exc:
        validate_seed_password(password)
    if password:
        assert password not in str(exc.value)


def test_strong_seed_password_is_accepted():
    password = "Strong-Seed-Password-123!"
    assert validate_seed_password(password) == password


def test_core_evidence_contract_matches_frozen_minio_objects():
    source = __import__("inspect").getsource(
        __import__("scripts.seed_wealthbutler_business_data", fromlist=["apply_seed"]).apply_seed
    )
    expected = {
        "RISK_DISCLOSURE_SIGNED": "9c7759d99f7f007bdb9af3ff77487766fdbe31c5e38c6b6af8338919119f9027",
        "RISK_NOTIFICATION_ACKNOWLEDGED": "8f1a3234b44a10f05e99cdeb93768c00673d13e08140e14e2c65852d0f835f48",
        "DOUBLE_RECORD_COMPLETED": "794fa8089e3f1344fac126d317d58c89ec99a97244cf40ef4a323f7e251d9e09",
    }
    assert all(evidence_type in source and digest in source for evidence_type, digest in expected.items())


def test_enum_contract_preflight_covers_every_seed_value():
    validate_enum_contracts({field: sorted(values) for field, values in SEED_ENUM_VALUES.items()})
    broken = {field: sorted(values) for field, values in SEED_ENUM_VALUES.items()}
    broken["biz_work_order.order_type"] = ["客户转介"]
    with pytest.raises(RuntimeError, match="biz_work_order.order_type"):
        validate_enum_contracts(broken)
