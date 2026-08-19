#!/usr/bin/env python
"""Phase 5 答辩 Demo：真实只读检索 + 隔离式写链。

不调用外部 LLM，不执行真实交易，不打印密码、JWT 或确认 token。
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _print_result(passed: bool, label: str) -> None:
    print(f"{'PASS' if passed else 'FAIL'} | {label}")


def _run_real_read_journey() -> tuple[bool, dict]:
    try:
        # 屏蔽依赖初始化日志，答辩输出只保留场景结论。
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            from scripts.verify_phase4_customer_journey import run

            report = run()
        return True, report
    except Exception:
        return False, {}


def _run_isolated_contracts() -> bool:
    nodes = (
        "tests/test_operator_real_runtime_e2e.py::test_concurrent_confirmation_executes_transaction_at_most_once",
        "tests/test_operator_real_runtime_e2e.py::test_permission_suitability_and_missing_evidence_fail_closed",
        "tests/test_operator_real_runtime_e2e.py::test_event_failure_enters_retry_and_audit_never_contains_sensitive_values",
        "tests/test_five_agent_smoke_contracts.py",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *nodes, "-q", "--disable-warnings"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return result.returncode == 0


def main() -> int:
    print("WB-SEED-20260817 | Phase 5 答辩 Demo")
    real_ok, report = _run_real_read_journey()
    phases = report.get("phases", {}) if real_ok else {}
    checks = (
        (bool(phases.get("customer_login", {}).get("passed")), "客户认证与越权拒绝"),
        (bool(phases.get("risk_assessment", {}).get("passed")), "客户风险评估"),
        (bool(phases.get("customer_service_rag", {}).get("passed")), "客服 RAG（真实 Milvus）"),
        (bool(phases.get("advisor_graphrag_suitability", {}).get("passed")), "投顾 GraphRAG 与适当性"),
        (bool(phases.get("holdings", {}).get("passed")), "真实持仓只读查询"),
        (bool(phases.get("event_risk_alert_work_order", {}).get("passed")), "风控预警与工单关联"),
        (bool(phases.get("nl2sql", {}).get("passed")), "NL2SQL 安全查询与危险输入拒绝"),
    )
    for passed, label in checks:
        _print_result(passed, label)

    isolated_ok = _run_isolated_contracts()
    _print_result(isolated_ok, "Operator 申购二次确认（隔离内存，无真实交易）")

    passed = real_ok and isolated_ok and all(item[0] for item in checks)
    print(f"RESULT | {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
