"""Agent 工具层

职责：
- 实现 10 个 BaseTool 子类（继承 Base.Ai.base.baseTool.BaseTool）
- 封装 Agent 可调用的原子能力（RAG 检索、适当性校验、图谱查询、NL2SQL 等）
- 定义 Function Calling 的 Schema（输入参数、输出格式、调用时机说明）
- 与 Service 层解耦：Tool 是 AI 可调用的接口，Service 是确定性业务逻辑

分层原则：
- 本层是 Agent 与业务逻辑的桥梁，实现 LangChain Tool 协议
- 每个 Tool 是单一原子能力，不包含复杂业务编排（编排在 Agent 层）
- Tool 内部可调用 Service 层获取数据，但不直接操作数据库
- 输入输出必须可序列化为 JSON（Function Calling 协议要求）

10 个 BaseTool 清单（Agent设计文档§7）：

1. KnowledgeRetrieval        RAG 向量检索工具
   - 输入：query(str), collection_name(str), top_k(int)
   - 输出：[{content, score, source}]
   - 调用方：智能客服 Agent
   - 职责：检索 Milvus 三个集合（fin_product/fin_policy/fin_faq）

2. ProfileExtract            画像抽取工具
   - 输入：conversation_text(str), customer_id(int)
   - 输出：{extracted_attrs: {risk_preference, investment_goal, ...}}
   - 调用方：智能客服 Agent
   - 职责：从对话中识别客户属性，写入 memory_units

3. SuitabilityCheck          适当性硬匹配过滤工具
   - 输入：customer_id(int), product_ids(list[int])
   - 输出：{passed: [id1,id2], rejected: [{id, reason}]}
   - 调用方：投顾助手 Agent
   - 职责：四维度硬匹配（需求文档§5.3 第6-9条）

4. GraphQuery                Neo4j 图谱查询工具
   - 输入：cypher_template(str), params(dict)
   - 输出：{nodes: [...], relationships: [...]}
   - 调用方：投顾助手 Agent
   - 职责：多跳查询行业分散度信号、基金-公司关联

5. NL2SQLTool                自然语言转 SQL 工具
   - 输入：nl_query(str), allowed_tables(list[str])
   - 输出：{sql: str, params: dict, estimated_rows: int}
   - 调用方：数据分析 Agent
   - 职责：LLM 生成 SQL，带安全检查（只读、白名单表、禁止 DROP/TRUNCATE）

6. SQLExecutor               SQL 执行工具
   - 输入：sql(str), params(dict), dry_run(bool)
   - 输出：{rows: [...], columns: [...], row_count: int}
   - 调用方：数据分析 Agent
   - 职责：执行 NL2SQL 生成的查询，支持 dry_run 预览

7. NL2APITool                自然语言转 API 调用工具
   - 输入：nl_intent(str), context(dict)
   - 输出：{api_path: str, method: str, payload: dict, confirm_required: bool}
   - 调用方：业务操作 Agent
   - 职责：LLM 映射意图到内部 API（购买/赎回/修改资料），超阈值标记需二次确认

8. APIExecutor               API 执行工具
   - 输入：api_path(str), method(str), payload(dict), confirm_token(str)
   - 输出：{success: bool, result: dict, tx_id: str}
   - 调用方：业务操作 Agent
   - 职责：执行 NL2API 映射的操作，verify confirm_token（二次确认机制）

9. RuleEvaluator             规则引擎评估工具
   - 输入：rule_name(str), context(dict)
   - 输出：{triggered: bool, confidence: float, violated_conditions: [...]}
   - 调用方：风控监测 Agent
   - 职责：评估单条风控规则（反洗钱 8 条 + 风险画像 7 条）

10. EventPublisher           事件发布工具
    - 输入：stream_key(str), event_type(str), payload(dict)
    - 输出：{message_id: str, published_at: int}
    - 调用方：业务操作 Agent（大额交易触发）
    - 职责：封装 Redis Streams XADD，发布到事件总线

典型模块文件：
- knowledgeRetrievalTool.py
- profileExtractTool.py
- suitabilityCheckTool.py
- graphQueryTool.py
- nl2sqlTool.py
- sqlExecutorTool.py
- nl2apiTool.py
- apiExecutorTool.py
- ruleEvaluatorTool.py
- eventPublisherTool.py

BaseTool 实现模板：
    from app.Base.Ai.base.baseTool import BaseTool
    from pydantic import Field

    class KnowledgeRetrievalTool(BaseTool):
        name = "KnowledgeRetrieval"
        description = "检索知识库文档片段，支持产品/政策/FAQ 三个集合"

        # Pydantic Schema 定义（Function Calling 自动传给 LLM）
        query: str = Field(..., description="检索关键词或问题")
        collection_name: str = Field(..., description="集合名称：fin_product/fin_policy/fin_faq")
        top_k: int = Field(default=5, description="返回 Top-K 结果")

        def _run(self, query: str, collection_name: str, top_k: int = 5) -> list[dict]:
            '''同步执行（本期不实现异步）'''
            from app.Base.Client.milvusClient import get_milvus_client
            from WealthButler.Service.knowledgeService import KnowledgeService

            # 调用 Service 层获取向量检索结果
            results = KnowledgeService.retrieve(
                query=query,
                collection=collection_name,
                top_k=top_k
            )

            # 过滤低于阈值的结果（Agent设计文档§2.2）
            threshold = 0.75 if collection_name == 'fin_faq' else 0.7
            filtered = [r for r in results if r['score'] >= threshold]

            return filtered

        async def _arun(self, *args, **kwargs):
            '''异步版本（本期暂不实现，抛出 NotImplementedError）'''
            raise NotImplementedError("异步执行暂不支持")

Schema 与 Prompt 的关系：
- Tool 的 description 和 Field.description 会自动传给 LLM（Function Calling）
- Prompts 层的"③工具使用说明"段落只写"何时调用"，不重复 Schema 细节
- LLM 根据 Schema 自动生成调用参数，不需要在 Prompt 里手动列举参数

调用链：
    Agent.invoke() → LLM 决策调用 Tool → Tool._run() → Service 层 → Models/Client 层

安全约束：
- NL2SQLTool：只允许 SELECT，禁止 INSERT/UPDATE/DELETE/DROP/TRUNCATE
- NL2APITool：超阈值操作必须标记 confirm_required=True
- APIExecutor：verify confirm_token，防止绕过二次确认
- RuleEvaluator：规则表达式禁止 eval()，用安全的规则引擎（如简单的条件树）

与 Base.Ai.base.baseTool 的继承关系：
- Base 层提供 BaseTool 抽象基类，定义 _run()/_arun() 协议
- WealthButler.Tools 实现具体工具，复用 Base 层的 Tool 注册机制
- Agent 构造时传入 tools=[KnowledgeRetrievalTool(), ...]

使用规范：
- Tool 是无状态的，不存储会话信息（会话由 Agent 的 memory 管理）
- 输入输出必须可 JSON 序列化（不能返回 SQLAlchemy Model 对象）
- 错误处理：Tool 内部捕获异常，返回 {error: str}，由 Agent 决定如何处理
- 日志记录：Tool 执行前后记录参数与耗时，供 Metrics 中间件收集
"""

__all__ = [
    "GraphQueryTool",
    "SuitabilityCheckTool"
]

