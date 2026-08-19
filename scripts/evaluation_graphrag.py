#!/usr/bin/env python
"""纯 RAG 与 GraphRAG 同题对照实验（只读）。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def ndcg_at_k(codes: list[str], relevance: dict[str, int], k: int = 3) -> float:
    gains = [relevance.get(code, 0) for code in codes[:k]]
    dcg = sum((2**gain - 1) / math.log2(index + 2) for index, gain in enumerate(gains))
    ideal = sorted(relevance.values(), reverse=True)[:k]
    idcg = sum((2**gain - 1) / math.log2(index + 2) for index, gain in enumerate(ideal))
    return round(dcg / idcg, 4) if idcg else 0.0


def reciprocal_rank(codes: list[str], relevance: dict[str, int]) -> float:
    for index, code in enumerate(codes, 1):
        if relevance.get(code, 0) > 0:
            return round(1.0 / index, 4)
    return 0.0


def compare_rankings(pure: list[dict[str, Any]], graph: list[dict[str, Any]], relevance: dict[str, int]) -> dict[str, Any]:
    pure_codes = [str(item.get("product_code")) for item in pure]
    graph_codes = [str(item.get("product_code")) for item in graph]
    pure_ndcg = ndcg_at_k(pure_codes, relevance)
    graph_ndcg = ndcg_at_k(graph_codes, relevance)
    return {
        "pure_rag": {"ranking": pure_codes, "ndcg_at_3": pure_ndcg, "mrr": reciprocal_rank(pure_codes, relevance)},
        "graphrag": {"ranking": graph_codes, "ndcg_at_3": graph_ndcg, "mrr": reciprocal_rank(graph_codes, relevance)},
        "ranking_changed": pure_codes != graph_codes,
        "ndcg_delta": round(graph_ndcg - pure_ndcg, 4),
        "strict_relevance_improved": graph_ndcg > pure_ndcg,
    }


def run_controlled() -> dict[str, Any]:
    """用固定业务事实隔离验证生产融合排序，避免外部存储漂移。"""
    from app.WealthButler.Service.advisorService import AdvisorService

    products = [
        {"id": 1, "product_code": "TECH-R3", "product_name": "科技成长", "risk_level": "R3", "industry": "科技", "return_score": 0.9, "redemption_period_days": 180, "status": "在售"},
        {"id": 2, "product_code": "HEALTH-R3", "product_name": "医药均衡", "risk_level": "R3", "industry": "医药", "return_score": 0.7, "redemption_period_days": 90, "status": "在售"},
        {"id": 3, "product_code": "CONSUMER-R2", "product_name": "消费稳健", "risk_level": "R2", "industry": "消费", "return_score": 0.6, "redemption_period_days": 30, "status": "在售"},
    ]
    context = {"risk_assessment": {"risk_level": "C3"}, "holdings": [{"industry": "科技"}]}
    vector = {"TECH-R3": 0.95, "HEALTH-R3": 0.72, "CONSUMER-R2": 0.68}
    graph_result = {"success": True, "graph_score": 0.0, "product_scores": {"TECH-R3": 0.05, "HEALTH-R3": 1.0, "CONSUMER-R2": 0.9}}
    relevance = {"TECH-R3": 0, "HEALTH-R3": 2, "CONSUMER-R2": 2}
    service = AdvisorService(vector_search=lambda _query: vector)
    pure = service.rank_products(products, graph_result={}, vector_scores=vector, context=context, top_k=3)
    graph = service.rank_products(products, graph_result=graph_result, vector_scores=vector, context=context, top_k=3)
    comparison = compare_rankings(pure, graph, relevance)
    comparison.update({
        "id": "GRAPH-CONTROL-001", "query": "客户科技行业持仓集中，请推荐有助于分散风险的产品",
        "evidence_level": "controlled_production_ranking",
        "explanation_evidence": {"industry_concentration": "科技", "graph_product_scores": graph_result["product_scores"]},
    })
    return comparison


class _GraphLlm:
    model_name = "deterministic-read-only-evaluation"

    def __init__(self):
        cypher = (
            "MATCH (c:Customer {customer_id: $customer_id})-[:INVESTS_IN]->"
            "(p:Product)-[:BELONGS_TO]->(i:Industry) "
            "RETURN p.product_code AS product_code, i.industry_name AS industry_name, "
            "count(*) AS relation_count LIMIT $limit"
        )
        message = SimpleNamespace(content=json.dumps({"cypher": cypher, "parameters": {}}, ensure_ascii=False))
        self.model_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: SimpleNamespace(choices=[SimpleNamespace(message=message)]))))


def run_storage() -> dict[str, Any]:
    """在现有种子数据上比较生产路径；全程只读 MySQL、Milvus、Neo4j。"""
    import pymysql
    from app.Base.Config.setting import settings
    from app.Base.Client.neo4jClient import Neo4jClient
    from app.WealthButler.Service.advisorService import AdvisorService
    from app.WealthButler.Tools.graphQueryTool import GraphQueryTool

    connection = pymysql.connect(host=settings.mysql.host, port=settings.mysql.port, user=settings.mysql.user, password=str(settings.mysql.password), database=settings.mysql.name, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, username FROM base_user WHERE username IN (%s,%s) AND deleted_at IS NULL ORDER BY username", ("wb_seed_c1_elderly", "wb_seed_c4_professional"))
            customers = cursor.fetchall()
    finally:
        connection.close()
    observations = []
    with Neo4jClient() as neo4j:
        graph_tool = GraphQueryTool(client=neo4j, llm=_GraphLlm())
        service = AdvisorService()
        for customer in customers:
            customer_id = int(customer["id"])
            query = "结合现有持仓行业，推荐有助于分散风险的产品"
            context = service.load_customer_context(customer_id)
            suitable = service.filter_suitable_products(customer_id, service.load_products(), assessment=context.get("risk_assessment") or {})
            vector = service.retrieve_vector_scores(query)
            graph_result = graph_tool.execute(customer_id=customer_id, depth=2, query_intent=query)
            pure = service.rank_products(suitable, graph_result={}, vector_scores=vector, context=context, top_k=5)
            graph = service.rank_products(suitable, graph_result=graph_result, vector_scores=vector, context=context, top_k=5)
            pure_codes = [str(item.get("product_code")) for item in pure]
            graph_codes = [str(item.get("product_code")) for item in graph]
            held_industries = set(graph_result.get("industry_weights", {}))
            relevance = {
                str(item.get("product_code")): (
                    2 if item.get("industry") and str(item.get("industry")) not in held_industries
                    else 0 if item.get("industry") else 1
                )
                for item in suitable
            }
            pure_ndcg = ndcg_at_k(pure_codes, relevance, k=5)
            graph_ndcg = ndcg_at_k(graph_codes, relevance, k=5)
            observations.append({
                "customer": customer["username"], "customer_id": customer_id,
                "graph_query_success": bool(graph_result.get("success")),
                "graph_row_count": graph_result.get("row_count", 0),
                "graph_industry_count": len(graph_result.get("industry_weights", {})),
                "pure_rag_ranking": pure_codes, "graphrag_ranking": graph_codes,
                "ranking_changed": pure_codes != graph_codes,
                "explanation_evidence_added": bool(graph_result.get("industry_weights") or graph_result.get("rows")),
                "relevance_rule": "候选产品行业不在客户当前持仓行业中记2分，缺少行业记1分，已有行业记0分",
                "pure_rag_ndcg_at_5": pure_ndcg,
                "graphrag_ndcg_at_5": graph_ndcg,
                "ndcg_delta": round(graph_ndcg - pure_ndcg, 4),
                "strict_relevance_improved": graph_ndcg > pure_ndcg,
            })
    return {"evidence_level": "real_storage_observation", "query": "结合现有持仓行业，推荐有助于分散风险的产品", "observations": observations}


def run(with_storage: bool = False) -> dict[str, Any]:
    result = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "controlled": run_controlled(), "storage": None,
    }
    if with_storage:
        result["storage"] = run_storage()
    observations = (result.get("storage") or {}).get("observations", [])
    real_improved = bool(observations) and all(item.get("strict_relevance_improved") for item in observations)
    result["acceptance"] = {
        "controlled_relevance_improved": result["controlled"]["strict_relevance_improved"],
        "real_storage_executed": result["storage"] is not None,
        "real_ranking_improved_proven": real_improved,
        "note": "真实相关性仅针对行业分散查询，按候选行业是否避开当前持仓行业的固定规则计算NDCG@5。",
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-storage", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "runtime_artifacts" / "evaluation" / "graphrag-latest.json")
    args = parser.parse_args()
    result = run(args.with_storage)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"controlled_ndcg_delta": result["controlled"]["ndcg_delta"], "controlled_improved": result["controlled"]["strict_relevance_improved"], "storage_executed": result["storage"] is not None, "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
