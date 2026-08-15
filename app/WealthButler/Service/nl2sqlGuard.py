# -*- coding: utf-8 -*-
"""nl2sqlGuard.py — NL2SQL 安全校验层 + 表白名单/Schema 目录（Service 层）。

⚠️ 脚手架复用警示（《.claude/skills/scaffold-reuse》§3 警告 2）：
    脚手架 SQLBuilder 不做表名/字段名白名单、ToolGuard 只是关键词黑名单
    （可被注释/大小写变形绕过）——本模块按团队规范【必须完全新写】，
    不依赖脚手架这两个组件。执行 SQL 仅在此校验通过后放行。

校验分层（《数据分析Agent需求文档》§4）：
    L1 危险操作黑名单（词边界正则，大小写不敏感；先剥注释与字符串字面量）
    L2 单语句约束（引号感知分号扫描，仅允许末尾一个分号）
    L3 只读约束（首关键字必须 SELECT，CTE/WITH MVP 直接拒绝）
    L4 行数限制（无 LIMIT 自动追加 100；>100 钳制为 100）
    L5 危险函数/子句 + 表白名单 + 敏感列/PII 列拒绝

设计口径（与《表设计文档》§1 对齐）：
    允许查询 8 张业务表；排除 conversation_archive（会话PII+自身审计落点）
    与 fin_knowledge_meta（知识库运维元数据）。
    敏感列分级：restricted（password_hash 等凭据，永禁）；pii（phone/email/
    设备指纹/对手方信息，默认拒绝、可配置放开）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# 表白名单（8 张，与 WealthButler/Models 对齐）
# ---------------------------------------------------------------------------
ALLOWED_TABLES: Tuple[str, ...] = (
    "base_user",
    "fin_customer_profile",
    "fin_product",
    "fin_transaction",
    "fin_holdings",
    "fin_risk_assessment",
    "fin_risk_alert",
    "biz_work_order",
)

# 永禁敏感列（认证凭据，任何角色不可查询）
RESTRICTED_COLUMNS: Tuple[str, ...] = (
    "password_hash", "password", "secret", "token", "salt", "id_card",
)

# PII 列（默认拒绝查询、不注入 Schema；config allow_pii=true 时放开）
PII_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "base_user": ("phone", "email"),
    "fin_transaction": (
        "counterparty_account", "counterparty_name", "payer_account_name",
        "device_fingerprint",
    ),
    "fin_holdings": (),
    "fin_customer_profile": (),
    "fin_product": (),
    "fin_risk_assessment": (),
    "fin_risk_alert": (),
    "biz_work_order": (),
}

# 字段目录：表 -> {列名: 中文注释}，与 WealthButler/Models 的建表 SQL 对齐
_COLUMNS: Dict[str, Dict[str, str]] = {
    "base_user": {
        "id": "主键ID", "username": "登录名", "email": "邮箱", "phone": "手机号",
        "password_hash": "密码哈希（禁止查询）", "source_module": "来源模块标识",
        "status": "账户状态 active/inactive/banned", "last_login_at": "最后登录时间",
        "user_type": "用户大类 CUSTOMER/EMPLOYEE",
        "employee_role": "员工主角色 理财顾问/风控专员/客户经理/业务管理员",
        "advisor_level": "理财顾问执业等级 初级/中级/高级",
        "customer_level": "客户等级 普通/金卡/白金/钻石/私行",
        "created_at": "创建时间", "updated_at": "更新时间", "deleted_at": "软删除时间",
    },
    "fin_customer_profile": {
        "id": "主键ID", "customer_id": "客户ID(关联base_user.id)",
        "risk_level": "画像风险等级 C1-C5", "risk_score": "综合评分0-100",
        "dimension1_score": "维度一基础属性分(满分25)", "dimension2_score": "维度二投资经验分(满分25)",
        "dimension3_score": "维度三风险偏好分(满分30)", "dimension4_score": "维度四行为异常分(满分20)",
        "fm_flags": "命中熔断标记JSON数组 FM-01~FM-05",
        "asset_allocation": "资产配置画像JSON", "product_preference": "产品偏好画像JSON",
        "memory_units": "中期记忆单元JSON数组", "confidence_score": "画像整体置信度",
        "updated_reason": "更新触发原因 定期/事件/行为/市场/人工触发",
        "created_at": "创建时间", "updated_at": "更新时间",
    },
    "fin_product": {
        "id": "主键ID", "product_code": "产品编码", "product_name": "产品名称",
        "product_type": "产品类型 公募基金/私募基金/银行理财/保险/信托/结构性存款",
        "risk_level": "产品风险等级 R1-R5", "min_investment": "起投金额",
        "redemption_period_days": "赎回到账周期(天)", "nav": "最新净值", "nav_date": "净值日期",
        "industry": "所属行业", "fund_manager": "基金经理/管理人",
        "status": "产品状态 在售/已下架/封闭期", "description": "产品说明",
        "created_at": "创建时间", "updated_at": "更新时间",
    },
    "fin_transaction": {
        "id": "主键ID", "customer_id": "客户ID", "product_id": "产品ID(转账类可为空)",
        "transaction_type": "交易类型 申购/赎回/转账/分红/定投", "amount": "交易金额",
        "shares": "份额", "nav": "成交净值", "fee": "手续费", "is_cash": "是否现金交易",
        "counterparty_account": "对手方账号", "counterparty_name": "对手方名称",
        "counterparty_region": "对手方注册地/地区", "payer_account_name": "付款人姓名",
        "device_fingerprint": "设备指纹", "channel": "交易渠道 APP/柜台/网银等",
        "status": "交易状态 待确认/成交/失败/已撤销", "transaction_time": "交易发生时间",
        "created_at": "创建时间",
    },
    "fin_holdings": {
        "id": "主键ID", "customer_id": "客户ID", "product_id": "产品ID",
        "shares": "持有份额", "cost_amount": "累计成本金额", "current_value": "当前市值",
        "profit_loss": "浮动盈亏", "profit_ratio": "盈亏比例",
        "updated_at": "更新时间", "created_at": "创建时间",
    },
    "fin_risk_assessment": {
        "id": "主键ID", "customer_id": "客户ID", "total_score": "问卷总分0-100",
        "risk_level": "评估结果分级 C1-C5", "answers": "16题逐题作答JSON数组",
        "is_professional_investor": "是否专业投资者", "assessment_time": "评估完成时间",
        "valid_until": "有效期至(评估时间+12个月)", "created_at": "创建时间",
    },
    "fin_risk_alert": {
        "id": "主键ID", "customer_id": "客户ID", "alert_type": "触发规则编号 RW-001~RW-020",
        "alert_level": "预警级别 蓝/黄/红", "rule_weight_tier": "规则信号强度档位 强信号/中信号/弱信号",
        "transaction_ids": "关联交易流水ID JSON数组", "confidence": "预警置信度0-1",
        "is_repeat": "是否30天内重复触发", "repeat_trigger_count": "重复触发次数",
        "is_false_positive": "误报标记 NULL/0/1", "status": "处理状态 待处理/处理中/已处理/已升级",
        "handle_note": "处理备注", "handled_by": "处理人ID", "handled_at": "处理时间",
        "created_at": "创建时间(预警触发时间)",
    },
    "biz_work_order": {
        "id": "主键ID", "order_type": "工单类型 客户转介/风控处置/投诉建议/其他",
        "customer_id": "客户ID", "intent_summary": "意向摘要",
        "related_alert_id": "关联风控预警ID", "handled_by": "处理人ID",
        "status": "状态机 待处理/处理中/待审核/已完成/已驳回",
        "priority": "优先级 低/中/高", "created_at": "创建时间", "updated_at": "更新时间",
    },
}

# ---------------------------------------------------------------------------
# 危险关键字/函数/子句
# ---------------------------------------------------------------------------
_DANGEROUS_KEYWORDS: Tuple[str, ...] = (
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "CREATE",
    "GRANT", "REVOKE", "REPLACE", "RENAME", "EXEC", "EXECUTE", "CALL",
    "LOAD", "LOCK", "UNLOCK", "MERGE", "HANDLER",
)
_DANGEROUS_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(_DANGEROUS_KEYWORDS) + r")\b", re.IGNORECASE
)
_DANGEROUS_FUNCTIONS: Tuple[str, ...] = (
    "SLEEP", "BENCHMARK", "LOAD_FILE", "GET_LOCK", "RELEASE_LOCK",
    "IS_FREE_LOCK", "EXTRACTVALUE", "UPDATEXML", "GEOMETRYCOLLECTION",
)
_DANGEROUS_FUNC_RE = re.compile(
    r"\b(" + "|".join(_DANGEROUS_FUNCTIONS) + r")\s*\(", re.IGNORECASE
)
_DANGEROUS_CLAUSES: Tuple[str, ...] = (
    "INTO OUTFILE", "INTO DUMPFILE", "INFORMATION_SCHEMA", "PERFORMANCE_SCHEMA",
    "MYSQL.", "FOR UPDATE", "LOCK IN SHARE MODE",
)
_DANGEROUS_CLAUSE_RE = re.compile(
    r"(" + "|".join(_DANGEROUS_CLAUSES) + r")", re.IGNORECASE
)

MAX_ROWS = 100

# ---------------------------------------------------------------------------
# 字符串/注释剥离（引号感知，避免字面量中的关键字误报）
# ---------------------------------------------------------------------------
def _strip_string_literals(sql: str) -> str:
    """把单/双引号字符串替换为占位符；未闭合引号视为异常输入原样返回。"""
    out: List[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            quote = ch
            j = i + 1
            while j < n:
                if sql[j] == "\\":
                    j += 2
                    continue
                if sql[j] == quote:
                    if j + 1 < n and sql[j + 1] == quote:
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                return sql
            out.append("?")
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def strip_comments(sql: str) -> str:
    """剥离 -- 行注释、# 行注释与块注释；注释不参与执行。"""
    out: List[str] = []
    i, n = 0, len(sql)
    while i < n:
        if sql[i] == "-" and i + 1 < n and sql[i + 1] == "-":
            j = sql.find("\n", i)
            if j == -1:
                break
            out.append("\n")
            i = j + 1
        elif sql[i] == "#":
            j = sql.find("\n", i)
            if j == -1:
                break
            out.append("\n")
            i = j + 1
        elif sql[i] == "/" and i + 1 < n and sql[i + 1] == "*":
            j = sql.find("*/", i + 2)
            if j == -1:
                return sql
            out.append(" ")
            i = j + 2
        else:
            out.append(sql[i])
            i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# L2：引号感知分号扫描
# ---------------------------------------------------------------------------
def split_statements(sql: str) -> List[str]:
    parts: List[str] = []
    cur: List[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            quote = ch
            cur.append(ch)
            j = i + 1
            while j < n:
                cur.append(sql[j])
                if sql[j] == "\\":
                    if j + 1 < n:
                        cur.append(sql[j + 1])
                    j += 2
                    continue
                if sql[j] == quote:
                    if j + 1 < n and sql[j + 1] == quote:
                        cur.append(sql[j + 1])
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            i = j
        elif ch == ";":
            if cur and "".join(cur).strip():
                parts.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(ch)
            i += 1
    if cur and "".join(cur).strip():
        parts.append("".join(cur))
    return parts


def is_single_statement(sql: str) -> bool:
    cleaned = strip_comments(sql).strip()
    if not cleaned:
        return False
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    if not cleaned:
        return False
    return len(split_statements(cleaned)) == 1


def is_read_only(sql: str) -> bool:
    cleaned = strip_comments(sql).strip().rstrip(";").strip()
    first = re.match(r"^\s*([A-Za-z]+)", cleaned)
    if not first:
        return False
    return first.group(1).upper() == "SELECT"


# ---------------------------------------------------------------------------
# L4：LIMIT 强制
# ---------------------------------------------------------------------------
_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)(?:\s*,\s*(\d+))?\s*$", re.IGNORECASE)


def enforce_row_limit(sql: str, max_rows: int = MAX_ROWS) -> Tuple[str, bool]:
    cleaned = sql.rstrip()
    trailing_semi = cleaned.endswith(";")
    body = cleaned[:-1].rstrip() if trailing_semi else cleaned
    m = _LIMIT_RE.search(body)
    enforced = False
    if m:
        if m.group(2) is not None:
            offset, count = int(m.group(1)), int(m.group(2))
            if count > max_rows:
                body = _LIMIT_RE.sub(f"LIMIT {offset}, {max_rows}", body)
                enforced = True
        else:
            count = int(m.group(1))
            if count > max_rows:
                body = _LIMIT_RE.sub(f"LIMIT {max_rows}", body)
                enforced = True
    else:
        body = body + f" LIMIT {max_rows}"
        enforced = True
    return body + (";" if trailing_semi else ""), enforced


# ---------------------------------------------------------------------------
# 表/列提取
# ---------------------------------------------------------------------------
_TABLE_REF_RE = re.compile(r"\b(?:FROM|JOIN)\s+([`\w\.]+)", re.IGNORECASE)
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_COLUMN_REF_RE = re.compile(r"[`\w]+\.([`\w]+)", re.IGNORECASE)
_BARE_COLUMN_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")


def extract_table_names(sql: str) -> List[str]:
    cleaned = strip_comments(_strip_string_literals(sql))
    names = []
    for m in _TABLE_REF_RE.finditer(cleaned):
        token = _BACKTICK_RE.sub(r"\1", m.group(1).strip())
        if token.endswith("."):
            token = token[:-1]
        names.append(token)
    return names


def extract_column_names(sql: str) -> List[str]:
    cleaned = strip_comments(_strip_string_literals(sql))
    cols = [_BACKTICK_RE.sub(r"\1", m.group(1)) for m in _COLUMN_REF_RE.finditer(cleaned)]
    if not cols:
        cols = [m.group(1) for m in _BARE_COLUMN_RE.finditer(cleaned)]
    return cols


# ---------------------------------------------------------------------------
# 校验结论与主入口
# ---------------------------------------------------------------------------
@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""
    violations: List[str] = field(default_factory=list)
    sql: str = ""
    limit_enforced: bool = False

    def __bool__(self) -> bool:
        return self.allowed


class Nl2sqlGuard:
    """NL2SQL 安全校验器 + 表白名单/Schema 目录（进程内单例）。

    usage:
        guard = Nl2sqlGuard(allow_pii=False)
        result = guard.validate(llm_sql)   # -> GuardResult
        guard.ddl_for([...])               # 动态 Schema 注入用
        guard.filter_row(row)              # 执行器侧敏感列剥离
    """

    def __init__(self, allow_pii: bool = False):
        self.allow_pii = allow_pii
        self.tables: Set[str] = set(ALLOWED_TABLES)
        self.restricted: Set[str] = set(RESTRICTED_COLUMNS)
        self.pii: Set[str] = set()
        if not allow_pii:
            for cols in PII_COLUMNS.values():
                self.pii.update(cols)

    # ---- Schema 目录（Prompt 动态注入用）----
    def ddl_for(self, tables: List[str]) -> str:
        lines: List[str] = []
        for table in tables:
            if table not in self.tables:
                continue
            lines.append(f"CREATE TABLE {table} (")
            col_defs = []
            for col, comment in _COLUMNS[table].items():
                if col in self.restricted or (col in self.pii and not self.allow_pii):
                    continue  # 敏感/PII 列不注入 Schema（prompt-engineering §6 双层防线）
                col_defs.append(f"  {col} -- {comment}")
            lines.append(",\n".join(col_defs))
            lines.append(");")
            lines.append("")
        return "\n".join(lines)

    def full_ddl(self) -> str:
        return self.ddl_for(list(ALLOWED_TABLES))

    def filter_row(self, row: dict) -> dict:
        """执行器侧逐行剥离 restricted 与未放开 PII 列（SELECT * 兜底）。"""
        blocked = set(self.restricted)
        if not self.allow_pii:
            blocked.update(self.pii)
        return {k: v for k, v in row.items() if str(k).lower() not in blocked}

    # ---- L1-L5 全量校验 ----
    def validate(self, sql: str, max_rows: int = MAX_ROWS) -> GuardResult:
        raw = sql.strip()
        if not raw:
            return GuardResult(False, "空 SQL", ["empty"])

        if not is_single_statement(raw):
            return GuardResult(False, "仅允许单条语句", ["multi_statement"])

        # 剥注释 + 剥字符串字面量后做关键字/白名单校验
        cleaned = _strip_string_literals(strip_comments(raw))

        m = _DANGEROUS_KEYWORD_RE.search(cleaned)
        if m:
            return GuardResult(
                False, "不允许执行该操作（危险关键字）",
                ["dangerous_keyword:" + m.group(1).upper()],
            )

        if not is_read_only(cleaned):
            return GuardResult(False, "仅允许 SELECT 只读查询", ["not_read_only"])

        violations: List[str] = []
        mf = _DANGEROUS_FUNC_RE.search(cleaned)
        if mf:
            violations.append("dangerous_function:" + mf.group(1).upper())
        mc = _DANGEROUS_CLAUSE_RE.search(cleaned)
        if mc:
            violations.append("dangerous_clause:" + mc.group(1).upper())
        if violations:
            return GuardResult(False, "不允许执行该操作（危险函数/子句）", violations)

        tables = extract_table_names(cleaned)
        if not tables:
            return GuardResult(False, "未能解析出查询表", ["no_table"])
        unknown = sorted({t for t in tables if t.lower() not in self.tables})
        if unknown:
            return GuardResult(
                False, "查询包含白名单外的表",
                [f"table_not_allowed:{t}" for t in unknown],
            )

        cols = extract_column_names(cleaned)
        restricted_hits = [c for c in cols if c.lower() in self.restricted]
        if restricted_hits:
            return GuardResult(
                False, "查询包含敏感列",
                [f"column_restricted:{c}" for c in restricted_hits],
            )
        pii_hits = [c for c in cols if c.lower() in self.pii]
        if pii_hits:
            return GuardResult(
                False, "查询包含个人信息列（默认不开放）",
                [f"column_pii:{c}" for c in pii_hits],
            )

        final_sql, enforced = enforce_row_limit(raw, max_rows)
        return GuardResult(True, sql=final_sql, limit_enforced=enforced)
