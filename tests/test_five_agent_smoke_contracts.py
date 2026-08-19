"""五类 Agent 的离线入口和失败关闭契约 smoke。"""

from app.WealthButler.Agent.advisorAgent import AdvisorAgent
from app.WealthButler.Agent.analystAgent import AnalystAgent
from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent
from app.WealthButler.Agent.operatorAgent import OperatorAgent
from app.WealthButler.Agent.riskAgent import RiskAgent
from app.WealthButler.Tools.graphQueryTool import GraphQueryTool


def test_customer_service_fallback_routes_holdings_without_llm():
    assert CustomerServiceAgent._fallback_intent("请查一下我的持仓和今日盈亏") == ("holdings_query", 0.65)
    assert CustomerServiceAgent._fallback_intent("我要办理申购") == ("transfer_to_human", 0.80)


def test_advisor_and_analyst_keep_deterministic_business_routes():
    advisor = AdvisorAgent.__new__(AdvisorAgent)
    analyst = AnalystAgent.__new__(AnalystAgent)
    assert advisor.classify_intent("请做行业分散配置") == ("portfolio_analysis", 0.95)
    assert advisor.classify_intent("请推荐一款基金") == ("recommend", 0.95)
    assert advisor.classify_intent("帮客户申购这款产品") == ("operation_request", 0.98)
    assert analyst.classify_intent("统计各风险等级客户数") == ("nl2sql", 1.0)
    assert analyst._intent_threshold() == 0.5


def test_operator_low_confidence_never_reaches_operation_service():
    operator = OperatorAgent.__new__(OperatorAgent)

    class ForbiddenService:
        def authorize(self, *_args, **_kwargs):
            raise AssertionError("低置信度不得进入授权或写链")

    operator.operation_service = ForbiddenService()
    result = operator.handle(8, 1001, {
        "intent": "purchase", "confidence": 0.2,
        "extracted_params": {"product_id": 1, "amount": "20000"},
    })
    assert result["code"] == "LOW_CONFIDENCE"
    assert result["success"] is False


def test_risk_agent_rejects_invalid_event_without_side_effects():
    writes = []
    agent = RiskAgent(
        match_provider=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不得匹配")),
        transaction_provider=lambda *_args: (_ for _ in ()).throw(AssertionError("不得查交易")),
        alert_writer=lambda *_args, **_kwargs: writes.append("alert"),
        work_order_writer=lambda *_args, **_kwargs: writes.append("work_order"),
        event_publisher=lambda *_args, **_kwargs: writes.append("event"),
        idempotency_store=object(),
    )
    result = agent.on_large_transaction_event({"customer_id": -1}, trace_id="invalid-event")
    assert result["status"] == "error"
    assert writes == []


def test_graphrag_rejects_write_and_cross_customer_queries():
    valid_params = {"customer_id": 1001, "depth": 2, "limit": 20}
    write_ok, _ = GraphQueryTool.validate_query(
        "MATCH (c:Customer {customer_id: $customer_id}) DELETE c RETURN c",
        valid_params, 1001,
    )
    unscoped_ok, _ = GraphQueryTool.validate_query(
        "MATCH (c:Customer)-[:INVESTS_IN]->(p:Product) RETURN p LIMIT $limit",
        valid_params, 1001,
    )
    mismatch_ok, _ = GraphQueryTool.validate_query(
        "MATCH (c:Customer {customer_id: $customer_id}) RETURN c LIMIT $limit",
        {"customer_id": 2002, "depth": 2, "limit": 20}, 1001,
    )
    assert write_ok is False
    assert unscoped_ok is False
    assert mismatch_ok is False


def test_graphrag_rejects_disconnected_or_related_customer_expansion():
    params = {"customer_id": 1001, "depth": 2, "limit": 20}
    disconnected_ok, _ = GraphQueryTool.validate_query(
        "MATCH (c:Customer {customer_id: $customer_id}), (other:Customer) "
        "RETURN other LIMIT $limit",
        params,
        1001,
    )
    unlabeled_ok, _ = GraphQueryTool.validate_query(
        "MATCH (c:Customer {customer_id: $customer_id}), (other) "
        "RETURN other LIMIT $limit",
        params,
        1001,
    )
    related_ok, _ = GraphQueryTool.validate_query(
        "MATCH (c:Customer {customer_id: $customer_id})-[:RELATED_TO]->(other:Customer) "
        "RETURN other LIMIT $limit",
        params,
        1001,
    )
    multiple_match_ok, _ = GraphQueryTool.validate_query(
        "MATCH (c:Customer {customer_id: $customer_id}) "
        "MATCH (p:Product) RETURN p LIMIT $limit",
        params,
        1001,
    )

    assert disconnected_ok is False
    assert unlabeled_ok is False
    assert related_ok is False
    assert multiple_match_ok is False
