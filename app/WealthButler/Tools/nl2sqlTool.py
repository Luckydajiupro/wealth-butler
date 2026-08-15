# -*- coding: utf-8 -*-
"""nl2sqlTool.py — 数据分析Agent 主工具（Tools 层，BaseTool 子类）。

参照脚手架 `Ai/agents/nl2cypherAgent.py` 的工具写法：
pydantic args_schema + BaseTool.execute。
《Agent设计文档》§7.5：入参 query(str)，出参 sql_statement/query_result/
interpretation。
"""

from __future__ import annotations

import time
from typing import Any, Dict

from pydantic import BaseModel, Field

from app.Base.Ai.base.baseTool import BaseTool
from app.WealthButler.Service.nl2sqlService import Nl2sqlService


class Nl2sqlArgs(BaseModel):
    query: str = Field(..., description="自然语言数据查询问题，如：'上季度在售产品有多少款'")


class Nl2sqlTool(BaseTool):
    """NL2SQL 只读查询工具：自然语言 → 安全 SQL → 结果 + 解读。"""

    name = "Nl2sqlTool"
    description = (
        "将自然语言数据问题转换为只读 SQL 查询并返回结果与解读。"
        "仅支持 SELECT 查询业务数据（客户/画像/产品/交易/持仓/风评/预警/工单）。"
        "禁止任何写操作。"
    )
    args_schema = Nl2sqlArgs

    def __init__(self, service: Nl2sqlService):
        super().__init__()
        self.service = service

    def execute(self, query: str) -> str:
        import json as _json

        started = time.monotonic()
        result = self.service.answer_query(query)
        payload = {
            "sql_statement": result.generated_sql,
            "query_result": result.query_result,
            "interpretation": result.reply,
            "metadata": {
                "row_count": result.row_count,
                "cache_hit": result.cache_hit,
                "truncated": result.truncated,
                "security_rejected": result.security_rejected,
                "confidence": result.confidence,
            },
            "status": "success" if result.error is None else "error",
            "execution_time_ms": int((time.monotonic() - started) * 1000),
        }
        return _json.dumps(payload, ensure_ascii=False, default=str)
