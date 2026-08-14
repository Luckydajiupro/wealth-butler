"""Agent 中间件层

职责：
- 实现 Agent 调用链的中间件洋葱模型（Logging → Metrics → Safety → MemoryRecall → Eval）
- 为所有 Agent 提供横切关注点：日志记录、性能监控、安全审核、记忆召回、质量评估
- 继承 Base.Ai.base.baseMiddleware.BaseMiddleware 实现 before/after 钩子
- 统一处理 Agent 执行前后的通用逻辑，避免在每个 Agent 内部重复代码

分层原则：
- 本层是 AOP（面向切面编程）模式，与具体 Agent 业务逻辑解耦
- 中间件按洋葱模型执行：请求从外到内穿透，响应从内到外返回
- 中间件可短路：Safety 中间件检测到违规可直接返回拒绝，不执行后续链路
- 复用 Base 层已有中间件，只新增业务特化的 MemoryRecallMiddleware

中间件洋葱顺序（架构设计文档§2.3）：
    外层 ←→ 内层
    Logging → Metrics → Safety → MemoryRecall(新增) → Eval → Agent Core

1. LoggingMiddleware（Base 层已有，复用）
   - Before: 记录 Agent 调用开始（session_id, user_id, agent_type, input）
   - After: 记录 Agent 调用结束（output, token_usage, duration_ms, error）

2. MetricsMiddleware（Base 层已有，复用）
   - Before: 启动计时器
   - After: 记录性能指标（latency、token/s、tool_call_count）到 Prometheus/Redis

3. SafetyMiddleware（Base 层已有，复用）
   - Before: 内容安全审核（敏感词过滤、违规意图检测）
   - After: 输出内容二次审核（防止 LLM 生成违规内容）
   - 短路：检测到违规直接返回拒绝响应，不执行 Agent

4. MemoryRecallMiddleware（WealthButler 新增）
   - Before: 召回相关记忆（短期会话记忆 + 中期画像记忆）注入到 Agent context
   - After: 保存本轮对话到记忆系统（Redis + Milvus）
   - 职责：封装 Base.Service.memoryV1Service 的调用逻辑

5. EvalMiddleware（Base 层已有，复用）
   - Before: 无操作
   - After: 评估 Agent 输出质量（相关性、准确性、合规性）
   - 采样评估：只对 10% 的请求执行（降低性能开销）

典型模块：
- memoryRecallMiddleware.py    记忆召回中间件（本层核心，新增）
- safetyEnhancer.py            安全增强器（可选，扩展 Base 的 SafetyMiddleware）
- rbacMiddleware.py            权限校验中间件（可选，与 Base.Service.authService 集成）

MemoryRecallMiddleware 实现：
    from Base.Ai.base.baseMiddleware import BaseMiddleware
    from Base.Service.memoryV1Service import MemoryV1Service
    from typing import Any

    class MemoryRecallMiddleware(BaseMiddleware):
        '''记忆召回中间件（架构设计文档§2.3）'''

        def __init__(self, memory_service: MemoryV1Service = None):
            self.memory = memory_service or MemoryV1Service()

        def before(self, context: dict) -> dict:
            '''Agent 执行前：召回相关记忆并注入 context

            Args:
                context: {
                    'user_id': int,
                    'session_id': str,
                    'agent_type': str,  # 'customer_service' | 'advisor' | ...
                    'input': str,
                    'metadata': dict
                }

            Returns:
                增强后的 context，新增字段：
                - short_term_memory: list[dict]  # 最近 N 轮对话（TTL 30min）
                - long_term_memory: dict         # 用户画像（风险偏好/投资目标等）
            '''
            user_id = context.get('user_id')
            session_id = context.get('session_id')
            agent_type = context.get('agent_type')

            # 1. 短期记忆：最近 10 轮对话（Redis）
            short_term = self.memory.get_session_history(session_id, limit=10)
            context['short_term_memory'] = short_term

            # 2. 中期记忆：用户画像（MySQL fin_customer_profile）
            if agent_type == 'advisor':
                # 投顾助手需要完整画像（四维度）
                profile = self.memory.get_customer_profile(user_id)
                context['long_term_memory'] = profile
            elif agent_type == 'customer_service':
                # 客服只需要基础画像（风险偏好）
                profile = self.memory.get_customer_profile(user_id, fields=['risk_preference'])
                context['long_term_memory'] = profile
            else:
                context['long_term_memory'] = {}

            # 3. 语义记忆（可选）：向量检索历史相似对话（Milvus）
            # 本期暂不实现，预留接口
            # semantic_memory = self.memory.search_similar_conversations(user_id, context['input'], top_k=3)
            # context['semantic_memory'] = semantic_memory

            return context

        def after(self, context: dict, result: Any) -> Any:
            '''Agent 执行后：保存本轮对话到记忆系统

            Args:
                context: before() 返回的增强 context
                result: Agent 返回的 AgentResult 对象

            Returns:
                不修改 result，原样返回
            '''
            user_id = context.get('user_id')
            session_id = context.get('session_id')
            user_input = context.get('input')
            agent_output = result.output if hasattr(result, 'output') else str(result)

            # 1. 保存到短期记忆（Redis，TTL 30min）
            self.memory.append_message(
                session_id=session_id,
                role='user',
                content=user_input
            )
            self.memory.append_message(
                session_id=session_id,
                role='assistant',
                content=agent_output
            )

            # 2. 异步保存到向量库（Milvus，供语义检索）
            # 由 Base.Api.ai.chatApi 的 @persist_conversation 装饰器统一处理
            # 本中间件不重复实现

            # 3. 提取画像更新（ProfileExtract Tool 已处理，这里不重复）

            return result

        def on_error(self, context: dict, error: Exception) -> None:
            '''Agent 执行出错时的回调（可选）'''
            session_id = context.get('session_id')
            print(f"[MemoryRecallMiddleware] Error in session {session_id}: {error}")
            # 错误日志已由 LoggingMiddleware 记录，这里可选择性补充

中间件链构造示例：
    from Base.Ai.middleware.loggingMiddleware import LoggingMiddleware
    from Base.Ai.middleware.metricsMiddleware import MetricsMiddleware
    from Base.Ai.middleware.safetyMiddleware import SafetyMiddleware
    from WealthButler.Middleware.memoryRecallMiddleware import MemoryRecallMiddleware
    from Base.Ai.middleware.evalMiddleware import EvalMiddleware

    # Agent 构造时传入中间件链
    middlewares = [
        LoggingMiddleware(),
        MetricsMiddleware(),
        SafetyMiddleware(audit_service=audit_service),
        MemoryRecallMiddleware(memory_service=memory_service),
        EvalMiddleware(sample_rate=0.1)  # 10% 采样
    ]

    agent = CustomerServiceAgent(
        llm=llm,
        tools=tools,
        middlewares=middlewares
    )

执行流程：
    1. Request 进入
    2. LoggingMiddleware.before()  → 记录请求日志
    3. MetricsMiddleware.before()  → 启动计时
    4. SafetyMiddleware.before()   → 内容审核（可能短路拒绝）
    5. MemoryRecallMiddleware.before() → 召回记忆，增强 context
    6. EvalMiddleware.before()     → 无操作
    7. **Agent Core 执行**         → LLM 推理 + Tool 调用
    8. EvalMiddleware.after()      → 质量评估
    9. MemoryRecallMiddleware.after() → 保存对话
    10. SafetyMiddleware.after()   → 输出内容审核
    11. MetricsMiddleware.after()  → 记录性能指标
    12. LoggingMiddleware.after()  → 记录响应日志
    13. Response 返回

短路机制示例：
    class SafetyMiddleware(BaseMiddleware):
        def before(self, context: dict) -> dict:
            if self._contains_sensitive_word(context['input']):
                # 短路：直接抛出异常，中止后续执行
                raise SafetyViolationError("输入包含敏感词")
            return context

RBAC 中间件（可选扩展）：
    class RBACMiddleware(BaseMiddleware):
        '''权限校验中间件（与 Base.Service.authService 集成）'''

        def before(self, context: dict) -> dict:
            user_id = context.get('user_id')
            agent_type = context.get('agent_type')

            # 校验用户是否有权限调用该 Agent
            # 例：业务操作 Agent 只允许理财顾问/客户经理调用
            if agent_type == 'operator':
                required_role = ['理财顾问', '客户经理']
                if not self._has_role(user_id, required_role):
                    raise PermissionDeniedError(f"需要角色：{required_role}")

            return context

        def _has_role(self, user_id: int, roles: list[str]) -> bool:
            from Base.Service.authService import AuthService
            user_roles = AuthService.get_user_roles(user_id)
            return any(r in roles for r in user_roles)

与架构设计文档的对应关系：
- §2.3: 中间件洋葱模型与执行顺序
- §8.1: 智能客服 Agent 的短期记忆召回（30min TTL）
- §8.2: 投顾助手 Agent 的中期记忆召回（fin_customer_profile 四维度）
- §5 ADR-5: 记忆分层策略（短期 Redis / 中期 MySQL / 长期 Milvus）

技术约束：
- 中间件应尽量无状态，不依赖外部可变状态
- 中间件执行时间应控制在 <50ms（before + after 总和）
- 短路机制只在 before() 中使用，after() 不应抛出业务异常
- 异步中间件（如 Milvus 向量化）应使用后台任务，不阻塞主流程

使用规范：
- 新增中间件需在架构设计文档 ADR 中说明必要性
- 中间件顺序有依赖关系，不能随意调整（如 MemoryRecall 必须在 Eval 之前）
- 生产环境应通过配置开关控制中间件启用（如 Eval 采样率可调整为 0）
"""

__all__ = ['MemoryRecallMiddleware']
