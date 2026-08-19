"""Milvus/Neo4j 种子脚本的离线安全与幂等测试。"""

import ast
from pathlib import Path

import pytest

from scripts.seed_vector_graph_data import (
    APPLY_CONFIRMATION,
    CUSTOMERS,
    MySQLSeedData,
    NAMESPACE,
    SeedItem,
    build_faq_items,
    build_memory_items,
    build_parser,
    build_policy_items,
    build_product_items,
    existing_stable_keys,
    namespace_row_count,
    seed_neo4j,
    select_missing_items,
    validate_embedding,
)


def test_seed_candidates_are_meaningful_unique_and_cross_keyed():
    customer_ids = {key: index for index, key in enumerate(CUSTOMERS, start=1001)}
    groups = {
        "faq": build_faq_items(),
        "product": build_product_items(),
        "policy": build_policy_items(),
        "memory": build_memory_items(customer_ids),
    }

    assert len(groups["faq"]) >= 22
    assert len(groups["product"]) >= 18
    assert len(groups["policy"]) >= 5
    assert len(groups["memory"]) == 100
    for items in groups.values():
        keys = [item.stable_key for item in items]
        assert len(keys) == len(set(keys))
        assert all(len(item.text) >= 30 for item in items)

    memory_blob = "\n".join(item.text for item in groups["memory"])
    assert "王建国" in memory_blob and "陈秀兰" in memory_blob
    assert NAMESPACE in memory_blob


def test_plan_only_fills_deficit_and_is_namespace_idempotent():
    candidates = [SeedItem(f"key-{i}", f"真实金融主题文本-{i}" * 3, {}) for i in range(10)]
    selected = select_missing_items(candidates, {"key-0", "key-1"}, current_count=95, target=100)
    assert [item.stable_key for item in selected] == ["key-2", "key-3", "key-4", "key-5", "key-6"]
    assert select_missing_items(candidates, set(), current_count=100, target=100) == []

    rows = [
        {"metadata": '{"namespace":"WB-SEED-20260817","stable_key":"key-1"}'},
        {"metadata": '{"namespace":"other","stable_key":"key-2"}'},
    ]
    assert existing_stable_keys(rows) == {"key-1"}
    memory_rows = [{
        "id": "server-auto-id", "session_id": NAMESPACE,
        "content": f"[namespace={NAMESPACE}][stable_key=memory-1] 客户长期记忆",
    }]
    assert existing_stable_keys(memory_rows, memory=True) == {"memory-1"}
    assert namespace_row_count(rows) == 1


def test_embedding_validation_fails_closed():
    with pytest.raises(RuntimeError, match="维度"):
        validate_embedding([0.1] * 3)
    with pytest.raises(RuntimeError, match="零向量"):
        validate_embedding([0.0] * 1024)
    with pytest.raises(RuntimeError, match="非有限"):
        validate_embedding([0.1] * 1023 + [float("nan")])
    assert len(validate_embedding([0.1] * 1024)) == 1024


def test_apply_requires_exact_confirmation():
    parser = build_parser()
    args = parser.parse_args(["--apply"])
    assert args.confirm == ""
    args = parser.parse_args(["--apply", "--confirm", APPLY_CONFIRMATION])
    assert args.apply is True and args.confirm == APPLY_CONFIRMATION


def test_neo4j_seed_source_has_no_delete_or_create_node_statements():
    source_path = Path(__file__).parents[1] / "scripts" / "seed_vector_graph_data.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    string_literals = [node.value.upper() for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    cypher_blob = "\n".join(value for value in string_literals if "MATCH" in value or "MERGE" in value or "CONSTRAINT" in value)
    assert "DETACH DELETE" not in cypher_blob
    assert " DELETE " not in cypher_blob
    assert "CREATE (" not in cypher_blob
    assert "MERGE (" in cypher_blob


def test_graph_seed_uses_all_namespace_customers_employees_and_products():
    employees = {
        f"employee-{index:02d}": {
            "id": 2000 + index, "employee_role": "理财顾问" if index < 15 else "客户经理",
            "advisor_level": "高级", "extra_data": '{"display_name":"种子员工"}',
        }
        for index in range(30)
    }
    employee_keys = list(employees)
    customers = {}
    for index in range(180):
        customers[f"customer-{index:03d}"] = {
            "id": 1000 + index, "risk_level": f"C{index % 5 + 1}",
            "extra_data": {
                "display_name": f"验收客户{index:03d}",
                "advisor_username": employee_keys[index % 15],
                "customer_manager_username": employee_keys[15 + index % 15],
            },
        }
    products = {
        f"WBSEED-R{index % 5 + 1}-{index:03d}": {
            "id": 3000 + index, "product_name": f"演示产品{index:03d}", "product_type": "公募基金",
            "risk_level": f"R{index % 5 + 1}", "industry": "科技", "fund_manager": "种子基金管理人",
        }
        for index in range(55)
    }

    class FakeNeo4j:
        def __init__(self):
            self.calls = []

        def run(self, cypher, parameters=None):
            self.calls.append((cypher, parameters or {}))
            return [{"touched": len((parameters or {}).get("rows", []))}]

    client = FakeNeo4j()
    seed_neo4j(client, MySQLSeedData(customers, employees, products, []))
    row_batches = [(cypher, params["rows"]) for cypher, params in client.calls if "rows" in params]
    assert any("MERGE (n:Customer" in cypher and len(rows) == 180 for cypher, rows in row_batches)
    assert any("MERGE (n:Employee" in cypher and len(rows) == 30 for cypher, rows in row_batches)
    assert any("MERGE (n:Product" in cypher and len(rows) == 55 for cypher, rows in row_batches)
    assert any(":SERVES" in cypher and len(rows) == 360 for cypher, rows in row_batches)
