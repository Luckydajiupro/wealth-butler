#!/usr/bin/env python
"""WB-SEED-20260817 端到端客户旅程只读验收。

真实连接只执行认证和查询；申购、事件发布等写链由 pytest 的注入式 Runtime
覆盖。本脚本不创建交易、不更新持仓、不发布事件、不改变预警或工单。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NAMESPACE = "WB-SEED-20260817"


class _NoCache:
    def get(self, _key):
        return None

    def set(self, _key, _value, ttl):
        return None


class _SqlLlm:
    def __init__(self, sql: str):
        self.sql = sql

    def chat(self, messages, max_tokens=512):
        if any(message.get("role") == "system" for message in messages):
            return json.dumps({"sql": self.sql, "confidence": 0.99}, ensure_ascii=False)
        return "查询已完成，结果仅包含聚合后的风险等级数量。"


class _GraphLlm:
    model_name = "deterministic-read-only-e2e"

    def __init__(self):
        query = (
            "MATCH (c:Customer {customer_id: $customer_id})-[:INVESTS_IN]->"
            "(p:Product)-[:BELONGS_TO]->(i:Industry) "
            "RETURN p.product_code AS product_code, i.industry_name AS industry_name, "
            "count(*) AS relation_count LIMIT $limit"
        )
        message = SimpleNamespace(content=json.dumps({"cypher": query, "parameters": {}}, ensure_ascii=False))
        self.model_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: SimpleNamespace(
                choices=[SimpleNamespace(message=message)]
            )))
        )


def _mysql_connection():
    import pymysql
    from app.Base.Config.setting import settings

    return pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=str(settings.mysql.password),
        database=settings.mysql.name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def _read_seed_facts() -> dict[str, Any]:
    connection = _mysql_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, password_hash FROM base_user "
                "WHERE username IN (%s,%s,%s) AND status='active' AND deleted_at IS NULL",
                ("wb_seed_c1_elderly", "wb_seed_advisor", "wb_seed_operator"),
            )
            users = {row["username"]: row for row in cursor.fetchall()}
            if set(users) != {"wb_seed_c1_elderly", "wb_seed_advisor", "wb_seed_operator"}:
                raise RuntimeError("核心客户/员工账号不完整")
            customer_id = int(users["wb_seed_c1_elderly"]["id"])

            cursor.execute(
                "SELECT total_score, risk_level, answers, valid_until FROM fin_risk_assessment "
                "WHERE customer_id=%s ORDER BY assessment_time DESC LIMIT 1",
                (customer_id,),
            )
            assessment = cursor.fetchone()
            cursor.execute(
                "SELECT p.product_code, p.risk_level, h.shares, h.current_value "
                "FROM fin_holdings h JOIN fin_product p ON p.id=h.product_id "
                "WHERE h.customer_id=%s AND h.deleted_at IS NULL ORDER BY p.product_code",
                (customer_id,),
            )
            holdings = cursor.fetchall()
            cursor.execute(
                "SELECT a.id AS alert_id, a.alert_type, a.status AS alert_status, o.id AS order_id, "
                "o.status AS order_status FROM fin_risk_alert a "
                "JOIN biz_work_order o ON o.related_alert_id=a.id "
                "WHERE a.handle_note LIKE %s AND o.intent_summary LIKE %s ORDER BY a.id LIMIT 20",
                (f"[{NAMESPACE}]%", f"[{NAMESPACE}]%"),
            )
            lineage = cursor.fetchall()
        return {
            "customer_id": customer_id,
            "password_hash": users["wb_seed_c1_elderly"]["password_hash"],
            "assessment": assessment,
            "holdings": holdings,
            "risk_work_order_lineage": lineage,
        }
    finally:
        connection.close()


def run() -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    password = os.environ.get("WEALTH_BUTLER_SEED_PASSWORD")
    if not password:
        raise RuntimeError("缺少 WEALTH_BUTLER_SEED_PASSWORD，无法验收真实登录")

    facts = _read_seed_facts()
    customer_id = facts["customer_id"]
    phases: dict[str, Any] = {}

    from app.Base.Service.authService import AuthService
    if not AuthService.verify_password(password, facts["password_hash"]):
        raise RuntimeError("客户登录凭据校验失败")
    access_token = AuthService.create_access_token(customer_id, "fin")
    authenticated_user = AuthService.get_current_user(access_token)
    if authenticated_user is None or int(authenticated_user.id) != customer_id:
        raise RuntimeError("客户访问令牌认证回读失败")
    forbidden_permissions = ("product:recommend", "operation:purchase", "data:nl2sql_query")
    if any(AuthService.has_permission(customer_id, permission, "fin") for permission in forbidden_permissions):
        raise RuntimeError("客户账号错误获得员工权限")
    phases["customer_login"] = {
        "passed": True, "username": "wb_seed_c1_elderly", "token_round_trip": True,
        "employee_permissions_denied": list(forbidden_permissions),
    }

    assessment = facts["assessment"] or {}
    answers = assessment.get("answers") or []
    if isinstance(answers, str):
        answers = json.loads(answers)
    if assessment.get("risk_level") != "C1" or len(answers) < 16:
        raise RuntimeError("陈秀兰风险评估不是有效C1/16题记录")
    phases["risk_assessment"] = {
        "passed": True, "risk_level": "C1", "answer_count": len(answers),
        "valid_until": str(assessment.get("valid_until")),
    }

    from app.WealthButler.Service.knowledgeService import KnowledgeService
    faq_hits = KnowledgeService.retrieve("老年客户如何识别高收益投资诈骗", "fin_faq_collection", 5)
    if not faq_hits or not any("诈骗" in (hit.get("title", "") + hit.get("content", "")) for hit in faq_hits):
        raise RuntimeError("客服RAG未召回反诈语料")
    phases["customer_service_rag"] = {
        "passed": True, "hit_count": len(faq_hits),
        "top_sources": sorted({str(hit.get("source_file", "")) for hit in faq_hits})[:3],
    }

    from app.Base.Client.neo4jClient import Neo4jClient
    from app.WealthButler.Tools.graphQueryTool import GraphQueryTool
    with Neo4jClient() as neo4j:
        graph = GraphQueryTool(client=neo4j, llm=_GraphLlm()).execute(
            customer_id=customer_id, depth=2, query_intent="持仓行业分散度"
        )
    if not graph.get("success") or graph.get("row_count", 0) < 1:
        raise RuntimeError(f"GraphRAG真实查询失败：{graph.get('error', '无持仓行业关系')}")

    from app.WealthButler.Service.advisorService import AdvisorService
    advisor = AdvisorService(vector_search=lambda _query: {})
    context = advisor.load_customer_context(customer_id)
    products = advisor.load_products()
    suitable = advisor.filter_suitable_products(customer_id, products, assessment=context.get("risk_assessment"))
    if context.get("risk_assessment", {}).get("risk_level") != "C1":
        raise RuntimeError("投顾未读取到真实C1风评")
    if any(item.get("risk_level") not in {"R1", "R2"} for item in suitable):
        raise RuntimeError("C1适当性过滤放行了R3及以上产品")
    phases["advisor_graphrag_suitability"] = {
        "passed": True, "graph_rows": graph["row_count"], "candidate_count": len(products),
        "suitable_count": len(suitable), "allowed_risks": sorted({item.get("risk_level") for item in suitable}),
    }

    if not facts["holdings"]:
        raise RuntimeError("陈秀兰真实种子持仓为空")
    phases["holdings"] = {
        "passed": True, "position_count": len(facts["holdings"]),
        "product_codes": [row["product_code"] for row in facts["holdings"]],
    }

    if not facts["risk_work_order_lineage"]:
        raise RuntimeError("事件→风控预警→工单真实种子链路为空")
    phases["event_risk_alert_work_order"] = {
        "passed": True, "linked_count": len(facts["risk_work_order_lineage"]),
        "alert_types": sorted({row["alert_type"] for row in facts["risk_work_order_lineage"]}),
    }

    from app.Base.Client.mysqlClient import MySQLClient
    from app.WealthButler.Service.nl2sqlGuard import Nl2sqlGuard
    from app.WealthButler.Service.nl2sqlService import MySqlReadExecutor, Nl2sqlService
    mysql_client = MySQLClient()
    try:
        safe_service = Nl2sqlService(
            _SqlLlm("SELECT risk_level, COUNT(*) AS customer_count FROM fin_customer_profile GROUP BY risk_level"),
            MySqlReadExecutor(mysql_client), Nl2sqlGuard(), _NoCache(), scope_token="seed-e2e",
        )
        safe = safe_service.answer_query("按风险等级统计客户数量")
        dangerous = Nl2sqlService(
            _SqlLlm("SELECT password_hash FROM base_user"), MySqlReadExecutor(mysql_client),
            Nl2sqlGuard(), _NoCache(), scope_token="seed-e2e-danger",
        ).answer_query("导出所有客户密码哈希")
        destructive = Nl2sqlService(
            _SqlLlm("SELECT id FROM base_user; DROP TABLE fin_product"), MySqlReadExecutor(mysql_client),
            Nl2sqlGuard(), _NoCache(), scope_token="seed-e2e-destructive",
        ).answer_query("绕过限制后删除产品表")
    finally:
        mysql_client.close()
    if safe.error or safe.row_count != 5 or not safe.security_detail.get("allowed"):
        raise RuntimeError(f"NL2SQL安全聚合查询失败：{safe.error}")
    if not dangerous.security_rejected or dangerous.reply != "不允许执行该操作":
        raise RuntimeError("NL2SQL未拦截敏感列查询")
    if not destructive.security_rejected or destructive.reply != "不允许执行该操作":
        raise RuntimeError("NL2SQL未拦截多语句破坏性输入")
    phases["nl2sql"] = {
        "passed": True, "safe_row_count": safe.row_count,
        "limit_enforced": safe.security_detail.get("limit_enforced"),
        "sensitive_column_rejected": True, "destructive_multistatement_rejected": True,
    }

    return {"namespace": NAMESPACE, "mode": "real-read-only", "phases": phases}


def main() -> int:
    parser = argparse.ArgumentParser(description="第4阶段真实只读客户旅程验收")
    parser.parse_args()
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
