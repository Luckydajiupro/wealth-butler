"""风控监测Agent 规则引擎核心（组C）

模块职责：
- RiskRuleMatch.match(customer_id, rule_scope, trigger_source, context=None)：统一核心入口，
  事件轨与批量轨共用（只传不同 rule_scope），组F 实时/日批/周批三条路径都调它；
- 只做聚合：规则范围校验、20 条 check_* 调用、三态结果聚合（命中/数据不足/取数失败）、
  30 天重复触发查询、三级预警分级（就高修正）、风控置信度、30 天中风险规则累计升级信号；
- **不写库、不建工单、不发事件、不做交易拦截**：本层只产出"规则判断与升级建议"结构化结果，
  fin_risk_alert / biz_work_order 写入与 stream:risk_alert 发布属于组F/联调阶段（跨组边界）。

核心口径（全部来自组A/组B已确认纪要，勿在此重新设计）：
- 分级 = 命中数档位 与 批次内最高规则风险等级档位 与 重复触发最低档位 取高（聂柏确认①）：
  命中数 1条→low / 2-3条→medium / >3条→high；风险等级档位取组B RISK_LEVEL_MIN_SEVERITY
  （🔴高→high、🟠中高→medium、🟡中·🔵低→low）；任一命中规则重复→最低 medium。
  critical 本迭代不启用（蒋智仁 A3 确认：升级不引入新档位）。
- 置信度 = round(min(1.0, Σ命中规则权重 + 0.15×is_repeat), 2)，与 severity 是两个独立维度，
  互不推导（需求§5.4.2）。仅统计 status='hit'；insufficient_data 与取数失败不计入。
- 30 天升级（聂柏确认②）：只统计原文风险等级为"中风险"的规则 MEDIUM_RISK_RULE_IDS
  （RW-001/007/012/015）的预警行，不按 severity='medium' 统计——中高风险规则也映射 medium，
  按 severity 统计会放大升级面。历史计数 + 本批命中计数 >= 3 → escalated，severity 强制 high/红。
  升级不写 fm_flags、不改 risk_level、不参与交易拦截（蒋智仁 A3 确认，方案B）。
- 重复触发：RiskAlertModel.find_by_rule_id(rule_id, days=30) 只有 rule_id 参数、没有 customer_id，
  **必须逐条按 alert.customer_id 二次过滤**，否则会把其他客户的历史误算到当前客户头上。
  历史查询失败不得默认 is_repeat=False，必须降级（degraded）并拒绝生成看似完整的 severity/confidence。

组B 三态契约（原样兼容，不得复制规则判断逻辑）：
- None → 未命中，不进入 triggered_rules，不参与分级与置信度；
- RuleHit(status='hit') → 命中，保留 rule_id/rule_name/details/related_transaction_ids/primary_transaction_id；
- RuleHit(status='insufficient_data') → 数据不足，进 insufficient_rules，保留 missing_fields/details.reason；
- RuleDataUnavailableError → 取数失败，进 errors，绝不伪装成 None。

本模块不包含任何动态执行代码路径；金额/比例类型由组B check 函数保证，本层只做聚合。
"""
import logging
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field

from app.WealthButler.Rules.ruleDefinitions import (
    AML_RULES,
    DAILY_RULE_IDS,
    MEDIUM_RISK_RULE_IDS,
    REALTIME_RULE_IDS,
    RISK_LEVEL_MIN_SEVERITY,
    WEEKLY_RULE_IDS,
    RuleContext,
    RuleDataUnavailableError,
    RuleHit,
)

logger = logging.getLogger(__name__)

# 严重程度排序（本迭代只有三档；critical 不启用——蒋智仁 A3 确认升级不引入新档位，
# 否则 NL2SQL 白名单/查询口径要跟着变）
SEVERITY_RANK: Dict[str, int] = {"low": 0, "medium": 1, "high": 2}
# severity -> 展示用 alert_level（组A 蓝/黄/红口径，Agent Tool schema 与展示层使用）
SEVERITY_TO_ALERT_LEVEL: Dict[str, str] = {"low": "蓝", "medium": "黄", "high": "红"}

# 重复触发/升级的历史查询窗口（自然日，与 RiskAlertModel.find_by_rule_id 的 days 语义一致）
REPEAT_WINDOW_DAYS = 30
ESCALATION_WINDOW_DAYS = 30


class TriggeredRuleInfo(BaseModel):
    """单条命中规则的结构化信息（触发聚合的原始证据，供组F写库映射）。"""

    rule_id: str
    rule_name: str
    weight_tier: float
    priority: int
    risk_level: str
    details: Dict[str, Any] = Field(default_factory=dict)
    related_transaction_ids: List[int] = Field(default_factory=list)
    primary_transaction_id: Optional[int] = None


class InsufficientRuleInfo(BaseModel):
    """单条规则"数据不足、无法判定"的结构化信息（与未命中严格区分，供组F留痕）。"""

    rule_id: str
    rule_name: str
    missing_fields: List[str] = Field(default_factory=list)
    reason: str = ""


class EngineErrorInfo(BaseModel):
    """取数失败/引擎异常的结构化信息（绝不静默忽略）。"""

    rule_id: str
    rule_name: str
    error: str


class RiskRuleMatchResult(BaseModel):
    """RiskRuleMatch.match 的输出契约（组F写库的输入）。"""

    status: Literal["ok", "no_hit", "degraded", "error"] = "ok"
    customer_id: int
    trigger_source: Literal["event", "scheduler"]
    rule_scope: List[str] = Field(default_factory=list)
    triggered_rules: List[TriggeredRuleInfo] = Field(default_factory=list)
    insufficient_rules: List[InsufficientRuleInfo] = Field(default_factory=list)
    errors: List[EngineErrorInfo] = Field(default_factory=list)
    # 分级与置信度是两个独立维度，互不推导；历史查询不可用时为 None（拒绝生成看似完整的结果）
    severity: Optional[Literal["low", "medium", "high"]] = None
    alert_level: Optional[Literal["蓝", "黄", "红"]] = None
    confidence: Optional[float] = None
    # 重复触发（批次级）：任一当前命中规则在30天内有历史预警即为 True
    is_repeat: Optional[bool] = None
    repeat_rule_ids: List[str] = Field(default_factory=list)
    repeat_status: str = "not_checked"  # checked | unavailable | not_checked
    # 30天中风险规则累计升级信号（聂柏确认② + 蒋智仁 A3 方案B：只输出信号，不写 fm_flags）
    escalated: Optional[bool] = None
    escalation_count: int = 0
    escalation_rule_ids: List[str] = Field(default_factory=list)
    escalation_reason: str = ""
    escalation_status: str = "not_checked"  # checked | unavailable | not_checked


# ======================================================================
# 内部辅助
# ======================================================================


def _coerce_context(context: Optional[Union[RuleContext, dict]]) -> RuleContext:
    """统一 context 类型：RuleContext 原样使用；dict 转 RuleContext；None 用默认值。
    context 只用于测试/临时数据注入与已备案数据缺口（组B RuleContext 契约），不是公开参数。"""
    if context is None:
        return RuleContext()
    if isinstance(context, RuleContext):
        return context
    if isinstance(context, dict):
        return RuleContext(**context)
    raise ValueError(f"context 必须是 RuleContext 或 dict，收到: {type(context)!r}")


def _validate_params(customer_id, rule_scope, trigger_source) -> None:
    """参数校验（调用方错误 → 抛 ValueError，错误信息必须可定位）。"""
    if isinstance(customer_id, bool) or not isinstance(customer_id, int) or customer_id <= 0:
        raise ValueError(f"customer_id 必须是正整数，收到: {customer_id!r}")
    if not isinstance(rule_scope, (list, tuple)) or not rule_scope:
        raise ValueError("rule_scope 不能为空，且必须是规则ID列表（如 ['RW-001']）")
    for rule_id in rule_scope:
        if not isinstance(rule_id, str) or rule_id not in AML_RULES:
            raise ValueError(
                f"rule_scope 含未知规则ID: {rule_id!r}（仅允许 RW-001~RW-020；"
                f"MANUAL 等人工上报值不允许传入自动规则匹配）"
            )
    if trigger_source not in ("event", "scheduler"):
        raise ValueError(f"trigger_source 只允许 'event' 或 'scheduler'，收到: {trigger_source!r}")
    if trigger_source == "event":
        invalid = [r for r in rule_scope if r not in REALTIME_RULE_IDS]
        if invalid:
            raise ValueError(
                f"trigger_source='event' 只允许实时/准实时规则（{list(REALTIME_RULE_IDS)}），"
                f"违规规则: {invalid}"
            )
    else:
        scheduler_ids = set(DAILY_RULE_IDS) | set(WEEKLY_RULE_IDS)
        invalid = [r for r in rule_scope if r not in scheduler_ids]
        if invalid:
            raise ValueError(
                f"trigger_source='scheduler' 只允许日批/周批规则，违规规则: {invalid}"
            )


def _normalize_scope(rule_scope) -> List[str]:
    """规则范围去重（保留首次出现顺序）+ 按 (priority 升序, rule_id) 稳定排序——评估顺序与
    结果中命中规则的顺序都必须遵循该约定（组C契约第5.7/5.8条）。"""
    seen = set()
    deduped: List[str] = []
    for rule_id in rule_scope:
        if rule_id not in seen:
            seen.add(rule_id)
            deduped.append(rule_id)
    deduped.sort(key=lambda r: (AML_RULES[r].priority, r))
    return deduped


def _hit_count_tier(count: int) -> Optional[str]:
    """命中数档位（聂柏确认①）：0条无预警；1条 low；2-3条 medium；>3条 high。"""
    if count <= 0:
        return None
    if count == 1:
        return "low"
    if count <= 3:
        return "medium"
    return "high"


def _find_customer_rule_alerts(customer_id: int, rule_id: str, days: int = REPEAT_WINDOW_DAYS) -> List[Any]:
    """查询某客户某规则最近 days 天的历史预警记录。

    WHY 必须按 customer_id 二次过滤：RiskAlertModel.find_by_rule_id(rule_id, days) 只有 rule_id
    参数、没有 customer_id 过滤，直接 bool() 返回结果会把**其他客户**的历史误算到当前客户头上
    （跨客户误判的回归测试见 tests/test_ruleEngine.py）。
    惰性导入模型规避 EB-B-16（app/Base 双命名空间循环导入）；导入或查询失败必须抛
    RuleDataUnavailableError，调用方不得默认 is_repeat=False。"""
    try:
        from app.WealthButler.Models.riskAlertModel import RiskAlertModel
    except Exception as e:
        raise RuleDataUnavailableError(f"历史预警查询不可用（RiskAlertModel 导入失败）: {e}") from e
    try:
        alerts = RiskAlertModel.find_by_rule_id(rule_id, days=days)
    except Exception as e:
        raise RuleDataUnavailableError(f"查询规则 {rule_id} 最近{days}天历史预警失败: {e}") from e
    return [a for a in alerts if getattr(a, "customer_id", None) == customer_id]


def _count_medium_risk_history(customer_id: int, days: int = ESCALATION_WINDOW_DAYS) -> Dict[str, int]:
    """统计客户最近 days 天四条中风险规则（MEDIUM_RISK_RULE_IDS）的历史预警行数。

    WHY 只统计 MEDIUM_RISK_RULE_IDS（聂柏确认②）：升级机制原文是"30天内累计触发≥3次**中风险**预警"，
    中风险对应规则原文 🟡档（RW-001/007/012/015）；若按 severity='medium' 统计，🟠中高风险规则
    （单条命中经就高修正也映射 medium）会混入计数，放大升级面。"""
    counts: Dict[str, int] = {}
    for rule_id in MEDIUM_RISK_RULE_IDS:
        counts[rule_id] = len(_find_customer_rule_alerts(customer_id, rule_id, days=days))
    return counts


# ======================================================================
# 规则聚合核心
# ======================================================================


class RiskRuleMatch:
    """风控规则聚合核心（确定性代码，不使用 LLM；组F 事件轨与批量轨共用入口）。"""

    @classmethod
    def match(
        cls,
        customer_id: int,
        rule_scope: List[str],
        trigger_source: Literal["event", "scheduler"],
        context: Optional[Union[RuleContext, dict]] = None,
    ) -> RiskRuleMatchResult:
        """评估指定规则范围并聚合输出。

        Args:
            customer_id: 待评估客户ID（base_user.id，正整数）。
            rule_scope: 规则ID列表（RW-001~RW-020 子集；event 只允许实时8条，scheduler 只允许日批/周批12条）。
            trigger_source: 触发来源（event=实时/准实时事件触发；scheduler=日批/周批定时批量）。
            context: RuleContext（或 dict），仅测试/数据注入使用，不是 Function Calling 公开参数。

        Returns:
            RiskRuleMatchResult（组F写库的输入）；参数错误抛 ValueError（调用方错误）。
        """
        # 参数校验（调用方错误 → 明确拒绝，不做结构化结果）
        _validate_params(customer_id, rule_scope, trigger_source)
        scope = _normalize_scope(rule_scope)
        ctx = _coerce_context(context)

        try:
            result = RiskRuleMatchResult(
                customer_id=customer_id, trigger_source=trigger_source, rule_scope=list(scope)
            )
            cls._evaluate(result, scope, ctx)
            cls._resolve_repeat(result, customer_id)
            cls._resolve_escalation(result, customer_id)
            cls._resolve_severity(result)
            cls._resolve_confidence(result)
            cls._resolve_status(result)
            return result
        except Exception as e:  # 引擎自身异常兜底：不吞、不伪装，转成 error 状态
            logger.error(f"规则引擎内部异常: {e}", exc_info=True)
            return RiskRuleMatchResult(
                status="error",
                customer_id=customer_id,
                trigger_source=trigger_source,
                rule_scope=list(scope),
                errors=[EngineErrorInfo(rule_id="__engine__", rule_name="规则引擎", error=f"引擎内部异常: {e}")],
            )

    # ----- 评估与三态聚合 -----

    @classmethod
    def _evaluate(cls, result: RiskRuleMatchResult, scope: List[str], ctx: RuleContext) -> None:
        """按 (priority, rule_id) 顺序逐条调用 check_func，三态分别聚合。
        RuleDataUnavailableError 与其他异常进 errors，不中断其余规则评估，绝不伪装成 None。"""
        for rule_id in scope:
            meta = AML_RULES[rule_id]
            try:
                # 组B统一签名 check_func(customer_id, context=None)，按位置参数调用
                rule_result = meta.check_func(result.customer_id, ctx)
            except RuleDataUnavailableError as e:
                result.errors.append(EngineErrorInfo(rule_id=rule_id, rule_name=meta.rule_name, error=str(e)))
                continue
            except Exception as e:  # 防御：非预期异常同样结构化留痕，其余规则继续
                result.errors.append(
                    EngineErrorInfo(rule_id=rule_id, rule_name=meta.rule_name, error=f"规则函数异常: {e}")
                )
                continue
            if rule_result is None:
                continue  # 未命中：不进入任何列表
            if getattr(rule_result, "status", None) == "hit":
                result.triggered_rules.append(
                    TriggeredRuleInfo(
                        rule_id=rule_result.rule_id,
                        rule_name=rule_result.rule_name,
                        weight_tier=meta.weight_tier,
                        priority=meta.priority,
                        risk_level=meta.risk_level,
                        details=dict(rule_result.details or {}),
                        related_transaction_ids=list(rule_result.related_transaction_ids or []),
                        primary_transaction_id=rule_result.primary_transaction_id,
                    )
                )
            else:  # insufficient_data：不能当成未命中，也不能当成命中
                reason = ""
                if isinstance(rule_result.details, dict):
                    reason = str(rule_result.details.get("reason", ""))
                result.insufficient_rules.append(
                    InsufficientRuleInfo(
                        rule_id=rule_result.rule_id,
                        rule_name=rule_result.rule_name,
                        missing_fields=list(rule_result.missing_fields or []),
                        reason=reason,
                    )
                )

    # ----- 30 天重复触发（只对当前批次实际命中的规则判定）-----

    @classmethod
    def _resolve_repeat(cls, result: RiskRuleMatchResult, customer_id: int) -> None:
        """is_repeat 为批次级布尔：任一当前命中规则存在本客户30天历史预警即为 True。
        历史查询失败 → repeat_status='unavailable'、is_repeat=None，不得默认 False。"""
        if not result.triggered_rules:
            result.repeat_status = "not_checked"
            result.is_repeat = False
            return
        try:
            for info in result.triggered_rules:
                if _find_customer_rule_alerts(customer_id, info.rule_id, days=REPEAT_WINDOW_DAYS):
                    result.repeat_rule_ids.append(info.rule_id)
            result.is_repeat = bool(result.repeat_rule_ids)
            result.repeat_status = "checked"
        except RuleDataUnavailableError as e:
            result.repeat_status = "unavailable"
            result.is_repeat = None
            result.errors.append(
                EngineErrorInfo(rule_id="repeat_query", rule_name="30天重复触发历史查询", error=str(e))
            )

    # ----- 30 天中风险规则累计升级（只输出信号，不写 fm_flags/risk_level，不拦截交易）-----

    @classmethod
    def _resolve_escalation(cls, result: RiskRuleMatchResult, customer_id: int) -> None:
        """升级判定（聂柏确认② + 蒋智仁 A3 方案B）：历史中风险规则预警行 + 本批命中中风险规则数 >= 3
        → escalated=True、severity 强制 high/红。升级为什么落 high 不落 critical：critical 本迭代不启用
        （蒋智仁确认不引入新档位）；为什么不写 fm_flags：升级是事后监测信号，写入事前熔断字段属语义污染
        （蒋智仁三方案判定 B 胜出），由组F写预警行+工单+事件，不触碰画像。"""
        if not result.triggered_rules:
            result.escalation_status = "not_checked"
            result.escalated = False
            return
        try:
            history_counts = _count_medium_risk_history(customer_id, days=ESCALATION_WINDOW_DAYS)
            batch_ids = [t.rule_id for t in result.triggered_rules if t.rule_id in MEDIUM_RISK_RULE_IDS]
            total = sum(history_counts.values()) + len(batch_ids)
            involved = sorted({r for r, c in history_counts.items() if c > 0} | set(batch_ids))
            result.escalation_status = "checked"
            result.escalation_count = total
            result.escalation_rule_ids = involved
            if total >= 3:
                result.escalated = True
                result.escalation_reason = (
                    f"30天内中风险规则预警累计{total}次（历史{sum(history_counts.values())}"
                    f"+本批{len(batch_ids)}），升级为高风险关注"
                )
            else:
                result.escalated = False
        except RuleDataUnavailableError as e:
            result.escalation_status = "unavailable"
            result.escalated = None
            result.errors.append(
                EngineErrorInfo(rule_id="escalation_query", rule_name="30天中风险升级历史查询", error=str(e))
            )

    # ----- 三级分级 + 就高修正 -----

    @classmethod
    def _resolve_severity(cls, result: RiskRuleMatchResult) -> None:
        """severity = max(命中数档位, 批次内最高规则风险等级档位, 重复触发最低档位)，升级再强制 high。
        与 confidence 是两个独立维度，互不推导。历史查询不可用（repeat/escalation unavailable）时
        置 None——拒绝生成看似完整的可写库结果。"""
        if not result.triggered_rules:
            result.severity = None
            result.alert_level = None
            return
        if result.repeat_status == "unavailable" or result.escalation_status == "unavailable":
            result.severity = None
            result.alert_level = None
            return
        count_tier = _hit_count_tier(len(result.triggered_rules))
        risk_tier = max(
            (RISK_LEVEL_MIN_SEVERITY.get(t.risk_level, "low") for t in result.triggered_rules),
            key=lambda v: SEVERITY_RANK[v],
        )
        repeat_tier = "medium" if result.is_repeat else None
        candidates = [t for t in (count_tier, risk_tier, repeat_tier) if t]
        severity = max(candidates, key=lambda v: SEVERITY_RANK[v])
        if result.escalated:
            severity = "high"  # 30天3次中风险升级 → 落红档（聂柏确认①+蒋智仁 A3）
        result.severity = severity
        result.alert_level = SEVERITY_TO_ALERT_LEVEL[severity]

    # ----- 风控置信度（只使用自动规则命中权重，不复用记忆体系 BaseConfidenceCalc）-----

    @classmethod
    def _resolve_confidence(cls, result: RiskRuleMatchResult) -> None:
        """confidence = round(min(1.0, Σweight_tier + 0.15×is_repeat), 2)。
        只统计 status='hit'；insufficient_data 与取数失败不计入；重复奖励只有历史查询明确确认
        重复时才加；历史查询失败 → None（不能默认加或不加 0.15）；无命中 → 0。"""
        if not result.triggered_rules:
            result.confidence = 0.0
            return
        if result.repeat_status == "unavailable" or result.escalation_status == "unavailable":
            result.confidence = None
            return
        total_weight = sum(t.weight_tier for t in result.triggered_rules)
        repeat_bonus = 0.15 if result.is_repeat else 0.0
        result.confidence = round(min(1.0, total_weight + repeat_bonus), 2)

    # ----- 最终状态 -----

    @classmethod
    def _resolve_status(cls, result: RiskRuleMatchResult) -> None:
        """ok=有命中且无异常；no_hit=全部规则都明确未命中；degraded=存在取数失败或历史查询不可用
        （部分成功，写库层必须谨慎处理）；error=引擎自身异常（match 顶层兜底已处理，此处不出现）。"""
        history_unavailable = (
            result.repeat_status == "unavailable" or result.escalation_status == "unavailable"
        )
        if result.errors or history_unavailable:
            result.status = "degraded"
        elif result.triggered_rules:
            result.status = "ok"
        elif result.insufficient_rules:
            result.status = "ok"  # 部分规则无法判定：不能算"未命中"，由 insufficient_rules 承载
        else:
            result.status = "no_hit"


__all__ = [
    "RiskRuleMatch", "RiskRuleMatchResult", "TriggeredRuleInfo", "InsufficientRuleInfo",
    "EngineErrorInfo", "SEVERITY_RANK", "SEVERITY_TO_ALERT_LEVEL",
    "REPEAT_WINDOW_DAYS", "ESCALATION_WINDOW_DAYS",
]
