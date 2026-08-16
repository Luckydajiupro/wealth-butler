"""智能 Agent 层

职责：
- 实现 5 大智能体的核心逻辑（基于 LangGraph/LangChain 或自定义 Agent 框架）
- 封装复杂的多轮对话、决策推理、工具调用流程
- 与向量数据库（Milvus）、知识图谱（Neo4j）交互
- 调用 LLM 完成自然语言理解、生成、推理任务

分层原则：
- 本层是"智能决策层"，包含 AI 推理与多步骤编排
- 复用 Base.Ai.llms 的 LLM 封装（QwenLlm、DeepseekLlm）
- 使用 Base.Service.memoryV1Service 管理对话记忆
- 可以调用 Service 层获取业务数据，但不直接操作数据库

5 大智能体设计：
1. advisorChatAgent.py      投顾助手 Agent（理财顾问对话）
   - 多轮对话管理、产品推荐、客户分析
   - 结合客户画像提供个性化建议

2. advisorChatAgent.py      客户服务 Agent
   - 智能客服、FAQ 检索、知识问答
   - 基于向量数据库的语义检索

3. analystAgent.py          数据分析 Agent
   - NL2SQL、数据查询、结果解读
   - 安全校验、权限控制

4. advisorChatAgent.py      业务操作 Agent
   - NL2API、意图识别、参数提取
   - 二次确认、权限校验

5. advisorChatAgent.py      风控助手 Agent
   - 风险分析、预警建议、规则解读
   - 事件驱动、跨Agent通知
"""

from app.WealthButler.Agent.analystAgent import AnalystAgent
from app.WealthButler.Agent.advisorAgent import AdvisorAgent
from app.WealthButler.Agent.advisorChatAgent import (
    AdvisorChatAgent,
    CustomerChatAgent,
    RiskChatAgent,
    OperatorChatAgent
)

__all__ = [
    "AnalystAgent",
    "AdvisorAgent",
    "AdvisorChatAgent",
    "CustomerChatAgent",
    "RiskChatAgent",
    "OperatorChatAgent"
]

