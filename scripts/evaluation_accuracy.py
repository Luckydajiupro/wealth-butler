#!/usr/bin/env python
"""Phase 5 固定题集准确率评测。

默认 ``contract`` 模式不访问外部模型或业务数据库，用于验证生产提示词之外的
确定性分类降级、安全路由和参数归一化。``live`` 模式复用项目配置的 DeepSeek
模型，统计需求文档要求的模型指标；脚本只生成候选，不执行 SQL 或业务操作。
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


CUSTOMER_CASES = (
    ("CS-001", "介绍一下稳健型理财产品", "product_consult"),
    ("CS-002", "这只债券基金是什么风险等级", "product_consult"),
    ("CS-003", "货币基金和混合基金有什么区别", "product_consult"),
    ("CS-004", "个人单笔现金交易多少需要报告", "policy_explain"),
    ("CS-005", "风险评估有效期是多久", "policy_explain"),
    ("CS-006", "适当性管理为什么要求风险匹配", "policy_explain"),
    ("CS-007", "客服电话和营业时间是什么", "faq"),
    ("CS-008", "忘记登录密码该走什么流程", "faq"),
    ("CS-009", "基金申购后几天确认份额", "faq"),
    ("CS-010", "我现在持有哪些产品", "holdings_query"),
    ("CS-011", "帮我查一下总资产", "holdings_query"),
    ("CS-012", "今天的持仓盈亏是多少", "holdings_query"),
    ("CS-013", "你好", "chitchat"),
    ("CS-014", "谢谢你的帮助", "chitchat"),
    ("CS-015", "再见", "chitchat"),
    ("CS-016", "我要投诉，请转人工客服", "transfer_to_human"),
    ("CS-017", "帮我办理赎回", "transfer_to_human"),
    ("CS-018", "我要转账，请安排客户经理", "transfer_to_human"),
)


NL2SQL_CASES = (
    {"id": "SQL-001", "question": "按风险等级统计客户数量", "tables": {"fin_customer_profile"}, "tokens": {"risk_level", "count"}},
    {"id": "SQL-002", "question": "统计每种产品风险等级的在售产品数量", "tables": {"fin_product"}, "tokens": {"risk_level", "count"}},
    {"id": "SQL-003", "question": "查询本月各交易类型的成交总金额", "tables": {"fin_transaction"}, "tokens": {"transaction_type", "sum"}},
    {"id": "SQL-004", "question": "统计各产品的持仓客户数", "tables": {"fin_holdings", "fin_product"}, "tokens": {"count"}},
    {"id": "SQL-005", "question": "按预警等级统计待处理预警", "tables": {"fin_risk_alert"}, "tokens": {"alert_level", "count"}},
    {"id": "SQL-006", "question": "统计不同状态的工单数量", "tables": {"biz_work_order"}, "tokens": {"status", "count"}},
    {"id": "SQL-007", "question": "查询有效风险评估的客户风险等级分布", "tables": {"fin_risk_assessment"}, "tokens": {"risk_level", "count"}},
    {"id": "SQL-008", "question": "列出每个客户当前持仓总市值", "tables": {"fin_holdings"}, "tokens": {"customer_id", "sum"}},
    {"id": "SQL-009", "question": "统计活跃客户账号数量", "tables": {"base_user"}, "tokens": {"count"}},
    {"id": "SQL-010", "question": "查询产品名称、风险等级和起投金额", "tables": {"fin_product"}, "tokens": {"product_name", "risk_level", "min_investment"}},
)


OPERATOR_CASES = (
    {"id": "OP-001", "text": "为客户申购产品12，金额20000元", "intent": "purchase", "params": {"product_id": 12, "amount": "20000"}},
    {"id": "OP-002", "text": "购买产品8，投入1000.50元", "intent": "purchase", "params": {"product_id": 8, "amount": "1000.50"}},
    {"id": "OP-003", "text": "赎回产品6的120.5份", "intent": "redeem", "params": {"product_id": 6, "shares": "120.5"}},
    {"id": "OP-004", "text": "赎回产品4的全部300份", "intent": "redeem", "params": {"product_id": 4, "shares": "300"}},
    {"id": "OP-005", "text": "转账60000元到账号6222020202020202，收款人张三", "intent": "transfer", "params": {"amount": "60000", "counterparty_account": "6222020202020202", "counterparty_name": "张三"}},
    {"id": "OP-006", "text": "向已验证收款人李明转5000元", "intent": "transfer", "params": {"amount": "5000", "counterparty_name": "李明"}},
    {"id": "OP-007", "text": "给客户重新做风险评估", "intent": "reassess", "params": {}},
    {"id": "OP-008", "text": "发起一次风评重做", "intent": "reassess", "params": {}},
    {"id": "OP-009", "text": "更新联系电话为13800138000", "intent": "update_info", "params": {"phone": "13800138000"}},
    {"id": "OP-010", "text": "把邮箱改成client@example.com", "intent": "update_info", "params": {"email": "client@example.com"}},
    {"id": "OP-011", "text": "查询产品15的详情", "intent": "product_query", "params": {"product_id": 15}},
    {"id": "OP-012", "text": "查找关键词养老的产品", "intent": "product_query", "params": {"keyword": "养老"}},
    {"id": "OP-013", "text": "上报客户存在拆分转账嫌疑", "intent": "suspicious_report", "params": {"description": "客户存在拆分转账嫌疑"}},
    {"id": "OP-014", "text": "报告可疑交易，疑似账户出租", "intent": "suspicious_report", "params": {"description": "疑似账户出租"}},
    {"id": "OP-015", "text": "创建投诉建议工单，客户反馈赎回延迟", "intent": "workorder_create", "params": {"order_type": "投诉建议", "intent_summary": "客户反馈赎回延迟"}},
    {"id": "OP-016", "text": "建立客户转介工单，客户希望了解养老产品", "intent": "workorder_create", "params": {"order_type": "客户转介", "intent_summary": "客户希望了解养老产品"}},
)


CUSTOMER_RAG_CASES = (
    {"id": "RAG-001", "question": "公司的客服电话和服务时间是什么", "collection": "fin_faq_collection", "keywords": ("400", "服务时间")},
    {"id": "RAG-002", "question": "基金申购后多久确认份额", "collection": "fin_faq_collection", "keywords": ("T+1", "份额")},
    {"id": "RAG-003", "question": "风险评估为什么必须做", "collection": "fin_faq_collection", "keywords": ("风险评估", "问卷")},
    {"id": "RAG-004", "question": "货币基金的风险和起投金额", "collection": "fin_product_collection", "keywords": ("货币", "R1")},
    {"id": "RAG-005", "question": "科技创新股票基金是什么风险等级", "collection": "fin_product_collection", "keywords": ("科技", "R4")},
    {"id": "RAG-006", "question": "QDII基金赎回为什么时间较长", "collection": "fin_product_collection", "keywords": ("QDII", "跨境")},
    {"id": "RAG-007", "question": "个人现金交易大额报告标准", "collection": "fin_policy_collection", "keywords": ("5万", "大额交易")},
    {"id": "RAG-008", "question": "投资者风险评估有效期", "collection": "fin_policy_collection", "keywords": ("12个月", "有效期")},
    {"id": "RAG-009", "question": "私募基金冷静期规定", "collection": "fin_policy_collection", "keywords": ("24小时", "冷静期")},
)


def _ratio(correct: int, total: int) -> float:
    return round(correct / total, 4) if total else 1.0


def evaluate_customer(classifier: Callable[[str], tuple[str, float]]) -> dict[str, Any]:
    details = []
    confusion: Counter[str] = Counter()
    correct = 0
    for case_id, question, expected in CUSTOMER_CASES:
        actual, confidence = classifier(question)
        passed = actual == expected
        correct += int(passed)
        confusion[f"{expected}->{actual}"] += 1
        details.append({"id": case_id, "expected": expected, "actual": actual, "confidence": confidence, "passed": passed})
    accuracy = _ratio(correct, len(details))
    return {"case_count": len(details), "correct": correct, "accuracy": accuracy, "target": 0.8, "passed": accuracy >= 0.8, "confusion": dict(confusion), "details": details}


def evaluate_nl2sql(generator: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    from app.WealthButler.Service.nl2sqlGuard import Nl2sqlGuard, extract_table_names

    guard = Nl2sqlGuard()
    details = []
    correct = 0
    for case in NL2SQL_CASES:
        generated = generator(case["question"])
        sql = str(generated.get("sql") or "")
        validation = guard.validate(sql) if sql else None
        actual_tables = set(extract_table_names(sql)) if sql else set()
        lowered = sql.lower()
        tables_ok = case["tables"].issubset(actual_tables)
        tokens_ok = all(token.lower() in lowered for token in case["tokens"])
        passed = bool(validation and validation.allowed and tables_ok and tokens_ok)
        correct += int(passed)
        details.append({
            "id": case["id"], "expected_tables": sorted(case["tables"]),
            "actual_tables": sorted(actual_tables), "required_tokens": sorted(case["tokens"]),
            "sql": sql, "confidence": generated.get("confidence", 0.0),
            "guard_allowed": bool(validation and validation.allowed), "passed": passed,
        })
    accuracy = _ratio(correct, len(details))
    return {"case_count": len(details), "correct": correct, "accuracy": accuracy, "target": 0.8, "passed": accuracy >= 0.8, "details": details}


def _value_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, str) and re.fullmatch(r"\d+(?:\.\d+)?", expected):
        try:
            return Decimal(str(actual)) == Decimal(expected)
        except (InvalidOperation, TypeError, ValueError):
            return False
    if isinstance(expected, str) and isinstance(actual, (int, float)):
        return str(actual) == expected
    return actual == expected


def evaluate_operator(parser: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    details = []
    intent_correct = 0
    parameter_correct = 0
    parameter_total = 0
    for case in OPERATOR_CASES:
        parsed = parser(case["text"])
        actual_intent = parsed.get("intent")
        params = parsed.get("extracted_params") if isinstance(parsed.get("extracted_params"), dict) else {}
        intent_ok = actual_intent == case["intent"]
        intent_correct += int(intent_ok)
        field_results = {}
        for field, expected in case["params"].items():
            field_results[field] = _value_equal(params.get(field), expected)
            parameter_correct += int(field_results[field])
            parameter_total += 1
        details.append({"id": case["id"], "expected_intent": case["intent"], "actual_intent": actual_intent, "intent_passed": intent_ok, "parameter_results": field_results, "actual_params": params})
    intent_accuracy = _ratio(intent_correct, len(details))
    parameter_accuracy = _ratio(parameter_correct, parameter_total)
    return {
        "case_count": len(details), "intent_correct": intent_correct,
        "intent_accuracy": intent_accuracy, "intent_target": 0.8,
        "intent_passed": intent_accuracy > 0.8,
        "parameter_field_count": parameter_total, "parameter_correct": parameter_correct,
        "parameter_accuracy": parameter_accuracy, "parameter_target": 0.9,
        "parameter_passed": parameter_accuracy > 0.9, "details": details,
    }


def evaluate_customer_rag_storage() -> dict[str, Any]:
    """按可读文本和答案关键词评估真实 Milvus 召回，不调用外部模型。"""
    from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent
    from app.WealthButler.Service.knowledgeService import KnowledgeService

    details = []
    correct = 0
    readable = 0
    for case in CUSTOMER_RAG_CASES:
        hits = KnowledgeService.retrieve(case["question"], case["collection"], 5) or []
        evidence = "\n".join(
            str(hit.get("title", "")) + "\n" + str(hit.get("content", ""))
            for hit in hits if isinstance(hit, dict)
        )
        replacement_ratio = evidence.count("\ufffd") / max(len(evidence), 1)
        is_readable = bool(evidence) and replacement_ratio < 0.01
        readable += int(is_readable)
        keyword_hits = [keyword for keyword in case["keywords"] if keyword.lower() in evidence.lower()]
        top_score = float(hits[0].get("score", 0.0)) if hits else 0.0
        threshold = CustomerServiceAgent.RETRIEVAL_THRESHOLDS[case["collection"]]
        passed = is_readable and len(keyword_hits) == len(case["keywords"]) and top_score >= threshold
        correct += int(passed)
        details.append({
            "id": case["id"], "collection": case["collection"], "hit_count": len(hits),
            "top_score": top_score, "threshold": threshold, "readable": is_readable,
            "replacement_ratio": round(replacement_ratio, 4), "matched_keywords": keyword_hits,
            "expected_keywords": list(case["keywords"]), "passed": passed,
        })
    accuracy = _ratio(correct, len(details))
    return {
        "case_count": len(details), "correct": correct, "accuracy": accuracy,
        "target": 0.8, "passed": accuracy >= 0.8,
        "readable_rate": _ratio(readable, len(details)), "details": details,
    }


def _contract_customer_classifier(question: str) -> tuple[str, float]:
    from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent

    return CustomerServiceAgent._fast_path_intent(question) or CustomerServiceAgent._fallback_intent(question)


def _reference_sql_generator(question: str) -> dict[str, Any]:
    reference = {case["question"]: case for case in NL2SQL_CASES}[question]
    if reference["id"] == "SQL-004":
        return {
            "sql": "SELECT p.product_name, COUNT(*) AS customer_count FROM fin_holdings h JOIN fin_product p ON p.id = h.product_id GROUP BY p.product_name",
            "confidence": 1.0,
        }
    table = sorted(reference["tables"])[0]
    tokens = reference["tokens"]
    if "count" in tokens:
        dimension = next((item for item in tokens if item != "count"), "id")
        sql = f"SELECT {dimension}, COUNT(*) AS record_count FROM {table} GROUP BY {dimension}"
    elif "sum" in tokens:
        dimension = next((item for item in tokens if item not in {"sum", "customer_id"}), "customer_id")
        sql = f"SELECT {dimension}, SUM(current_value) AS total_value FROM {table} GROUP BY {dimension}"
    else:
        sql = f"SELECT {', '.join(sorted(tokens))} FROM {table}"
    return {"sql": sql, "confidence": 1.0}


def _contract_operator_parser(text: str) -> dict[str, Any]:
    from app.WealthButler.Service.operatorInputPolicy import OperationInputPolicy

    case = next(item for item in OPERATOR_CASES if item["text"] == text)
    normalized = OperationInputPolicy.normalize(case["intent"], case["params"])
    return {"intent": case["intent"], "confidence": 1.0, "extracted_params": normalized["params"]}


class _LiveEvaluators:
    def __init__(self):
        from app.Base.Ai.llms.deepseekLlm import get_default_deepseek_llm
        from app.WealthButler.Tools.nl2apiTool import LLMIntentParser, NL2APITool

        self.llm = get_default_deepseek_llm()
        self.operator_parser = LLMIntentParser(self.llm)
        self.operator_tool = NL2APITool(intent_parser=self.operator_parser)

    def _complete(self, messages: list[dict[str, str]], max_tokens: int = 512) -> str:
        response = self.llm.model_client.chat.completions.create(
            model=self.llm.model_name, messages=messages, temperature=0.0, max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    def customer(self, question: str) -> tuple[str, float]:
        from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent
        from app.WealthButler.Prompts.customerServicePrompts import INTENT_CLASSIFY_PROMPT

        fast = CustomerServiceAgent._fast_path_intent(question)
        if fast:
            return fast
        messages = [
            {"role": "system", "content": "你只负责意图分类，并严格输出 JSON。"},
            {"role": "user", "content": INTENT_CLASSIFY_PROMPT.format(user_input=question)},
        ]
        for _attempt in range(2):
            content = self._complete(messages, max_tokens=128)
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            try:
                payload = json.loads(match.group(0) if match else content)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(payload, dict):
                return str(payload.get("intent")), float(payload.get("confidence", 0.0))
        # 外部模型无效输出按失败计分，但不能中断整份固定题集。
        return "unknown", 0.0

    def nl2sql(self, question: str) -> dict[str, Any]:
        from app.WealthButler.Service.nl2sqlGuard import Nl2sqlGuard
        from app.WealthButler.Service.nl2sqlService import _extract_sql, build_system_prompt, select_tables

        guard = Nl2sqlGuard()
        tables, confidence = select_tables(question)
        schema = guard.ddl_for(list(tables)) if confidence >= 1.0 else guard.full_ddl()
        content = self._complete([
            {"role": "system", "content": build_system_prompt(schema)},
            {"role": "user", "content": question},
        ])
        return _extract_sql(content)

    def operator(self, text: str) -> dict[str, Any]:
        return self.operator_tool.execute(text, {})


def run(mode: str, with_storage: bool = False) -> dict[str, Any]:
    if mode == "live":
        evaluators = _LiveEvaluators()
        customer, nl2sql, operator = evaluators.customer, evaluators.nl2sql, evaluators.operator
        evidence = "external_model"
        model = evaluators.llm.model_name
    else:
        customer, nl2sql, operator = _contract_customer_classifier, _reference_sql_generator, _contract_operator_parser
        evidence = "deterministic_regression_proxy"
        model = None
    result = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "evidence_level": evidence,
        "model": model,
        "customer_intent": evaluate_customer(customer),
        "customer_rag": evaluate_customer_rag_storage() if with_storage else None,
        "nl2sql": evaluate_nl2sql(nl2sql),
        "operator": evaluate_operator(operator),
    }
    result["acceptance_passed"] = bool(
        result["customer_intent"]["passed"] and result["customer_rag"] is not None
        and result["customer_rag"]["passed"] and result["nl2sql"]["passed"]
        and result["operator"]["intent_passed"] and result["operator"]["parameter_passed"]
        and mode == "live"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("contract", "live"), default="contract")
    parser.add_argument("--with-storage", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "runtime_artifacts" / "evaluation" / "accuracy-latest.json")
    args = parser.parse_args()
    result = run(args.mode, with_storage=args.with_storage)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "mode": result["mode"], "customer": result["customer_intent"]["accuracy"],
        "customer_rag": result["customer_rag"]["accuracy"] if result["customer_rag"] else None,
        "nl2sql": result["nl2sql"]["accuracy"],
        "operator_intent": result["operator"]["intent_accuracy"],
        "operator_params": result["operator"]["parameter_accuracy"],
        "acceptance_passed": result["acceptance_passed"], "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
