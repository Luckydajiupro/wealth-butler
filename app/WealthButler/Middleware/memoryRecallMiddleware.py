"""MemoryRecallMiddleware —— 记忆召回中间件（组E，需求 F4.2）

洋葱模型位置（架构设计 §2.3）：Logging → Metrics → Safety → **MemoryRecall** → Eval。
process_request（进入时）召回三层记忆并注入 AgentContext.metadata；process_response
（返回时，洋葱逆向）只保存本轮对话消息到短期记忆——**不**执行会话归档
（归档由调用方显式调 MemoryService.archive_session，EB-E-09）、**不**重复 chatApi
@persist_conversation 装饰器已负责的 Milvus/会话持久化。

真实基类合同（以仓库实际代码为准，app/Base/Ai/middlewares/base.py）：
    Middleware.process_request(ctx: AgentContext, next: Callable)  # 必须 await next()
    Middleware.process_response(ctx: AgentContext)
本模块不创建第二套 Middleware/MiddlewareChain/AgentContext；
app/WealthButler/Middleware/__init__.py 中的 BaseMiddleware 示例只是历史设计说明，
不是已实现基类，一律不使用。

fail-open 策略：记忆召回/保存异常一律记录结构化 degraded/error 状态后继续 Agent
核心流程，不抛出异常阻断；保存失败绝不覆盖 ctx.output。

AgentContext.metadata 兼容读取顺序（EB-E-05，仓库现有调用方无统一字段名，
Base 生态仅 metrics.py 使用 user_id/session_id，见组E报告）：
- query       : ctx.user_input → metadata["query"] → metadata["input"] → ""
- session_id  : metadata["session_id"]
- user_id     : metadata["user_id"]
- agent_type  : ctx.agent_name → metadata["agent_type"]
- customer_id : metadata["customer_id"] → （仅 agent_type=="customer" 时）
                metadata["user_id"]（客服链路登录用户即客户本人）
注入字段（canonical，任务约定）：ctx.metadata["memory_context"] =
    {short_term, mid_term, long_term, ranked, status, errors}
本模块额外携带 graph/merged 两个扩展键（长期图谱结果与三源合并结果），
注入时保留 metadata 其他键原样、已存在的 memory_context 不被覆盖。
"""
from typing import Any, Callable, Dict, Optional

from app.Base.Ai.middlewares.base import AgentContext, Middleware
from app.WealthButler.Service.memoryService import MemoryService

# 中间件默认配置（可注入覆盖；全部无外部连接，导入安全）
DEFAULT_CONFIG: Dict[str, Any] = {
    "short_term_limit": 10,      # 短期记忆读取条数（服务端上限 50）
    "long_term_top_k": 5,        # 长期记忆 TopK
    "long_term_threshold": 0.6,  # 长期记忆相似度阈值
    "save_session_messages": True,  # process_response 是否保存本轮消息到短期记忆
}

# memory_context 注入结构的 canonical 键（任务第十一节约定）+ 组E扩展键
MEMORY_CONTEXT_KEYS = ("short_term", "mid_term", "long_term", "ranked", "status", "errors")
MEMORY_CONTEXT_EXTRA_KEYS = ("graph", "merged")


class MemoryRecallMiddleware(Middleware):
    """记忆召回中间件（真实继承 app.Base.Ai.middlewares.base.Middleware）。

    构造不建立任何外部连接：memory_service 缺省时惰性构造默认 MemoryService
    （其默认 provider 同样惰性），保证"导入模块/实例化不因外部服务不可用而失败"。
    单元测试注入 memory_service 或 memory_service_factory（MOCK_ONLY）。
    """

    def __init__(self, memory_service=None, memory_service_factory=None,
                 config: Optional[Dict[str, Any]] = None):
        # 未注入 service 时用 factory 惰性构造（默认 factory=MemoryService）
        self._memory_service = memory_service
        self._service_factory = memory_service_factory or MemoryService
        self._service_instance = None
        self._config = dict(DEFAULT_CONFIG)
        if config:
            self._config.update(config)

    # ------------------------------------------------------------------
    # 服务惰性获取（首轮请求才实例化，导入期零连接）
    # ------------------------------------------------------------------
    def _get_service(self) -> MemoryService:
        if self._service_instance is None:
            self._service_instance = self._memory_service or self._service_factory()
        return self._service_instance

    # ------------------------------------------------------------------
    # AgentContext 信息提取（兼容读取顺序，EB-E-05）
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_context(ctx: AgentContext) -> Dict[str, Any]:
        metadata = ctx.metadata if isinstance(ctx.metadata, dict) else {}
        user_id = metadata.get("user_id")
        agent_type = ctx.agent_name or metadata.get("agent_type")
        session_id = metadata.get("session_id")
        query = ctx.user_input or metadata.get("query") or metadata.get("input") or ""
        customer_id = metadata.get("customer_id")
        # 客服链路中登录用户即客户本人（明确登记的兼容回退，非静默猜测）
        if customer_id is None and agent_type == "customer" and \
                isinstance(user_id, int) and not isinstance(user_id, bool):
            customer_id = user_id
        return {
            "customer_id": customer_id,
            "session_id": session_id,
            "user_id": user_id,
            "agent_type": agent_type,
            "query": query,
        }

    @staticmethod
    def _project(result: Dict[str, Any]) -> Dict[str, Any]:
        """把 MemoryService.recall 的完整结果投影为 memory_context 注入结构。"""
        long_layer = result.get("long_term") or {}
        return {
            "short_term": (result.get("short_term") or {}).get("messages", []),
            "mid_term": (result.get("mid_term") or {}).get("units", []),
            "long_term": long_layer.get("items", []),
            "graph": long_layer.get("graph", []),
            "ranked": result.get("ranked", []),
            "merged": result.get("merged", []),
            "status": result.get("status", "error"),
            "errors": list(result.get("errors", [])),
        }

    # ------------------------------------------------------------------
    # 进入：召回 + 注入 + 继续洋葱链
    # ------------------------------------------------------------------
    async def process_request(self, ctx: AgentContext, next: Callable) -> None:
        info = self._extract_context(ctx)
        try:
            service = self._get_service()
            result = service.recall(
                customer_id=info["customer_id"],
                query=info["query"],
                session_id=info["session_id"],
                agent_type=info["agent_type"],
                short_term_limit=self._config.get("short_term_limit", 10),
                long_term_top_k=self._config.get("long_term_top_k", 5),
                long_term_threshold=self._config.get("long_term_threshold", 0.6),
            )
            memory_context = self._project(result)
        except Exception as exc:
            # fail-open：记忆不可用不得阻断 Agent 核心流程
            memory_context = {
                "short_term": [], "mid_term": [], "long_term": [],
                "graph": [], "ranked": [], "merged": [],
                "status": "error",
                "errors": [f"MemoryRecallMiddleware 记忆召回异常（fail-open）: {exc}"],
            }
        if not isinstance(ctx.metadata, dict):
            ctx.metadata = {}
        # 只注入 canonical 键；不覆盖调用方已注入的 memory_context 及其他 metadata 键
        ctx.metadata.setdefault("memory_context", memory_context)
        await next()

    # ------------------------------------------------------------------
    # 返回（洋葱逆向）：只保存本轮消息，失败不阻断、不覆盖输出
    # ------------------------------------------------------------------
    async def process_response(self, ctx: AgentContext) -> None:
        if not self._config.get("save_session_messages", True):
            return
        if not isinstance(ctx.metadata, dict):
            ctx.metadata = {}
        session_id = ctx.metadata.get("session_id")
        if not session_id:
            return
        save_errors: list = []
        try:
            service = self._get_service()
            for role, content in (("user", ctx.user_input), ("assistant", ctx.output)):
                if content:
                    res = service.append_session_message(
                        session_id,
                        {"role": role, "content": content, "request_id": ctx.request_id},
                    )
                    if res.get("status") != "ok":
                        save_errors.extend(res.get("errors", []))
        except Exception as exc:
            # 保存失败不得抛出业务异常阻断用户响应（fail-open）
            save_errors.append(f"会话消息保存失败: {exc}")
        if save_errors:
            memory_context = ctx.metadata.setdefault(
                "memory_context", {"status": "degraded", "errors": []})
            if isinstance(memory_context, dict):
                existing = memory_context.get("errors")
                memory_context["errors"] = list(existing or []) + save_errors


__all__ = ["MemoryRecallMiddleware", "DEFAULT_CONFIG", "MEMORY_CONTEXT_KEYS"]
