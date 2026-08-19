import asyncio
import threading
import time

from app.Base.Ai.base.baseAgent import AgentResult
from app.Base.Ai.base.baseTool import BaseTool
from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent
from app.WealthButler.Agent.customerServiceAgent import CustomerStreamCancelled
from app.WealthButler.Prompts.customerServicePrompts import ANSWER_PROMPT, SYSTEM_PROMPT
from app.WealthButler.Prompts.customerServicePrompts import (
    CLARIFICATION_MESSAGE,
    FALLBACK_MESSAGE,
    KNOWLEDGE_UNAVAILABLE_MESSAGE,
)
from app.WealthButler.Service.chatService import ChatService


class _Tool(BaseTool):
    def __init__(self, name, result=None):
        super().__init__(name=name, description="test boundary")
        self._result = result or {}

    def execute(self, **kwargs):
        return self._result


class _CustomerService:
    def __init__(self):
        self.archived_messages = None

    def validate_customer(self, customer_id):
        return None

    def archive_conversation(self, **kwargs):
        self.archived_messages = kwargs["messages"]
        return 73

    def get_conversation(self, session_id, customer_id):
        return None


class _Delta:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content):
        self.choices = [_Choice(content)]
        self.usage = None


class _StreamingResponse:
    def __init__(self, release_second_chunk):
        self.release_second_chunk = release_second_chunk
        self.closed = False

    def __iter__(self):
        yield _Chunk("第一块")
        assert self.release_second_chunk.wait(timeout=1)
        yield _Chunk("第二块")

    def close(self):
        self.closed = True


class _Completions:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        assert kwargs["stream"] is True
        return self.response


class _Llm:
    model_name = "fake-streaming-model"

    def __init__(self, response):
        self.model_client = type(
            "Client", (), {"chat": type("Chat", (), {"completions": _Completions(response)})()}
        )()


def test_customer_agent_streams_final_answer_before_completion_and_archives_full_text():
    release_second_chunk = threading.Event()
    first_chunk_arrived = threading.Event()
    response = _StreamingResponse(release_second_chunk)
    customer_service = _CustomerService()
    agent = CustomerServiceAgent(
        llm=_Llm(response),
        knowledge_tool=_Tool("KnowledgeRetrieval"),
        profile_tool=_Tool("ProfileExtract"),
        holdings_tool=_Tool("HoldingsQuery"),
        customer_service=customer_service,
        work_order_service=object(),
        validate_customer=True,
    )
    agent.classify_intent = lambda _question: ("chitchat", 0.99)
    observed = []
    result_holder = {}

    def run_agent():
        result_holder["result"] = agent.run(
            "你好",
            customer_id=1640,
            session_id="stream-session",
            on_final_chunk=lambda chunk: (observed.append(chunk), first_chunk_arrived.set()),
        )

    worker = threading.Thread(target=run_agent)
    worker.start()
    assert first_chunk_arrived.wait(timeout=1)
    assert worker.is_alive()
    assert observed == ["第一块"]

    release_second_chunk.set()
    worker.join(timeout=1)

    assert result_holder["result"].output == "第一块第二块"
    assert customer_service.archived_messages[-1] == {
        "role": "assistant",
        "content": "第一块第二块",
    }
    assert response.closed is True


def test_chat_service_delivers_customer_chunks_before_agent_run_completes(monkeypatch):
    release_second_chunk = threading.Event()
    run_completed = threading.Event()

    class StreamingAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            emit = kwargs["on_final_chunk"]
            emit("第一块")
            assert release_second_chunk.wait(timeout=1)
            emit("第二块")
            run_completed.set()
            return AgentResult(success=True, output="第一块第二块")

    import app.WealthButler.Agent.customerServiceAgent as agent_module

    monkeypatch.setattr(agent_module, "CustomerServiceAgent", StreamingAgent)

    async def exercise():
        stream = ChatService.route_to_agent(
            agent_type="customer",
            message="你好",
            session_id="service-stream",
            user_id=1640,
        )
        first = await asyncio.wait_for(anext(stream), timeout=1)
        assert run_completed.is_set() is False
        release_second_chunk.set()
        remaining = [chunk async for chunk in stream]
        return first, remaining

    first, remaining = asyncio.run(exercise())

    assert first == "第一块"
    assert remaining == ["第二块"]


def test_obvious_greeting_skips_llm_intent_round_trip():
    release = threading.Event()
    response = _StreamingResponse(release)
    completions = _Completions(response)
    llm = _Llm(response)
    llm.model_client.chat.completions = completions
    agent = CustomerServiceAgent(
        llm=llm,
        knowledge_tool=_Tool("KnowledgeRetrieval"),
        profile_tool=_Tool("ProfileExtract"),
        holdings_tool=_Tool("HoldingsQuery"),
        customer_service=_CustomerService(),
        work_order_service=object(),
        validate_customer=False,
    )

    assert agent.classify_intent("你好，请用一句话介绍你能提供的服务。") == (
        "chitchat",
        0.95,
    )
    assert completions.calls == 0


def test_company_name_question_with_greeting_routes_to_faq_without_llm():
    release = threading.Event()
    response = _StreamingResponse(release)
    completions = _Completions(response)
    llm = _Llm(response)
    llm.model_client.chat.completions = completions
    agent = CustomerServiceAgent(
        llm=llm,
        knowledge_tool=_Tool("KnowledgeRetrieval"),
        profile_tool=_Tool("ProfileExtract"),
        holdings_tool=_Tool("HoldingsQuery"),
        customer_service=_CustomerService(),
        work_order_service=object(),
        validate_customer=False,
    )

    assert agent.classify_intent("你好，请问公司名称是什么？") == ("faq", 0.95)
    assert completions.calls == 0


def test_customer_prompt_distinguishes_platform_company_from_customer_employer():
    assert "默认指本项目运营公司" in SYSTEM_PROMPT
    assert "禁止说“您的公司”" in ANSWER_PROMPT
    assert "公司全称" in ANSWER_PROMPT


def test_customer_fast_paths_follow_business_priority():
    assert CustomerServiceAgent._fast_path_intent("你好，我想了解基金申购费率") == (
        "product_consult", 0.90
    )
    assert CustomerServiceAgent._fast_path_intent("我要办理申购") == (
        "transfer_to_human", 0.98
    )
    assert CustomerServiceAgent._fast_path_intent("我想申购科技创新股票") == (
        "transfer_to_human", 0.98
    )
    assert CustomerServiceAgent._fast_path_intent("请查我的持仓和今日收益") == (
        "holdings_query", 0.98
    )
    assert CustomerServiceAgent._fast_path_intent("投资者适当性有什么要求") == (
        "policy_explain", 0.92
    )
    assert CustomerServiceAgent._fast_path_intent("我的风险等级是什么") == (
        "risk_level_query", 0.99
    )


def test_customer_risk_level_answer_uses_current_assessment(monkeypatch):
    class Assessment:
        risk_level = "C3"
        assessment_time = "2026-08-17 10:00:00"
        valid_until = "2027-08-17 10:00:00"

    monkeypatch.setattr(
        "app.WealthButler.Agent.customerServiceAgent.RiskAssessmentModel.find_valid_by_customer_id",
        lambda _customer_id: Assessment(),
    )
    monkeypatch.setattr(
        "app.WealthButler.Agent.customerServiceAgent.RiskAssessmentModel.find_latest_by_customer_id",
        lambda _customer_id: Assessment(),
    )

    answer, status = CustomerServiceAgent._risk_level_answer(3664)

    assert status == "valid"
    assert "C3" in answer
    assert "2027-08-17" in answer


def test_customer_risk_level_answer_distinguishes_missing_assessment(monkeypatch):
    monkeypatch.setattr(
        "app.WealthButler.Agent.customerServiceAgent.RiskAssessmentModel.find_valid_by_customer_id",
        lambda _customer_id: None,
    )
    monkeypatch.setattr(
        "app.WealthButler.Agent.customerServiceAgent.RiskAssessmentModel.find_latest_by_customer_id",
        lambda _customer_id: None,
    )

    answer, status = CustomerServiceAgent._risk_level_answer(3664)

    assert status == "missing"
    assert "没有可查询的风险测评结果" in answer


def test_customer_profile_extraction_only_runs_for_explicit_preferences():
    assert CustomerServiceAgent._should_extract_profile("公司全称是什么") is False
    assert CustomerServiceAgent._should_extract_profile("请查询今日收益") is False
    assert CustomerServiceAgent._should_extract_profile("我偏好低波动产品") is True


def test_holdings_query_resolver_supports_combined_questions():
    assert CustomerServiceAgent._resolve_holdings_query_types("我的持仓和今日收益") == [
        "holdings_list", "today_profit"
    ]
    assert CustomerServiceAgent._resolve_holdings_query_types("总资产是多少") == ["total_asset"]
    assert CustomerServiceAgent._resolve_holdings_query_types(
        "我的总资产是多少？目前持有几个产品？"
    ) == ["total_asset", "holdings_list"]
    assert CustomerServiceAgent._fast_path_intent("我的账户资金") == (
        "holdings_query", 0.98
    )
    assert CustomerServiceAgent._resolve_holdings_query_types("我的账户资金") == [
        "total_asset"
    ]
    assert CustomerServiceAgent._fast_path_intent("目前持有几个产品？") == (
        "holdings_query", 0.98
    )


def test_holdings_follow_up_resolves_against_previous_answer():
    history = [
        {"role": "user", "content": "我持有几个产品？"},
        {"role": "assistant", "content": "您持有7个产品，总市值615473.11元"},
    ]

    assert CustomerServiceAgent._resolve_contextual_follow_up(
        "分别是什么？", history
    ) == ("holdings_query", 0.99, "我的持仓产品分别是什么")


def test_low_confidence_request_asks_for_clarification_without_work_order():
    release = threading.Event()
    agent = CustomerServiceAgent(
        llm=_Llm(_StreamingResponse(release)),
        knowledge_tool=_Tool("KnowledgeRetrieval"),
        profile_tool=_Tool("ProfileExtract"),
        holdings_tool=_Tool("HoldingsQuery"),
        customer_service=_CustomerService(),
        work_order_service=object(),
        validate_customer=False,
    )
    agent.classify_intent = lambda _question: ("chitchat", 0.2)

    result = agent.run("这个怎么办", customer_id=1640, session_id="clarify-session")

    assert result.output == CLARIFICATION_MESSAGE
    assert result.tool_calls == []
    assert result.metadata["clarification_required"] is True


def test_retrieval_miss_does_not_create_work_order():
    class EmptyKnowledgeTool(_Tool):
        def execute(self, **kwargs):
            return []

    release = threading.Event()
    agent = CustomerServiceAgent(
        llm=_Llm(_StreamingResponse(release)),
        knowledge_tool=EmptyKnowledgeTool("KnowledgeRetrieval"),
        profile_tool=_Tool("ProfileExtract"),
        holdings_tool=_Tool("HoldingsQuery"),
        customer_service=_CustomerService(),
        work_order_service=object(),
        validate_customer=False,
    )
    agent.classify_intent = lambda _question: ("faq", 0.99)

    result = agent.run("未知服务问题", customer_id=1640, session_id="no-hit-session")

    assert result.output == FALLBACK_MESSAGE
    assert all(call["name"] != "WorkOrder" for call in result.tool_calls)
    assert result.metadata["retrieval_below_threshold"] is True


def test_customer_agent_hydrates_bounded_valid_history_from_archive():
    class ArchivedCustomerService(_CustomerService):
        def get_conversation(self, session_id, customer_id):
            assert (session_id, customer_id) == ("restored-session", 1640)
            messages = [
                {"role": "user", "content": f"问题{i}"}
                for i in range(22)
            ]
            messages.extend([
                {"role": "system", "content": "不应恢复"},
                {"role": "assistant", "content": ""},
                "invalid",
            ])
            return {"messages": messages}

    service = ArchivedCustomerService()
    agent = CustomerServiceAgent(
        llm=_Llm(_StreamingResponse(threading.Event())),
        knowledge_tool=_Tool("KnowledgeRetrieval"),
        profile_tool=_Tool("ProfileExtract"),
        holdings_tool=_Tool("HoldingsQuery"),
        customer_service=service,
        work_order_service=object(),
        validate_customer=False,
    )
    agent.classify_intent = lambda _question: ("chitchat", 0.2)

    agent.run("继续", customer_id=1640, session_id="restored-session")

    assert agent.get_session_messages("restored-session")[0]["content"] == "问题5"
    assert len(service.archived_messages) == 19
    assert service.archived_messages[-2]["content"] == "继续"


def test_profile_extraction_failure_does_not_break_answer():
    class FailingProfileTool(_Tool):
        def execute(self, **kwargs):
            raise RuntimeError("profile unavailable")

    agent = CustomerServiceAgent(
        llm=_Llm(_StreamingResponse(threading.Event())),
        knowledge_tool=_Tool("KnowledgeRetrieval"),
        profile_tool=FailingProfileTool("ProfileExtract"),
        holdings_tool=_Tool("HoldingsQuery"),
        customer_service=_CustomerService(),
        work_order_service=object(),
        validate_customer=False,
    )
    agent.classify_intent = lambda _question: ("chitchat", 0.2)

    result = agent.run("我偏好低波动产品", customer_id=1640, session_id="profile-fail")

    assert result.output == CLARIFICATION_MESSAGE
    assert result.metadata["profile_extraction_failed"] is True


def test_archive_failure_does_not_break_answer():
    class FailingArchiveCustomerService(_CustomerService):
        def archive_conversation(self, **kwargs):
            raise RuntimeError("archive unavailable")

    agent = CustomerServiceAgent(
        llm=_Llm(_StreamingResponse(threading.Event())),
        knowledge_tool=_Tool("KnowledgeRetrieval"),
        profile_tool=_Tool("ProfileExtract"),
        holdings_tool=_Tool("HoldingsQuery"),
        customer_service=FailingArchiveCustomerService(),
        work_order_service=object(),
        validate_customer=False,
    )
    agent.classify_intent = lambda _question: ("chitchat", 0.2)

    result = agent.run("不明确的问题", customer_id=1640, session_id="archive-fail")

    assert result.success is True
    assert result.output == CLARIFICATION_MESSAGE
    assert result.metadata["archive_failed"] is True


def test_malformed_knowledge_result_returns_controlled_unavailable_message():
    class MalformedKnowledgeTool(_Tool):
        def execute(self, **kwargs):
            return [{"score": "high", "content": "broken"}]

    agent = CustomerServiceAgent(
        llm=_Llm(_StreamingResponse(threading.Event())),
        knowledge_tool=MalformedKnowledgeTool("KnowledgeRetrieval"),
        profile_tool=_Tool("ProfileExtract"),
        holdings_tool=_Tool("HoldingsQuery"),
        customer_service=_CustomerService(),
        work_order_service=object(),
        validate_customer=False,
    )
    agent.classify_intent = lambda _question: ("faq", 0.99)

    result = agent.run("公司名称", customer_id=1640, session_id="malformed-knowledge")

    assert result.output == KNOWLEDGE_UNAVAILABLE_MESSAGE
    assert result.metadata["knowledge_unavailable"] is True


def test_customer_stream_stops_worker_after_client_disconnect(monkeypatch):
    stopped = threading.Event()
    cancel_called = threading.Event()

    class CancellableAgent:
        def __init__(self, **kwargs):
            pass

        def cancel_stream(self):
            cancel_called.set()

        def run(self, **kwargs):
            kwargs["on_final_chunk"]("第一块")
            while not kwargs["is_cancelled"]():
                time.sleep(0.005)
            stopped.set()
            raise CustomerStreamCancelled()

    import app.WealthButler.Agent.customerServiceAgent as agent_module

    monkeypatch.setattr(agent_module, "CustomerServiceAgent", CancellableAgent)

    async def exercise():
        stream = ChatService.route_to_agent(
            agent_type="customer",
            message="你好",
            session_id="cancelled-stream",
            user_id=1640,
        )
        assert await asyncio.wait_for(anext(stream), timeout=1) == "第一块"
        await stream.aclose()
        assert cancel_called.is_set()
        assert await asyncio.to_thread(stopped.wait, 1)

    asyncio.run(exercise())


def test_customer_stream_does_not_expose_agent_exception(monkeypatch):
    secret = "mysql://admin:super-secret@internal-db/wealth"

    class FailingAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            raise RuntimeError(secret)

    import app.WealthButler.Agent.customerServiceAgent as agent_module

    monkeypatch.setattr(agent_module, "CustomerServiceAgent", FailingAgent)

    async def exercise():
        return [
            chunk
            async for chunk in ChatService.route_to_agent(
                agent_type="customer",
                message="你好",
                session_id="failed-stream",
                user_id=1640,
            )
        ]

    chunks = asyncio.run(exercise())

    assert chunks == ["抱歉，系统出现异常，请稍后重试。"]
    assert secret not in "".join(chunks)
