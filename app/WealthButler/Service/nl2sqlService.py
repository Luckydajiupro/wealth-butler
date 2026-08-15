# -*- coding: utf-8 -*-
"""nl2sqlService.py — 数据分析Agent NL2SQL 全链路引擎（Service 层）。

流程（《数据分析Agent需求文档》§2.3 调用链）：
    自然语言问题 → 缓存检查(nl2sql:cache:{query_hash}, TTL 10min)
    → 动态 Schema 筛选 + few-shot → LLM 生成 SQL
    → Nl2sqlGuard L1-L5 校验 → 只读执行(≤100行) → LLM 解读
    → 写缓存 / 审计返回

依赖注入（复用脚手架，不自行造连接）：
    llm       : Base.Ai.base.baseLlm.BaseLlm（DeepSeekLlm/QwenLlm）
    executor  : 只读执行器（默认 MySqlReadExecutor 包装 MySQLClient）
    cache     : 缓存（默认 RedisNl2sqlCache 包装 RedisClient 单例）
    guard     : Nl2sqlGuard（必须新写的安全校验层）
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.WealthButler.Prompts.analystPrompts import (
    build_interpret_prompt,
    build_system_prompt,
)
from app.WealthButler.Service.nl2sqlGuard import Nl2sqlGuard

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"   # 与 nl2sqlGuard 白名单版本绑定，白名单变更需递增
CACHE_TTL_SECONDS = 600  # 10 分钟
MAX_ROWS = 100

# 关键词 → 注入表（《数据分析Agent需求文档》§3.2，表名对齐《表设计文档》）
_KEYWORD_TABLES: List[Tuple[Tuple[str, ...], Tuple[str, ...]]] = [
    (("客户", "画像", "风险等级", "风险分级", "客户等级"), ("base_user", "fin_customer_profile")),
    (("持仓", "持有", "买了什么", "买了哪些", "仓位"), ("fin_holdings", "fin_product")),
    (("交易", "流水", "申购", "赎回", "转账", "分红", "定投"),
     ("fin_transaction", "fin_product", "base_user")),
    (("产品", "收益率", "净值", "在售", "基金", "理财"), ("fin_product",)),
    (("风评", "风险测评", "问卷", "风险评估", "有效期"), ("fin_risk_assessment",)),
    (("预警", "风控", "反洗钱", "可疑", "误报"), ("fin_risk_alert",)),
    (("工单", "转介", "投诉"), ("biz_work_order",)),
    (("收益", "AUM", "资产统计", "总资产", "亏损", "盈亏"), ("fin_holdings", "fin_customer_profile", "fin_product")),
]

# 兜底核心 3 表（未命中任何关键词时注入，不得注入全部 10 表）
FALLBACK_TABLES: Tuple[str, ...] = ("base_user", "fin_product", "fin_transaction")


# ---------------------------------------------------------------------------
# 结果结构
# ---------------------------------------------------------------------------
@dataclass
class Nl2sqlResult:
    """对齐 AgentResult.metadata 扩展（generated_sql/row_count/cache_hit）。"""
    reply: str = ""
    sql: str = ""
    query_result: List[Dict[str, Any]] = field(default_factory=list)
    generated_sql: str = ""
    row_count: int = 0
    cache_hit: bool = False
    truncated: bool = False
    confidence: float = 0.0
    low_confidence_note: bool = False
    security_rejected: bool = False
    security_detail: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "generated_sql": self.generated_sql,
            "row_count": self.row_count,
            "cache_hit": self.cache_hit,
            "truncated": self.truncated,
            "confidence": self.confidence,
            "security_rejected": self.security_rejected,
            "security": self.security_detail,
            "low_confidence_note": self.low_confidence_note,
        }


# ---------------------------------------------------------------------------
# 执行器（只读，101 行探测截断）
# ---------------------------------------------------------------------------
class MySqlReadExecutor:
    """包装脚手架 MySQLClient.execute_sync 的只读执行器。

    production 建议连接串使用只读数据库账号（nl2sql_ro），
    作为 Nl2sqlGuard 应用层校验之外的第二道防线。
    """

    def __init__(self, mysql_client, row_filter: Optional[Callable[[dict], dict]] = None):
        self._client = mysql_client
        self._row_filter = row_filter

    def execute_read(self, sql: str) -> Tuple[List[Dict[str, Any]], bool]:
        """返回 (行列表, 是否超 100 行被截断)。"""
        probe_sql = _with_limit(sql, MAX_ROWS + 1)
        raw = self._client.execute_sync(probe_sql) or []
        truncated = len(raw) > MAX_ROWS
        raw = raw[:MAX_ROWS]
        if self._row_filter is not None:
            raw = [self._row_filter(r) for r in raw]
        return raw, truncated


# ---------------------------------------------------------------------------
# 缓存（RedisClient 单例适配）
# ---------------------------------------------------------------------------
class RedisNl2sqlCache:
    KEY_PREFIX = "nl2sql:cache"

    def __init__(self, redis_client, key_prefix: str = KEY_PREFIX):
        self._client = redis_client
        self._prefix = key_prefix

    def get(self, key: str) -> Optional[dict]:
        raw = self._client.get(f"{self._prefix}:{key}")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def set(self, key: str, payload: dict, ttl: int = CACHE_TTL_SECONDS) -> None:
        self._client.set(
            f"{self._prefix}:{key}",
            json.dumps(payload, ensure_ascii=False, default=str),
            ex=ttl,
        )


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def normalize_question(question: str) -> str:
    return re.sub(r"\s+", "", question.strip().lower())


def compute_query_hash(question: str, scope_token: str = "", schema_version: str = SCHEMA_VERSION) -> str:
    """缓存键哈希 = 问题 + 权限范围 + Schema 版本（防跨权限复用缓存）。"""
    raw = f"{normalize_question(question)}|{scope_token}|{schema_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def select_tables(question: str) -> Tuple[Tuple[str, ...], float]:
    """关键词匹配选表；未命中兜底核心 3 表并返回置信度 0.5。"""
    q = question.lower()
    tables: List[str] = []
    for keywords, tbls in _KEYWORD_TABLES:
        if any(kw.lower() in q for kw in keywords):
            for t in tbls:
                if t not in tables:
                    tables.append(t)
    if tables:
        return tuple(tables), 1.0
    if q.strip():
        return FALLBACK_TABLES, 0.5
    return (), 0.0


def _extract_sql(raw: Any) -> Dict[str, Any]:
    """从 LLM 输出提取 {sql, confidence}（健壮化，兼容三种形态）：
    1) dict 直接返回；2) 纯 JSON 字符串；3) 包裹形态（```json 围栏、
    前后附解释文字、JSON 子串）——联调发现 DeepSeek 偶发输出包裹格式。"""
    if isinstance(raw, dict):
        return {"sql": str(raw.get("sql") or ""),
                "confidence": float(raw.get("confidence", 1.0) or 1.0)}
    if isinstance(raw, str):
        text = raw.strip()
        # 剥 markdown 代码围栏
        fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        candidates = []
        # 取首 { 到末 } 的 JSON 子串（容忍前后解释文字）
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            candidates.append(text[start:end + 1])
        candidates.append(text)
        for cand in candidates:
            try:
                data = json.loads(cand)
                if isinstance(data, dict):
                    return {"sql": str(data.get("sql") or ""),
                            "confidence": float(data.get("confidence", 1.0) or 1.0)}
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
    return {"sql": "", "confidence": 0.0}


def _with_limit(sql: str, limit: int) -> str:
    body = sql.rstrip()
    trailing_semi = body.endswith(";")
    body = body[:-1].rstrip() if trailing_semi else body
    if re.search(r"\bLIMIT\s+\d+(\s*,\s*\d+)?\s*$", body, re.IGNORECASE):
        return body + (";" if trailing_semi else "")
    return body + f" LIMIT {limit}" + (";" if trailing_semi else "")


def _format_table(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "未查询到相关数据。"
    headers = list(rows[0].keys())
    lines = ["\t".join(headers)]
    for r in rows:
        lines.append("\t".join(str(r.get(h, "")) for h in headers))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------
class Nl2sqlService:
    """NL2SQL 全链路编排。依赖全部注入，便于测试与脚手架适配。"""

    def __init__(
        self,
        llm,
        executor,
        guard: Nl2sqlGuard,
        cache,
        scope_token: str = "",
        auditor: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.llm = llm
        self.executor = executor
        self.guard = guard
        self.cache = cache
        self.scope_token = scope_token
        self.auditor = auditor

    # ------------------------------------------------------------------
    def answer_query(self, question: str) -> Nl2sqlResult:
        started = time.monotonic()
        result = Nl2sqlResult()

        if not question or not question.strip():
            result.error = "问题不能为空"
            return result

        cache_key = compute_query_hash(question, self.scope_token)

        # 1. 缓存检查（Redis 不可用 → 跳过缓存，降级直查）
        # 性能优化（联调发现）：缓存值含 interpretation，命中路径直接返回
        # 不再调解读 LLM（命中路径 2.3s → <100ms）。
        try:
            entry = self.cache.get(cache_key)
        except Exception:
            entry = None
        if entry is not None:
            rows = entry.get("result", []) if isinstance(entry.get("result"), list) else []
            # interpretation 已含低置信度提示（写入缓存时即最终文案），直接返回
            reply = entry.get("interpretation") or self._interpret_or_fallback(question, entry.get("sql", ""), rows)
            result.cache_hit = True
            result.generated_sql = entry.get("sql", "")
            result.sql = result.generated_sql
            result.query_result = rows
            result.row_count = len(rows)
            result.reply = f"（缓存结果）{reply}"
            result.audit_hint = cache_key
            return result

        # 2. 动态 Schema 筛选 + few-shot（低置信度 → 注入全量允许 Schema）
        tables, sel_confidence = select_tables(question)
        schema = self.guard.ddl_for(list(tables)) if sel_confidence >= 1.0 else self.guard.full_ddl()
        system_prompt = build_system_prompt(schema)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]

        # 3. LLM 生成 SQL（失败 → 错误码 1003 语义，不属安全拦截）
        # 性能与稳定折中（联调实测）：max_tokens=512 比 1024 快约 35%，
        # 但偶发截断输出（复杂问题概率性 finish_reason=length）→
        # 空结果时自动升级 1024 重试一次。
        generated = {"sql": "", "confidence": 0.0}
        for attempt_tokens in (512, 1024):
            try:
                raw = self.llm.chat(messages, max_tokens=attempt_tokens)
                generated = _extract_sql(raw)
                if generated["sql"].strip():
                    break
            except Exception as exc:
                logger.warning("SQL 生成失败(max_tokens=%s): %s", attempt_tokens, exc)
                generated = {"sql": "", "confidence": 0.0}

        sql_text = generated["sql"].strip()
        sql_confidence = generated["confidence"]
        result.generated_sql = sql_text
        result.confidence = round(sql_confidence, 2)
        if not sql_text:
            result.error = "SQL 生成失败，请换一种方式描述您的查询需求。"
            return result

        # 4. 安全校验（L1-L5；拒绝 → 业务级错误"不允许执行该操作"）
        guard_result = self.guard.validate(sql_text)
        result.security_detail = {
            "allowed": guard_result.allowed,
            "reason": guard_result.reason,
            "violations": guard_result.violations,
            "limit_enforced": guard_result.limit_enforced,
        }
        if not guard_result.allowed:
            result.security_rejected = True
            result.reply = "不允许执行该操作"
            result.error = f"安全校验未通过：{guard_result.reason}"
            self._emit_audit(result, cache_key)
            return result
        safe_sql = guard_result.sql

        # 5. 只读执行（≤100 行）
        try:
            rows, truncated = self.executor.execute_read(safe_sql)
        except Exception as exc:
            logger.warning("查询执行异常: %s", exc)
            result.error = f"查询执行异常：{exc}"
            return result
        result.sql = safe_sql
        result.query_result = rows
        result.row_count = len(rows)
        result.truncated = truncated

        # 6. 解读（LLM 失败回退原始表格兜底）
        result.reply = self._interpret_or_fallback(question, safe_sql, rows)

        # 低置信度降级：安全通过后仍执行，附人工复核提示
        if sql_confidence < 0.5:
            result.low_confidence_note = True
            result.reply += "（该结果由低置信度 SQL 生成，建议人工复核）"

        # 7. 写缓存（失败不影响响应；interpretation 一并入缓存，
        #    命中路径免二次解读——性能优化）
        try:
            self.cache.set(cache_key, {
                "sql": safe_sql, "result": rows, "generated_at": time.time(),
                "interpretation": result.reply,
                "low_confidence_note": result.low_confidence_note,
            }, ttl=CACHE_TTL_SECONDS)
        except Exception:
            pass

        self._emit_audit(result, cache_key)
        return result

    # ------------------------------------------------------------------
    def _interpret_or_fallback(self, question: str, sql: str, rows: List[Dict[str, Any]]) -> str:
        try:
            prompt = build_interpret_prompt(question, sql, rows, len(rows))
            text = self.llm.chat([{"role": "user", "content": prompt}], max_tokens=256)
            if text and str(text).strip():
                return str(text).strip()
        except Exception:
            pass
        return _format_table(rows)

    def _emit_audit(self, result: Nl2sqlResult, cache_key: str) -> None:
        """审计回调：由调用方注入（写 conversation_archive.tool_calls）。"""
        if self.auditor is not None:
            try:
                self.auditor({
                    "cache_key": cache_key,
                    "scope_token": self.scope_token,
                    "generated_sql": result.generated_sql,
                    "security_rejected": result.security_rejected,
                    "security": result.security_detail,
                    "row_count": result.row_count,
                    "timestamp": time.time(),
                })
            except Exception:
                logger.warning("审计写入失败（不阻塞响应）", exc_info=True)
