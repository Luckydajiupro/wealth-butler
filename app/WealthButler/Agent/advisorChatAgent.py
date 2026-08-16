# -*- coding: utf-8 -*-
"""advisorChatAgent.py — 投顾助手对话Agent（理财顾问工作台专用）

功能：
- 为理财顾问提供产品推荐、客户分析、投资咨询等智能辅助
- 支持多轮对话，保持上下文记忆
- 基于客户画像和产品库提供个性化建议

技术栈：
- 继承 ReActAgent，支持工具调用（产品查询、客户画像查询等）
- 使用 DBMemory 持久化对话历史
- 调用 QwenLlm 作为基座模型
"""

from typing import Optional, Any
from app.Base.Ai.base.baseAgent import ReActAgent, DBMemory
from app.Base.Ai.llms.qwenLlm import QwenLlm


class AdvisorChatAgent(ReActAgent):
    """投顾助手对话Agent（理财顾问专用）"""

    def __init__(
        self,
        user_id: str,
        session_id: str,
        customer_id: Optional[int] = None,
        **kwargs
    ):
        """
        初始化投顾助手Agent

        Args:
            user_id: 理财顾问的用户ID
            session_id: 会话ID
            customer_id: 可选的客户ID（用于针对特定客户提供建议）
        """
        self.customer_id = customer_id

        # 构建系统提示词
        system_prompt = self._build_system_prompt()

        # 初始化LLM
        llm = QwenLlm()

        # 初始化数据库记忆
        memory = DBMemory(user_id=user_id, session_id=session_id, max_turns=10)

        super().__init__(
            llm=llm,
            name="AdvisorChatAgent",
            system_prompt=system_prompt,
            tools=[],  # TODO: 后续添加工具（产品查询、客户画像查询等）
            memory=memory,
            user_id=user_id,
            session_id=session_id,
            max_iterations=5,
            **kwargs
        )

    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        base_prompt = """你是智能财富管家系统的投顾助手，专门为理财顾问提供智能辅助服务。

【你的职责】
1. 产品推荐：根据客户画像推荐合适的理财产品
2. 客户分析：解读客户的风险等级、投资偏好、资产状况
3. 投资咨询：回答理财顾问关于产品、市场、政策的问题
4. 业务指导：协助理财顾问处理客户需求、工单流程

【你的能力】
- 了解公司的理财产品库（基金、保险、信托等）
- 掌握客户适当性管理要求（风险等级匹配）
- 熟悉投资组合配置理论和实践
- 能解读市场趋势和产品特点

【交互原则】
1. 专业但友好，使用理财顾问习惯的术语
2. 给出具体建议时注明依据（如风险等级、产品特性）
3. 涉及合规问题时提醒注意事项
4. 不确定时明确说明，避免误导

【重要提醒】
- 你是辅助工具，最终决策由理财顾问和客户共同做出
- 所有建议仅供参考，不构成投资承诺"""

        if self.customer_id:
            base_prompt += f"\n\n【当前上下文】\n正在为客户ID={self.customer_id}提供服务建议"

        return base_prompt


class CustomerChatAgent(ReActAgent):
    """客户端智能客服Agent"""

    def __init__(self, user_id: str, session_id: str, **kwargs):
        system_prompt = """你是智能财富管家系统的客服助手，为客户提供投资咨询和产品查询服务。

【你的职责】
1. 解答客户关于理财产品的问题
2. 协助客户了解账户资产和持仓情况
3. 解释投资术语和风险提示
4. 引导客户联系专业理财顾问

【交互原则】
1. 友好、耐心、专业
2. 使用通俗易懂的语言，避免过多术语
3. 涉及具体投资建议时，建议联系理财顾问
4. 保护客户隐私，不泄露敏感信息"""

        llm = QwenLlm()
        memory = DBMemory(user_id=user_id, session_id=session_id, max_turns=10)

        super().__init__(
            llm=llm,
            name="CustomerChatAgent",
            system_prompt=system_prompt,
            tools=[],
            memory=memory,
            user_id=user_id,
            session_id=session_id,
            max_iterations=5,
            **kwargs
        )


class RiskChatAgent(ReActAgent):
    """风控专员对话Agent"""

    def __init__(self, user_id: str, session_id: str, **kwargs):
        system_prompt = """你是智能财富管家系统的风控助手，为风控专员提供风险分析和预警建议。

【你的职责】
1. 风险分析：解读客户交易、持仓的风险状况
2. 预警建议：针对风险预警提供处置建议
3. 规则解读：解释风控规则和合规要求
4. 趋势分析：分析市场风险和客户风险趋势

【交互原则】
1. 专业、严谨、客观
2. 量化风险指标，给出明确结论
3. 提供可操作的风险处置建议
4. 标注风险等级和紧急程度"""

        llm = QwenLlm()
        memory = DBMemory(user_id=user_id, session_id=session_id, max_turns=10)

        super().__init__(
            llm=llm,
            name="RiskChatAgent",
            system_prompt=system_prompt,
            tools=[],
            memory=memory,
            user_id=user_id,
            session_id=session_id,
            max_iterations=5,
            **kwargs
        )


class OperatorChatAgent(ReActAgent):
    """业务操作助手Agent"""

    def __init__(self, user_id: str, session_id: str, customer_id: Optional[int] = None, **kwargs):
        self.customer_id = customer_id

        system_prompt = f"""你是智能财富管家系统的业务操作助手，协助员工执行业务操作。

【你的职责】
1. 理解操作意图：申购、赎回、转账、信息更新等
2. 参数提取：从自然语言中提取操作所需参数
3. 操作引导：提示操作步骤和注意事项
4. 结果确认：告知操作结果和后续跟进

【交互原则】
1. 明确、简洁、准确
2. 关键操作前再次确认参数
3. 提醒合规要求和风险提示
4. 操作失败时给出原因和解决方案

【当前上下文】
{'正在为客户ID=' + str(customer_id) + '执行业务操作' if customer_id else '等待指定客户ID'}"""

        llm = QwenLlm()
        memory = DBMemory(user_id=user_id, session_id=session_id, max_turns=10)

        super().__init__(
            llm=llm,
            name="OperatorChatAgent",
            system_prompt=system_prompt,
            tools=[],
            memory=memory,
            user_id=user_id,
            session_id=session_id,
            max_iterations=5,
            **kwargs
        )
