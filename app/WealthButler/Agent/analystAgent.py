# -*- coding: utf-8 -*-
"""analystAgent.py — 数据分析Agent（Agent 层，ReActAgent 子类）。

《Agent设计文档》§4.1：单一路径，非意图分类——
_get_handler 固定返回 _handle_nl2sql，不做多意图业务路由；
_intent_threshold = 0.5（矩阵最低值）：内部只读查询出错不造成业务后果，
低置信度时"附加人工复核提示但仍执行"，而非拒绝/转人工。

实现方式参照脚手架 nl2cypherAgent 的"固定流程 _run_loop"模式：
不依赖 LLM 决策路由，直接调用 Nl2sqlService 全链路。
权限标识 data:nl2sql_query 由 Api 层校验（不硬编码角色，
具体授权范围由统一 RBAC 初始化配置决定）。
"""

from __future__ import annotations

import time
from typing import Any, List, Optional

from app.Base.Ai.base.baseAgent import AgentResult, ReActAgent
from app.WealthButler.Service.nl2sqlService import Nl2sqlService

REQUIRED_PERMISSION = "data:nl2sql_query"


class AnalystAgent(ReActAgent):
    """数据分析 Agent（员工侧只读工具，客户不可访问）。"""

    def __init__(
        self,
        service: Nl2sqlService,
        llm,
        name: str = "AnalystAgent",
        system_prompt: Optional[str] = None,
        max_iterations: int = 3,
        **kwargs: Any,
    ):
        self.service = service
        base_prompt = system_prompt or (
            "你是智能财富管家系统的数据分析Agent，服务内部员工，"
            "将自然语言问题转换为只读 SQL 查询并解读结果。"
            "单一路径执行，不与其他 Agent 交互。"
        )
        super().__init__(
            llm=llm,
            name=name,
            system_prompt=base_prompt,
            tools=[],
            max_iterations=max_iterations,
            **kwargs,
        )

    # ---- 契约方法（对齐《Agent设计文档》§1.1/§4）----
    def classify_intent(self, text: str) -> tuple:
        """单一路径：固定返回 nl2sql 意图（不做多意图路由）。"""
        return ("nl2sql", 1.0)

    def _get_handler(self, intent: str):
        return self._handle_nl2sql

    def _intent_threshold(self) -> float:
        return 0.5

    def _scenario_name(self) -> str:
        return "analyst"

    # ---- 固定单一路径的 ReAct 循环（不经 LLM 决策）----
    def _run_loop(self, messages, **kwargs):
        """单一路径：直接执行 NL2SQL 全链路，返回 AgentResult。

        与 nl2cypherAgent 的固定流程思路一致：核心链路是确定性编排，
        不交给 LLM 决策。LLM 只在两个环节参与：SQL 生成、结果解读。
        """
        user_input = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_input = msg.get("content", "")
                break

        scope_token = kwargs.get("scope_token", self.service.scope_token)
        self.service.scope_token = scope_token

        started = time.monotonic()
        result = self.service.answer_query(user_input)

        return AgentResult(
            success=result.error is None,
            output=result.reply,
            tool_calls=[{
                "name": "Nl2sqlTool",
                "parameters": {"query": user_input},
                "result": result.query_result,
            }],
            iterations=1,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_msg=result.error,
            metadata=result.to_metadata(),
        )

    def _handle_nl2sql(self, message: str, **kwargs: Any) -> AgentResult:
        return self._run_loop([{"role": "user", "content": message}], **kwargs)
