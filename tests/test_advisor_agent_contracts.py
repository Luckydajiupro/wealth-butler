from app.Base.Ai.base.baseAgent import InMemoryMemory
from app.Base.Ai.base.baseTool import BaseTool
from app.WealthButler.Agent.advisorAgent import AdvisorAgent
from app.WealthButler.Prompts.advisorPrompts import ADVISOR_SYSTEM_PROMPT
from app.WealthButler.Service.advisorService import AdvisorService
from app.WealthButler.Tools.graphQueryTool import GraphQueryTool
from app.Base.Models.BaseLLMConversationModel import BaseLLMConversationModel


class _Tool(BaseTool):
    def __init__(self, name):
        super().__init__(name=name, description="test")

    def execute(self, **kwargs):
        return {"success": False}


class _Llm:
    model_name = "test"


class _CompletionClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = type("Message", (), {"content": self.content})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice], "usage": None})()


class _EvidenceLlm:
    model_name = "evidence-test"

    def __init__(self, content):
        self.completions = _CompletionClient(content)
        self.model_client = type("ModelClient", (), {
            "chat": type("Chat", (), {"completions": self.completions})()
        })()


class _ForbiddenService:
    def __getattr__(self, name):
        raise AssertionError(f"static advisor route must not call service: {name}")


class _PortfolioService:
    def load_customer_context(self, _customer_id):
        return {
            "risk_assessment": {"risk_level": "C2"},
            "profile": {},
            "holdings": [{"current_value": 1000}],
        }

    def load_products(self):
        return []

    @staticmethod
    def _enrich_holdings(holdings, _products):
        return holdings


def _agent(memory=None):
    return AdvisorAgent(
        llm=_Llm(),
        service=_ForbiddenService(),
        graph_tool=_Tool("GraphQuery"),
        suitability_tool=_Tool("SuitabilityCheck"),
        memory=memory or InMemoryMemory(),
    )


def test_operation_request_is_redirected_without_running_recommendation_pipeline():
    agent = _agent()

    result = agent.run("帮客户申购这款产品", customer_id=1001)

    assert result.success is True
    assert "客户经理/运营" in result.output
    assert result.metadata["intent"] == "operation_request"
    assert result.metadata["audit_applicable"] is False


def test_advisor_in_memory_history_records_complete_turns():
    memory = InMemoryMemory()
    agent = _agent(memory)

    agent.run("你好", customer_id=1001)
    agent.run("谢谢", customer_id=1001)

    assert [message["role"] for message in memory.get_messages()] == [
        "user", "assistant", "user", "assistant"
    ]


def test_advisor_greeting_acknowledges_selected_customer():
    result = _agent().run("你好", customer_id=1001)

    assert result.success is True
    assert "当前客户已就绪" in result.output
    assert "请先选择" not in result.output


def test_advisor_recognizes_common_customer_analysis_and_plan_phrases():
    agent = _agent()

    assert agent.classify_intent("帮我看看这个客户的情况")[0] == "portfolio_analysis"
    assert agent.classify_intent("根据这个客户做个方案")[0] == "recommend"
    assert agent.classify_intent(
        "根据这个客户的风险等级、现有持仓和流动性需求，做一个产品配置方案"
    )[0] == "recommend"
    assert agent.classify_intent(
        "XX全球精选QDII怎么样？请说明风险等级、起投金额和适合什么客户"
    )[0] == "product_explain"
    assert agent.classify_intent("XX全球精选QDII怎么样")[0] == "product_explain"
    assert agent.classify_intent(
        "请分析XX平衡优选混合与当前客户的风险适配性、流动性和配置价值"
    )[0] == "product_explain"


def test_advisor_followup_inherits_previous_recommendation_intent():
    agent = _agent()
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "根据客户持仓做个配置方案"},
        {"role": "assistant", "content": "客户当前有效风险评估等级为C3，推荐结果如下："},
        {"role": "user", "content": "为什么这样匹配"},
    ]

    intent, confidence, routed_query = agent._resolve_contextual_intent(
        messages, "为什么这样匹配", "clarify", 0.4
    )

    assert intent == "recommend"
    assert confidence >= 0.8
    assert "根据客户持仓" in routed_query
    assert "追问：为什么这样匹配" in routed_query


def test_advisor_followup_overrides_generic_product_explain_wording():
    agent = _agent()
    messages = [
        {"role": "user", "content": "推荐三款产品"},
        {"role": "assistant", "content": "推荐结果如下"},
        {"role": "user", "content": "为什么这样匹配？请分别说明理由"},
    ]

    intent, _, _ = agent._resolve_contextual_intent(
        messages, "为什么这样匹配？请分别说明理由", "product_explain", 0.9
    )

    assert intent == "recommend"


def test_advisor_followup_finds_last_real_recommendation_past_irrelevant_turn():
    agent = _agent()
    messages = [
        {"role": "user", "content": "推荐三款产品"},
        {"role": "assistant", "content": "推荐结果如下"},
        {"role": "user", "content": "说明这个产品"},
        {"role": "assistant", "content": "请提供产品名称"},
        {"role": "user", "content": "为什么这样匹配"},
    ]

    intent, _, routed_query = agent._resolve_contextual_intent(
        messages, "为什么这样匹配", "clarify", 0.4
    )

    assert intent == "recommend"
    assert routed_query.startswith("推荐三款产品")


def test_recommendation_limit_follows_requested_count():
    assert AdvisorAgent._recommendation_limit("推荐三款产品") == 3
    assert AdvisorAgent._recommendation_limit("推荐2个产品") == 2
    assert AdvisorAgent._recommendation_limit("给我一个配置方案") == 1
    assert AdvisorAgent._recommendation_limit("推荐产品") == 5


def test_portfolio_analysis_returns_deterministic_evidence_without_llm_wait():
    agent = AdvisorAgent(
        llm=_Llm(),
        service=_PortfolioService(),
        graph_tool=_Tool("GraphQuery"),
        suitability_tool=_Tool("SuitabilityCheck"),
    )

    result = agent.run("分析一下这位客户的持仓组合", customer_id=1001)

    assert result.success is True
    assert "风险等级为C2" in result.output
    assert "持仓市值合计1000.00元" in result.output
    assert result.metadata["audit_kind"] == "portfolio_analysis"


def test_portfolio_analysis_uses_llm_with_grounded_evidence_when_available():
    llm = _EvidenceLlm("这是基于客户数据的自然语言分析。")
    agent = AdvisorAgent(
        llm=llm,
        service=_PortfolioService(),
        graph_tool=_Tool("GraphQuery"),
        suitability_tool=_Tool("SuitabilityCheck"),
    )

    result = agent.run("分析一下这位客户的持仓组合", customer_id=1001)

    assert result.output == "这是基于客户数据的自然语言分析。"
    assert len(llm.completions.calls) == 1
    evidence_message = llm.completions.calls[0]["messages"][-1]["content"]
    assert "只能使用以下系统证据" in evidence_message
    assert '"risk_level": "C2"' in evidence_message


def test_advisor_graph_query_generation_is_network_free_and_customer_scoped():
    generated = GraphQueryTool(llm=object())._generate_query(
        customer_id=1001,
        depth=2,
        query_intent="分析持仓组合",
    )

    valid, reason = GraphQueryTool.validate_query(
        generated["cypher"], generated["parameters"], customer_id=1001
    )
    assert valid is True, reason
    assert generated["parameters"]["customer_id"] == 1001


def test_product_ordinal_followup_resolves_from_latest_advisor_answer():
    products = [
        {"product_name": "稳健产品A"},
        {"product_name": "成长产品B"},
    ]
    messages = [
        {"role": "assistant", "content": "1. 成长产品B（R4）\n2. 稳健产品A（R2）"},
        {"role": "user", "content": "第一个产品风险是什么"},
    ]

    resolved = AdvisorAgent._resolve_products_from_history(messages, products, "第一个产品风险是什么")

    assert resolved == [{"product_name": "成长产品B"}]


def test_database_memory_keeps_multi_product_answer_for_followups():
    answer = "1. 稳健产品A\n2. 成长产品B\n3. 平衡产品C" + "。" * 200
    messages = BaseLLMConversationModel(question="推荐产品", answer=answer).to_messages()

    assert "2. 成长产品B" in messages[1]["content"]
    assert "3. 平衡产品C" in messages[1]["content"]


def test_admission_tier_aggregation_handles_empty_and_mixed_results():
    assert AdvisorAgent._aggregate_admission_tier([]) == "不可执行"
    assert AdvisorAgent._aggregate_admission_tier([
        {"suitability": {"admission_tier": "可执行"}},
        {"suitability": {"admission_tier": "仅预约"}},
    ]) == "混合（逐产品确认）"


def test_suitability_annotation_keeps_rejected_product_for_explanation():
    service = AdvisorService(assessment_loader=lambda _customer_id: {"risk_level": "C1"})

    products = service.evaluate_products_suitability(
        1001,
        [{"product_name": "高风险产品", "risk_level": "R5", "product_type": "公募基金"}],
    )

    assert len(products) == 1
    assert products[0]["suitability"]["passed"] is False
    assert products[0]["suitability"]["admission_tier"] == "不可执行"


def test_advisor_prompt_matches_plain_text_frontend_and_read_only_boundary():
    assert "不使用 Markdown" in ADVISOR_SYSTEM_PROMPT
    assert "业务操作助手" in ADVISOR_SYSTEM_PROMPT
