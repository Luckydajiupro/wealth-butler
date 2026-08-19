#!/usr/bin/env python
"""Phase 5 read-only performance baseline for WealthButler.

The runner never calls an external LLM. GraphRAG, NL2SQL and AnalystAgent use
deterministic local substitutes; database operations are SELECT-only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any, Callable

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NAMESPACE = "WB-SEED-20260817"


class NoCache:
    def get(self, _key):
        return None

    def set(self, _key, _value, ttl):
        return None


class DeterministicSqlLlm:
    """Fixed SQL plus fixed interpretation; contains no network client."""

    SQL = (
        "SELECT risk_level, COUNT(*) AS customer_count "
        "FROM fin_customer_profile GROUP BY risk_level ORDER BY risk_level"
    )

    def chat(self, messages, max_tokens=512):
        if any(message.get("role") == "system" for message in messages):
            return json.dumps({"sql": self.SQL, "confidence": 0.99})
        return "只读聚合查询完成。"


class DeterministicGraphLlm:
    """Fixed customer-scoped Cypher; contains no network client."""

    model_name = "deterministic-read-only"

    def __init__(self):
        cypher = (
            "MATCH (c:Customer {customer_id: $customer_id})-[:INVESTS_IN]->"
            "(p:Product)-[:BELONGS_TO]->(i:Industry) "
            "RETURN i.industry_name AS industry_name, count(p) AS product_count LIMIT $limit"
        )
        message = SimpleNamespace(
            content=json.dumps({"cypher": cypher, "parameters": {}})
        )
        response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        self.model_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_kwargs: response)
            )
        )


def percentile(values: list[float], percentage: float) -> float:
    """Linear percentile, matching common monitoring dashboards."""
    if not values:
        raise ValueError("values must not be empty")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentage
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(samples_ms: list[float], target_ms: float | None = None) -> dict[str, Any]:
    result = {
        "samples": len(samples_ms),
        "p50_ms": round(percentile(samples_ms, 0.50), 2),
        "p95_ms": round(percentile(samples_ms, 0.95), 2),
        "min_ms": round(min(samples_ms), 2),
        "max_ms": round(max(samples_ms), 2),
    }
    if target_ms is not None:
        result["target_ms"] = target_ms
        result["target_met"] = result["p95_ms"] < target_ms
    return result


def benchmark(operation: Callable[[], Any], iterations: int, warmups: int = 1,
              validator: Callable[[Any], None] | None = None) -> dict[str, Any]:
    for _ in range(warmups):
        value = operation()
        if validator:
            validator(value)
    samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        value = operation()
        samples.append((time.perf_counter() - started) * 1000)
        if validator:
            validator(value)
    return {"samples_ms": samples}


def mysql_client_and_customer():
    from app.Base.Client.mysqlClient import MySQLClient

    client = MySQLClient()
    rows = client.execute_sync(
        "SELECT id, password_hash FROM base_user "
        "WHERE username='wb_seed_c1_elderly' AND status='active' "
        "AND deleted_at IS NULL LIMIT 1"
    ) or []
    if len(rows) != 1:
        client.close()
        raise RuntimeError("core seed customer is missing")
    return client, int(rows[0]["id"]), rows[0]["password_hash"]


def startup_probe() -> int:
    """Run the formal lifespan once; invoked only in an isolated subprocess."""
    load_dotenv(ROOT / ".env")

    async def _probe():
        from app.WealthButler.main import app, lifespan

        started = time.perf_counter()
        async with lifespan(app):
            ready_ms = (time.perf_counter() - started) * 1000
            print(f"PERF_STARTUP_READY_MS={ready_ms:.3f}")

    asyncio.run(_probe())
    return 0


def measure_startup(samples: int) -> dict[str, Any]:
    measurements = []
    for _ in range(samples):
        command = [sys.executable, str(Path(__file__).resolve()), "--startup-probe"]
        completed = subprocess.run(
            command, cwd=ROOT, text=True, capture_output=True, timeout=90,
            env={**os.environ, "WEALTH_BUTLER_PERF_EXTERNAL_LLM": "blocked"},
        )
        if completed.returncode != 0:
            tail = "\n".join(completed.stderr.splitlines()[-8:])
            raise RuntimeError(f"startup probe failed: {tail}")
        marker = next(
            (line for line in completed.stdout.splitlines()
             if line.startswith("PERF_STARTUP_READY_MS=")), None
        )
        if marker is None:
            raise RuntimeError("startup probe did not report ready time")
        measurements.append(float(marker.split("=", 1)[1]))
    return summarize(measurements)


def run_baseline(iterations: int, startup_samples: int) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    if iterations < 3:
        raise ValueError("iterations must be at least 3")

    # Importing main is side-effect free with respect to external services.
    from fastapi.testclient import TestClient
    from app.WealthButler.main import app, _register_routes_once

    _register_routes_once(app)
    api_client = TestClient(app)
    metrics: dict[str, Any] = {}

    openapi = benchmark(
        lambda: api_client.get("/openapi.json"), iterations,
        validator=lambda response: (
            None if response.status_code == 200 and len(response.json().get("paths", {})) >= 60
            else (_ for _ in ()).throw(RuntimeError("OpenAPI response is incomplete"))
        ),
    )
    metrics["openapi_response"] = summarize(openapi["samples_ms"])

    mysql_client, customer_id, password_hash = mysql_client_and_customer()
    try:
        from app.Base.Service.authService import AuthService

        seed_password = os.environ.get("WEALTH_BUTLER_SEED_PASSWORD")
        if not seed_password:
            raise RuntimeError("WEALTH_BUTLER_SEED_PASSWORD is required")
        if not AuthService.verify_password(seed_password, password_hash):
            raise RuntimeError("seed credential verification failed")
        token = AuthService.create_access_token(customer_id, "fin")

        def jwt_rbac():
            user = AuthService.get_current_user(token)
            denied = AuthService.has_permission(customer_id, "data:nl2sql_query", "fin")
            return user, denied

        auth = benchmark(
            jwt_rbac, iterations,
            validator=lambda value: (
                None if value[0] is not None and int(value[0].id) == customer_id and not value[1]
                else (_ for _ in ()).throw(RuntimeError("JWT/RBAC boundary failed"))
            ),
        )
        metrics["jwt_rbac"] = summarize(auth["samples_ms"])

        mysql_read = benchmark(
            lambda: mysql_client.execute_sync(
                "SELECT p.product_code, h.current_value FROM fin_holdings h "
                "JOIN fin_product p ON p.id=h.product_id "
                f"WHERE h.customer_id={customer_id} AND h.deleted_at IS NULL "
                "ORDER BY p.product_code LIMIT 20"
            ), iterations,
            validator=lambda rows: None if rows else (_ for _ in ()).throw(
                RuntimeError("real read-only MySQL query returned no rows")
            ),
        )
        metrics["mysql_read_only"] = summarize(mysql_read["samples_ms"])

        from app.WealthButler.Service.nl2sqlGuard import Nl2sqlGuard
        from app.WealthButler.Service.nl2sqlService import MySqlReadExecutor, Nl2sqlService

        nl2sql = Nl2sqlService(
            DeterministicSqlLlm(), MySqlReadExecutor(mysql_client),
            Nl2sqlGuard(), NoCache(), scope_token="phase5-read-only",
        )
        nl = benchmark(
            lambda: nl2sql.answer_query("按风险等级统计客户数量"), iterations,
            validator=lambda result: None if not result.error and result.row_count == 5
            else (_ for _ in ()).throw(RuntimeError(f"NL2SQL failed: {result.error}")),
        )
        metrics["nl2sql_safe"] = summarize(nl["samples_ms"], 3000)

        from app.WealthButler.Agent.analystAgent import AnalystAgent

        agent = AnalystAgent(service=nl2sql, llm=DeterministicSqlLlm())
        agent_run = benchmark(
            lambda: agent.run("按风险等级统计客户数量"), iterations,
            validator=lambda result: None if result.success
            else (_ for _ in ()).throw(RuntimeError(f"Agent failed: {result.error_msg}")),
        )
        metrics["agent_framework"] = summarize(agent_run["samples_ms"], 5000)
    finally:
        mysql_client.close()

    from app.WealthButler.Service.knowledgeService import KnowledgeService

    rag = benchmark(
        lambda: KnowledgeService.retrieve(
            "老年客户如何识别高收益投资诈骗", "fin_faq_collection", 5
        ), iterations,
        validator=lambda hits: None if hits else (_ for _ in ()).throw(
            RuntimeError("RAG returned no hits")
        ),
    )
    metrics["rag_retrieval"] = summarize(rag["samples_ms"], 2000)

    from app.Base.Client.neo4jClient import Neo4jClient
    from app.WealthButler.Tools.graphQueryTool import GraphQueryTool

    with Neo4jClient() as neo4j:
        graph_tool = GraphQueryTool(client=neo4j, llm=DeterministicGraphLlm())
        graph = benchmark(
            lambda: graph_tool.execute(customer_id, 2, "持仓行业分散度"), iterations,
            validator=lambda result: None if result.get("success") and result.get("row_count", 0) > 0
            else (_ for _ in ()).throw(RuntimeError(f"Graph query failed: {result.get('error')}")),
        )
    metrics["graph_query"] = summarize(graph["samples_ms"])

    if startup_samples:
        metrics["formal_entry_startup"] = measure_startup(startup_samples)

    return {
        "namespace": NAMESPACE,
        "mode": "real-read-only-deterministic-llm",
        "external_llm_calls": 0,
        "iterations": iterations,
        "startup_samples": startup_samples,
        "metrics": metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="run the read-only baseline")
    parser.add_argument("--startup-probe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--startup-samples", type=int, default=3)
    args = parser.parse_args()
    if args.startup_probe:
        return startup_probe()
    if not args.run:
        parser.error("explicit --run is required")
    print(json.dumps(run_baseline(args.iterations, args.startup_samples), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
