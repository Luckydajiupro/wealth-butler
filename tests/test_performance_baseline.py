import json

import pytest

from scripts.performance_baseline import (
    DeterministicGraphLlm,
    DeterministicSqlLlm,
    benchmark,
    percentile,
    summarize,
)


def test_percentile_and_summary_are_stable():
    values = [1, 2, 3, 4, 5]
    assert percentile(values, 0.5) == 3
    assert percentile(values, 0.95) == pytest.approx(4.8)
    assert summarize(values, 5)["target_met"] is True


def test_benchmark_runs_warmup_outside_samples():
    calls = []
    measured = benchmark(lambda: calls.append(1) or True, iterations=3, warmups=2)
    assert len(calls) == 5
    assert len(measured["samples_ms"]) == 3


def test_deterministic_sql_llm_is_read_only_and_network_free():
    llm = DeterministicSqlLlm()
    payload = json.loads(llm.chat([{"role": "system", "content": "x"}]))
    assert payload["sql"].startswith("SELECT ")
    assert all(word not in payload["sql"].upper() for word in ("INSERT", "UPDATE", "DELETE", "DROP"))
    assert not hasattr(llm, "model_client")


def test_deterministic_graph_llm_is_customer_scoped_read_only():
    llm = DeterministicGraphLlm()
    response = llm.model_client.chat.completions.create()
    payload = json.loads(response.choices[0].message.content)
    cypher = payload["cypher"]
    assert "$customer_id" in cypher
    assert cypher.startswith("MATCH ")
    assert all(word not in cypher.upper() for word in ("CREATE", "MERGE", "DELETE", "SET "))
