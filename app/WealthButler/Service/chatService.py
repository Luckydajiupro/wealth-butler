"""对话服务层

职责：
- 处理统一入口的 agent_type 分发逻辑
- 封装 4 个对话 Agent 的调用接口（风控 Agent 仅由事件触发）
- 实例化Agent并执行对话
- 流式输出的生成器在此层返回

分层原则：
- 本层封装业务逻辑，不直接处理 HTTP 请求/响应
- Agent 实例化与调用在此层完成
- 流式输出的生成器在此层返回
"""
import asyncio
import logging
import threading
from typing import AsyncGenerator, Dict, Any
import json

logger = logging.getLogger(__name__)


class ChatService:
    """对话服务统一封装"""

    _operator_runtime = None

    @staticmethod
    def _publish_customer_confirmation(customer_id: int, pending) -> None:
        """Expose an operator draft to the owning customer for final confirmation."""
        from app.Base.Client.redisClient import redis_client

        command = pending.command
        notification = {
            "id": f"operation-confirmation:{pending.token}",
            "type": "operation_confirmation",
            "customer_id": customer_id,
            "confirm_token": pending.token,
            "operation_intent": command.intent,
            "operation_params": command.params,
            "status": pending.status,
            "operator_id": pending.employee_id,
            "message": "客户经理已完成业务核验，请核对本次模拟操作并进行二次确认。",
            "created_at": pending.created_at.isoformat(),
            "expires_at": pending.expires_at.isoformat(),
        }
        key = f"notifications:user:{customer_id}"
        redis_client.client.lpush(
            key,
            json.dumps(notification, ensure_ascii=False, default=str),
        )
        redis_client.client.ltrim(key, 0, 199)

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
            stream = ChatService._call_customer_agent(message, session_id, user_id, **kwargs)
            try:
                async for chunk in stream:
                    yield chunk
            finally:
                await stream.aclose()
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
            yield json.dumps({
                "type": "error",
                "code": "RISK_CHAT_NOT_SUPPORTED",
                "content": "风控 Agent 仅通过事件总线和定时任务触发，不提供对话入口",
            }, ensure_ascii=False)
        else:
            # 未知 agent_type，返回错误
            error_response = json.dumps({
                "type": "error",
                "content": f"未知的 agent_type: {agent_type}，支持的类型: customer|advisor|analyst|operator"
            }, ensure_ascii=False)
            yield error_response

    @staticmethod
    async def _call_customer_agent(
        message: str,
        session_id: str,
        user_id: int,
        customer_id: int = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """客服 Agent（智能客服）

        功能：RAG知识库检索 + 会话记忆
        权限：客户本人
        """
        from app.WealthButler.Agent.customerServiceAgent import (
            CustomerServiceAgent,
            CustomerStreamCancelled,
        )

        agent = CustomerServiceAgent(validate_customer=True)
        actual_customer_id = customer_id if customer_id is not None else user_id
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        cancelled = threading.Event()
        emitted = False

        def enqueue(kind: str, payload: Any = None) -> None:
            if cancelled.is_set() and kind == "chunk":
                return
            try:
                loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))
            except RuntimeError:
                # 事件循环已关闭时丢弃迟到的线程通知。
                return

        def run_agent() -> None:
            try:
                result = agent.run(
                    user_input=message,
                    customer_id=actual_customer_id,
                    session_id=session_id,
                    on_final_chunk=lambda chunk: enqueue("chunk", chunk),
                    is_cancelled=cancelled.is_set,
                )
                enqueue("result", result)
            except CustomerStreamCancelled:
                enqueue("cancelled")
            except Exception as error:
                enqueue("error", error)
            finally:
                enqueue("end")

        worker = asyncio.create_task(asyncio.to_thread(run_agent))
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "chunk":
                    emitted = True
                    yield payload
                elif kind == "result":
                    if not payload.success:
                        yield "抱歉，系统出现异常，请稍后重试。"
                    elif not emitted and payload.output:
                        # 工具直接生成的最终回答没有 LLM token 流，作为单帧返回。
                        yield payload.output
                elif kind == "error":
                    logger.error("CustomerServiceAgent执行失败: %s", payload, exc_info=payload)
                    yield "抱歉，系统出现异常，请稍后重试。"
                elif kind == "end":
                    break
        finally:
            cancelled.set()
            cancel_stream = getattr(agent, "cancel_stream", None)
            if callable(cancel_stream):
                cancel_stream()
            if not worker.done():
                worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

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
        if not customer_id:
            yield "错误：投顾助手必须指定客户ID（customer_id）"
            return

        try:
            from app.WealthButler.Agent.advisorAgent import AdvisorAgent

            agent = AdvisorAgent(user_id=str(user_id), session_id=session_id)
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        agent.run,
                        user_input=message,
                        customer_id=customer_id,
                    ),
                    timeout=60.0,
                )
            except asyncio.TimeoutError:
                yield "抱歉，投顾助手响应超时，请稍后重试。"
                return

            if not result.success:
                error_msg = result.metadata.get("error", "未知错误") if result.metadata else "未知错误"
                yield f"抱歉，处理您的请求时出现错误：{error_msg}"
                return

            output = result.output
            chunk_size = 20
            for i in range(0, len(output), chunk_size):
                yield output[i:i + chunk_size]
                await asyncio.sleep(0.05)

            if result.metadata and result.metadata.get("audit_applicable"):
                logger.info(
                    "AdvisorAgent审计: customer_id=%s kind=%s products=%s admission=%s graph=%s",
                    result.metadata.get("customer_id"),
                    result.metadata.get("audit_kind"),
                    len(result.metadata.get("recommendations", [])),
                    result.metadata.get("admission_tier"),
                    result.metadata.get("graph_signals", {}),
                )
        except Exception:
            logger.exception("AdvisorAgent执行失败")
            yield "抱歉，投顾助手暂时不可用，请稍后重试。"

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
            from app.WealthButler.Agent.analystAgent import AnalystAgent
            from app.Base.Ai.llms.deepseekLlm import get_default_deepseek_llm

            # 实例化依赖组件
            # 复用启动阶段按 settings/.env 完整装配的模型实例。
            # 直接 DeepSeekLlm() 不会自动注入 base_url，会导致分析服务运行时失败。
            llm = get_default_deepseek_llm()
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

            # 调用Agent执行查询（在线程池中运行以避免阻塞事件循环）
            # 添加10秒超时保护
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        agent.run,
                        message,
                        scope_token=kwargs.get('scope_token', '')
                    ),
                    timeout=10.0
                )
            except asyncio.TimeoutError:
                error_response = {
                    "code": -1,
                    "message": "查询超时（可能是SQL生成或执行耗时过长），请简化查询条件",
                    "data": None
                }
                yield json.dumps(error_response, ensure_ascii=False, default=str)
                return

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
                yield json.dumps(response_data, ensure_ascii=False, default=str)
            else:
                error_response = {
                    "code": -1,
                    "message": result.error_msg or "查询失败",
                    "data": None
                }
                yield json.dumps(error_response, ensure_ascii=False, default=str)

        except Exception as e:
            logger.error(f"AnalystAgent执行失败: {e}", exc_info=True)
            error_response = {
                "code": -1,
                "message": "数据分析服务暂时不可用，请稍后重试",
                "data": None
            }
            yield json.dumps(error_response, ensure_ascii=False, default=str)

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
        权限：客户经理/运营（申购、赎回、转账、信息更新和产品查询）
        """
        try:
            # 确保运行时已配置
            if ChatService._operator_runtime is None:
                yield "业务操作失败：正式业务操作运行时尚未配置"
                return

            # 使用真实的OperatorAgent执行
            runtime = ChatService._operator_runtime
            result = await asyncio.to_thread(
                runtime.execute,
                employee_id=user_id,
                customer_id=customer_id,
                user_input=message,
                candidate=None,
                session_id=session_id,
            )

            # 流式输出结果
            response_message = ChatService._format_operator_response(result)
            if result.get("success"):
                # 成功响应
                metadata = result.get("metadata", {})
                if metadata.get("confirm_required"):
                    pending = runtime.service.confirmation_service.get_pending(metadata.get("confirm_token"))
                    if pending is not None:
                        try:
                            ChatService._publish_customer_confirmation(customer_id, pending)
                        except Exception:
                            logger.exception("客户二次确认通知发布失败: customer_id=%s", customer_id)
                    response_message = f"{response_message}\n确认令牌: {metadata.get('confirm_token')}"

                chunk_size = 20
                for i in range(0, len(response_message), chunk_size):
                    chunk = response_message[i:i + chunk_size]
                    yield chunk
                    await asyncio.sleep(0.05)
            else:
                # 失败响应
                yield f"业务操作失败：{response_message}"

        except Exception:
            logger.exception("OperatorAgent执行失败")
            yield "抱歉，系统出现异常，请稍后重试。"

    @staticmethod
    def _format_operator_response(result: Dict[str, Any]) -> str:
        """Turn structured operator results into useful workbench text."""
        message = str(result.get("message") or "操作完成")
        data = result.get("data")
        if not isinstance(data, dict):
            return message
        product = data if result.get("code") == "PRODUCT_FOUND" else None
        if result.get("code") == "PRODUCT_LISTED":
            items = data.get("items")
            if isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict):
                product = items[0]
        if product is None:
            return message

        def display(value: Any, fallback: str = "未提供") -> str:
            return fallback if value in (None, "") else str(value)

        minimum = product.get("min_investment")
        minimum_text = f"{float(minimum):,.2f} 元" if minimum not in (None, "") else "未提供"
        nav = product.get("nav")
        nav_text = f"{float(nav):,.4f}" if nav not in (None, "") else "未提供"
        redemption_days = product.get("redemption_period_days")
        redemption_text = f"{redemption_days} 天" if redemption_days not in (None, "") else "未提供"
        return "\n".join([
            f"产品名称：{display(product.get('product_name'))}",
            f"产品代码：{display(product.get('product_code'))}",
            f"产品类型：{display(product.get('product_type'))}",
            f"风险等级：{display(product.get('risk_level'))}",
            f"最新净值：{nav_text}（{display(product.get('nav_date'), '日期未提供')}）",
            f"起购金额：{minimum_text}",
            f"赎回期限：{redemption_text}",
            f"在售状态：{display(product.get('status'))}",
        ])

    @staticmethod
    def confirm_operator_action(employee_id: int, confirm_token: str, action: str) -> Dict[str, Any]:
        """业务操作二次确认闭环

        Args:
            confirm_token: 待确认操作的token
            action: confirm（确认执行）| cancel（取消）

        Returns:
            执行结果
        """
        runtime = ChatService._operator_runtime
        if runtime is None:
            return {
                "success": False,
                "code": "OPERATOR_RUNTIME_UNAVAILABLE",
                "message": "正式业务操作运行时尚未配置",
                "data": {},
                "metadata": {},
            }
        from app.WealthButler.Service.operatorApiRuntime import to_json_safe_result

        return to_json_safe_result(runtime.confirm(employee_id, confirm_token, action))
