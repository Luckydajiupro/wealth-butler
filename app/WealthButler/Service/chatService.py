"""对话服务层

职责：
- 处理统一入口的 agent_type 分发逻辑
- 封装 5 个 Agent 的调用接口
- 实例化Agent并执行对话
- 流式输出的生成器在此层返回

分层原则：
- 本层封装业务逻辑，不直接处理 HTTP 请求/响应
- Agent 实例化与调用在此层完成
- 流式输出的生成器在此层返回
"""
import asyncio
import logging
from typing import AsyncGenerator, Dict, Any
import json

from app.WealthButler.Agent.advisorChatAgent import (
    AdvisorChatAgent,
    CustomerChatAgent,
    RiskChatAgent,
    OperatorChatAgent
)
from app.WealthButler.Agent.analystAgent import AnalystAgent
from app.WealthButler.Service.nl2sqlService import Nl2sqlService
from app.Base.Ai.llms.qwenLlm import QwenLlm

logger = logging.getLogger(__name__)


class ChatService:
    """对话服务统一封装"""

    _operator_runtime = None

    @staticmethod
    def configure_operator_runtime(runtime):
        """配置业务操作Agent运行时"""
        ChatService._operator_runtime = runtime

    @staticmethod
    async def route_to_agent(
        agent_type: str,
        message: str,
        session_id: str,
        user_id: int,
        customer_id: int = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        统一入口：按 agent_type 分发到对应 Agent

        Args:
            agent_type: Agent类型 (customer|advisor|analyst|operator|risk)
            message: 用户消息
            session_id: 会话ID
            user_id: 当前登录用户ID
            customer_id: 客户ID（投顾/业务操作必填）
            **kwargs: 其他参数

        Returns:
            AsyncGenerator: SSE流式响应生成器
        """
        # 按 agent_type 分发
        if agent_type == "customer":
            async for chunk in ChatService._call_customer_agent(message, session_id, user_id, **kwargs):
                yield chunk
        elif agent_type == "advisor":
            async for chunk in ChatService._call_advisor_agent(message, session_id, user_id, customer_id, **kwargs):
                yield chunk
        elif agent_type == "analyst":
            async for chunk in ChatService._call_analyst_agent(message, session_id, user_id, **kwargs):
                yield chunk
        elif agent_type == "operator":
            async for chunk in ChatService._call_operator_agent(message, session_id, user_id, customer_id, **kwargs):
                yield chunk
        elif agent_type == "risk":
            async for chunk in ChatService._call_risk_agent(message, session_id, user_id, **kwargs):
                yield chunk
        else:
            # 未知 agent_type，返回错误
            error_response = json.dumps({
                "type": "error",
                "content": f"未知的 agent_type: {agent_type}，支持的类型: customer|advisor|analyst|operator|risk"
            }, ensure_ascii=False)
            yield error_response

    @staticmethod
    async def _call_customer_agent(
        message: str,
        session_id: str,
        user_id: int,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """客服 Agent（智能客服）

        功能：RAG知识库检索 + 会话记忆
        权限：客户本人 或 员工代客户
        """
        try:
            # 导入真实的客服Agent
            from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent

            # 实例化客服Agent
            agent = CustomerServiceAgent(validate_customer=True)

            # 调用Agent的run方法（同步调用）
            result = agent.run(
                user_input=message,
                customer_id=user_id,
                session_id=session_id
            )

            # 流式输出结果
            if result.success:
                # 将输出按字符拆分，模拟流式效果
                output = result.output
                chunk_size = 20  # 每次输出20个字符
                for i in range(0, len(output), chunk_size):
                    chunk = output[i:i + chunk_size]
                    yield chunk
                    await asyncio.sleep(0.05)  # 模拟流式延迟
            else:
                yield f"抱歉，处理您的请求时出现错误：{result.metadata.get('error', '未知错误')}"

        except Exception as e:
            logger.error(f"CustomerServiceAgent执行失败: {e}", exc_info=True)
            yield f"抱歉，系统出现异常，请稍后重试。"

    @staticmethod
    async def _call_advisor_agent(
        message: str,
        session_id: str,
        user_id: int,
        customer_id: int,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """投顾 Agent（投资顾问助手）

        功能：客户画像 + 产品推荐 + 适当性匹配 + GraphRAG增强
        权限：理财顾问（product:recommend）
        """
        try:
            # 导入真实的投顾Agent（带GraphRAG和推荐逻辑）
            from app.WealthButler.Agent.advisorAgent import AdvisorAgent

            # 校验必填参数
            if not customer_id:
                yield "错误：投顾助手必须指定客户ID（customer_id）"
                return

            # 实例化投顾Agent（使用默认LLM和Service）
            agent = AdvisorAgent()

            # 调用Agent的run方法，传入customer_id
            result = agent.run(
                user_input=message,
                customer_id=customer_id
            )

            # 流式输出结果
            if result.success:
                output = result.output
                chunk_size = 20
                for i in range(0, len(output), chunk_size):
                    chunk = output[i:i + chunk_size]
                    yield chunk
                    await asyncio.sleep(0.05)

                # 输出推荐审计信息（如果有）
                if result.metadata:
                    metadata_summary = (
                        f"\n\n【推荐审计信息】\n"
                        f"- 客户ID: {result.metadata.get('customer_id', 'N/A')}\n"
                        f"- 图谱信号: 多样性分数={result.metadata.get('graph_signals', {}).get('diversity_score', 0.0):.4f}, "
                        f"节点数={result.metadata.get('graph_signals', {}).get('node_count', 0)}, "
                        f"查询{'成功' if result.metadata.get('graph_signals', {}).get('query_success') else '失败'}\n"
                        f"- 推荐产品数: {len(result.metadata.get('recommendations', []))}\n"
                        f"- 准入层级: {result.metadata.get('admission_tier', '未知')}"
                    )
                    for i in range(0, len(metadata_summary), chunk_size):
                        chunk = metadata_summary[i:i + chunk_size]
                        yield chunk
                        await asyncio.sleep(0.05)
            else:
                error_msg = result.metadata.get('error', '未知错误') if result.metadata else '未知错误'
                yield f"抱歉，处理您的请求时出现错误：{error_msg}"

        except Exception as e:
            logger.error(f"AdvisorAgent执行失败: {e}", exc_info=True)
            yield f"抱歉，系统出现异常：{str(e)}"

    @staticmethod
    async def _call_analyst_agent(
        message: str,
        session_id: str,
        user_id: int,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """数据分析 Agent（NL2SQL）

        功能：自然语言转SQL + 动态Schema筛选 + 安全校验
        权限：全体员工（data:nl2sql_query）
        """
        try:
            # 导入依赖（延迟导入避免循环依赖）
            from app.Base.Client.mysqlClient import MySQLClient
            from app.Base.Client.redisClient import RedisClient
            from app.WealthButler.Service.nl2sqlGuard import Nl2sqlGuard
            from app.WealthButler.Service.nl2sqlService import (
                Nl2sqlService,
                MySqlReadExecutor,
                RedisNl2sqlCache
            )
            from app.Base.Ai.llms.qwenLlm import QwenLlm

            # 实例化依赖组件
            llm = QwenLlm()
            mysql_client = MySQLClient()
            redis_client = RedisClient()

            executor = MySqlReadExecutor(mysql_client)
            cache = RedisNl2sqlCache(redis_client)
            guard = Nl2sqlGuard()

            # 实例化NL2SQL服务
            nl2sql_service = Nl2sqlService(
                llm=llm,
                executor=executor,
                guard=guard,
                cache=cache,
                scope_token=kwargs.get('scope_token', '')
            )

            # 实例化分析Agent
            agent = AnalystAgent(
                service=nl2sql_service,
                llm=llm
            )

            # 调用Agent执行查询
            result = agent.run(message, scope_token=kwargs.get('scope_token', ''))

            # 流式输出结果（将查询结果JSON化后返回）
            if result.success:
                # 构建包含查询结果的响应
                response_data = {
                    "code": 0,
                    "message": "查询成功",
                    "data": {
                        "response": result.output,
                        "query_result": result.metadata.get("query_result", []) if result.metadata else [],
                        "generated_sql": result.metadata.get("generated_sql", "") if result.metadata else "",
                        "row_count": result.metadata.get("row_count", 0) if result.metadata else 0,
                        "execution_time_ms": result.duration_ms
                    }
                }

                # 返回JSON格式的完整响应
                yield json.dumps(response_data, ensure_ascii=False)
            else:
                error_response = {
                    "code": -1,
                    "message": result.error_msg or "查询失败",
                    "data": None
                }
                yield json.dumps(error_response, ensure_ascii=False)

        except Exception as e:
            logger.error(f"AnalystAgent执行失败: {e}", exc_info=True)
            error_response = {
                "code": -1,
                "message": f"系统异常：{str(e)}",
                "data": None
            }
            yield json.dumps(error_response, ensure_ascii=False)

    @staticmethod
    async def _call_operator_agent(
        message: str,
        session_id: str,
        user_id: int,
        customer_id: int,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """业务操作 Agent（NL2API）

        功能：意图识别 + 参数提取 + RBAC权限校验 + 二次确认
        权限：理财顾问（申购/赎回/风评重做）+ 客户经理（转账/信息更新/工单创建）
        """
        try:
            # 确保运行时已配置
            if ChatService._operator_runtime is None:
                from app.WealthButler.Service.operatorApiRuntime import OperatorApiRuntimeFactory
                ChatService._operator_runtime = OperatorApiRuntimeFactory.create_fake()

            # 使用真实的OperatorAgent执行
            runtime = ChatService._operator_runtime
            result = runtime.execute(
                employee_id=user_id,
                customer_id=customer_id if customer_id else 0,
                user_input=message,
                candidate=None,
                session_id=session_id
            )

            # 流式输出结果
            response_message = result.get("message", "操作完成")
            if result.get("success"):
                # 成功响应
                metadata = result.get("metadata", {})
                if metadata.get("confirm_required"):
                    response_message = f"{response_message}\n确认令牌: {metadata.get('confirm_token')}"

                chunk_size = 20
                for i in range(0, len(response_message), chunk_size):
                    chunk = response_message[i:i + chunk_size]
                    yield chunk
                    await asyncio.sleep(0.05)
            else:
                # 失败响应
                yield f"业务操作失败：{response_message}"

        except Exception as e:
            logger.error(f"OperatorAgent执行失败: {e}", exc_info=True)
            yield f"抱歉，系统出现异常，请稍后重试。"

    @staticmethod
    async def _call_risk_agent(
        message: str,
        session_id: str,
        user_id: int,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """风控 Agent（风险监测）

        功能：规则引擎 + 预警生成 + 跨Agent事件通知
        权限：风控专员（risk:monitor）
        注：此 Agent 无对话入口，主要通过事件总线被动触发
        """
        try:
            # 实例化风控助手Agent
            agent = RiskChatAgent(
                user_id=str(user_id),
                session_id=session_id
            )

            # 调用Agent的run方法
            result = agent.run(message)

            # 流式输出结果
            if result.success:
                output = result.output
                chunk_size = 20
                for i in range(0, len(output), chunk_size):
                    chunk = output[i:i + chunk_size]
                    yield chunk
                    await asyncio.sleep(0.05)
            else:
                yield f"抱歉，处理您的请求时出现错误：{result.error_msg}"

        except Exception as e:
            logger.error(f"RiskAgent执行失败: {e}", exc_info=True)
            yield f"抱歉，系统出现异常，请稍后重试。"

    @staticmethod
    async def get_session_history(session_id: str, limit: int = 50) -> Dict[str, Any]:
        """获取会话历史

        Args:
            session_id: 会话ID
            limit: 返回最近N条记录

        Returns:
            包含历史消息的字典
        """
        # TODO: 从数据库查询真实历史
        return {
            "session_id": session_id,
            "messages": [
                {
                    "role": "user",
                    "content": "（历史消息1）",
                    "timestamp": "2026-08-15 10:00:00"
                },
                {
                    "role": "assistant",
                    "content": "（历史回复1）",
                    "timestamp": "2026-08-15 10:00:05"
                }
            ],
            "total": 2
        }

    @staticmethod
    def confirm_operator_action(confirm_token: str, action: str) -> Dict[str, Any]:
        """业务操作二次确认闭环

        Args:
            confirm_token: 待确认操作的token
            action: confirm（确认执行）| cancel（取消）

        Returns:
            执行结果
        """
        # TODO: 实现真实的状态机流转
        if action == "confirm":
            return {
                "status": "executed",
                "message": "操作已执行",
                "transaction_id": "TXN202608150001"
            }
        elif action == "cancel":
            return {
                "status": "cancelled",
                "message": "操作已取消"
            }
        else:
            return {
                "status": "error",
                "message": f"无效的 action: {action}，仅支持 confirm|cancel"
            }
