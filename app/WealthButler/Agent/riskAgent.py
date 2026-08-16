"""RiskAgent —— 确定性风控监测 Agent（组F，需求 F4.1）

模块职责（只做编排与副作用，不做规则判断）：
- 四个确定性入口：on_large_transaction_event / on_suspicious_intent_event（实时轨）、
  scan_daily_rules / scan_weekly_rules（批量轨）；
- 全部复用组C RiskRuleMatch.match（传不同 rule_scope / trigger_source），规则判断、
  分级、置信度、重复触发、30 天升级一律由组C引擎产出，本模块不重新计算；
- 副作用三件套（组C §11 交接契约）：fin_risk_alert 每命中规则独立一行 →
  同批按"就高原则"合并一个 biz_work_order → 每行预警发布一个 stream:risk_alert 事件；
- 幂等：事件按 trace_id+事件类型+customer_id+transaction_id/session_id 记 Redis
  SET NX（写库成功后才 claim）；批量按 run_id+customer_id+rule_id；
- 升级口径（蒋智仁 A3 + 聂柏①②）：escalated=True 时批次内告警行 severity=high/红档，
  不写 fm_flags、不改 risk_level、不拦截交易、不维护 Redis 升级计数器、不新增表字段。

边界（组F红线）：不继承 ReActAgent、无 Prompt、无 LLM 意图分类；不修改组B/C/D/E；
不直接拼 SQL；事件 payload 只作触发信号，规则事实一律回查 Model/Repository；
不实现人工上报/双录/冷静期/回访/交易阻断。

确定性：本模块无模块级可变状态；同输入、同底层数据下输出一致（run_id/时间戳除外的
内容投影一致）。
"""
import json
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from pydantic import ValidationError

from app.WealthButler.EventBus.schemas import validate_event
from app.WealthButler.Rules.ruleDefinitions import (
    DAILY_RULE_IDS,
    REALTIME_RULE_IDS,
    WEEKLY_RULE_IDS,
    RuleContext,
    RuleDataUnavailableError,
)
from app.WealthButler.Rules.ruleEngine import RiskRuleMatch, SEVERITY_TO_ALERT_LEVEL

logger = logging.getLogger(__name__)

# ======================================================================
# 常量区（写库/工单/事件/幂等的口径单点定义，禁止散落魔法数字）
# ======================================================================

SEVERITY_TO_PRIORITY: Dict[str, str] = {
    "low": "低", "medium": "中", "high": "高", "critical": "紧急",
}  # critical 本迭代不由引擎产生（蒋智仁 A3），映射仅作防御性保留
WORK_ORDER_TYPE = "风控预警"       # biz_work_order.order_type ENUM 实际值（非旧文档"风控处置"）
WORK_ORDER_SOURCE = "系统生成"
WORK_ORDER_STATUS = "待分配"
ALERT_STATUS = "待处理"
RISK_ALERT_STREAM = "stream:risk_alert"
RISK_ALERT_EVENT_TYPE = "risk_alert"
SOURCE_AGENT = "risk_agent"

IDEMPOTENCY_EVENT_KEY = "risk:idem:event:{trace_id}:{event_type}:{customer_id}:{entity_id}"
IDEMPOTENCY_SCAN_KEY = "risk:idem:scan:{run_id}:{customer_id}:{rule_id}"
IDEMPOTENCY_TTL_SECONDS = 30 * 24 * 3600   # 30 天；键含 trace_id+业务键，不阻断新交易

BATCH_CUSTOMER_LIMIT = 1000                # 批量轨单次扫描客户上限（无上限读取禁止，EB-F-01）
SCAN_TYPE_DAILY = "daily"
SCAN_TYPE_WEEKLY = "weekly"

_EMPTY_RESULT_KEYS = ("triggered_alerts", "created_work_orders", "published_events", "errors")


# ======================================================================
# 默认 provider（惰性导入/惰性连接；测试全部注入替身，MOCK_ONLY 不进入生产模块）
# ======================================================================

def _default_match(customer_id: int, rule_scope: List[str], trigger_source: str,
                   context: Optional[RuleContext] = None):
    """默认规则匹配入口：组C RiskRuleMatch.match（classmethod）。"""
    return RiskRuleMatch.match(customer_id, rule_scope, trigger_source, context=context)


def _default_transaction_provider(transaction_id: int):
    """按 transaction_id 回查 fin_transaction（事件只作触发信号，事实必须回查源表）。

    get_by_id 内部吞错返回 None，无法区分"无记录"与"取数失败"，因此先探测连接：
    连接不可用抛 RuleDataUnavailableError（→ degraded），None 视为"回查不到交易"（→ error）。
    """
    from app.WealthButler.Models.transactionModel import TransactionModel
    if TransactionModel.get_db_connection() is None:
        raise RuleDataUnavailableError(
            f"fin_transaction 数据库连接不可用，无法回查交易 {transaction_id}"
        )
    return TransactionModel.get_by_id(transaction_id)


def _default_customer_ids_provider(limit: int) -> List[int]:
    """批量轨客户 ID 来源：fin_customer_profile.get_all（每客户一行，uk_customer_id）。

    统一入口 + 显式 limit（BATCH_CUSTOMER_LIMIT）分页读取，不做全库无上限扫描；
    跨页循环与更权威的"全量客户清单"入口待确认（备案 EB-F-01），provider 可注入替换。
    """
    from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
    if CustomerProfileModel.get_db_connection() is None:
        raise RuleDataUnavailableError("fin_customer_profile 数据库连接不可用，无法获取客户ID列表")
    rows = CustomerProfileModel.get_all(limit=limit, offset=0, order_by="id", order="ASC")
    return [int(r.customer_id) for r in rows if getattr(r, "customer_id", None) is not None]


def _default_context_provider(customer_id: int) -> Dict[str, Any]:
    """画像上下文补齐 provider（生产返回空 dict：组B check 函数自带真实数据源回退，
    如 RW-016 年龄自动读 base_user.extra_data）；测试/授权场景注入已备案数据缺口。"""
    return {}


def _default_alert_writer(customer_id: int, rule_id: str, rule_name: str, severity: str,
                          confidence: Decimal, trigger_details: Optional[dict],
                          related_transaction_id: Optional[int]):
    """默认告警写入口：RiskAlertRepository.create（不直接拼 SQL）。"""
    from app.WealthButler.Repository.riskAlertRepository import RiskAlertRepository
    return RiskAlertRepository.create(
        customer_id=customer_id, rule_id=rule_id, rule_name=rule_name,
        severity=severity, confidence=confidence,
        trigger_details=trigger_details, related_transaction_id=related_transaction_id,
    )


def _default_work_order_writer(order_data: Dict[str, Any]):
    """默认工单写入口：WorkOrderModel.save()（字段按实际模型 §组F报告核对）。"""
    from app.WealthButler.Models.workOrderModel import WorkOrderModel
    order = WorkOrderModel(**order_data)
    order_id = order.save()
    if not order_id or order_id < 0:
        return None
    return order


def _default_event_publisher(stream_key: str, event_type: str, payload: Dict[str, Any],
                             source_agent: str, trace_id: Optional[str]) -> str:
    """默认事件发布入口：按**当前实际** EventBus.publish 签名调用
    （stream_key, event_type, payload, source_agent, trace_id；不照搬旧文档签名）。"""
    from app.WealthButler.EventBus.eventBus import EventBus
    return EventBus.publish(stream_key=stream_key, event_type=event_type, payload=payload,
                            source_agent=source_agent, trace_id=trace_id)


def _default_redis_client():
    """惰性获取 Redis 原生连接（幂等键用；与组E短期记忆同一连接方式）。"""
    from app.Base.Client.redisClient import RedisClient
    return RedisClient().client


class RedisIdempotencyStore:
    """幂等记录存储（Redis SET NX EX，键见 IDEMPOTENCY_*_KEY）。

    Redis 异常向上抛，由 RiskAgent 捕获后记录 degraded 风险并继续（绝不静默当作成功）；
    标记时机：写入成功后 claim（至少一次语义，崩溃窗口内可能重复写入，fin_risk_alert
    无 trace_id 列，无法做到精确一次——已在组F报告登记）。
    """

    def __init__(self, redis_factory: Callable = None):
        self._redis_factory = redis_factory or _default_redis_client

    def exists(self, key: str) -> bool:
        return bool(self._redis_factory().get(key))

    def claim(self, key: str, ttl: int = IDEMPOTENCY_TTL_SECONDS) -> bool:
        return bool(self._redis_factory().set(key, "1", nx=True, ex=ttl))


# ======================================================================
# RiskAgent
# ======================================================================

class RiskAgent:
    """确定性风控监测 Agent（需求 F4.1；Agent设计文档 §6）。

    四个入口全部返回 JSON 可序列化 dict，至少含：
    status(ok|no_hit|degraded|error) / trigger_source(event|scheduler) /
    processed_customers / triggered_alerts / created_work_orders /
    published_events / errors。
    """

    def __init__(
        self,
        match_provider: Callable = None,
        transaction_provider: Callable = None,
        customer_ids_provider: Callable = None,
        context_provider: Callable = None,
        alert_writer: Callable = None,
        work_order_writer: Callable = None,
        event_publisher: Callable = None,
        idempotency_store=None,
        batch_customer_limit: int = BATCH_CUSTOMER_LIMIT,
        now_fn: Callable = None,
    ):
        self._match = match_provider or _default_match
        self._transaction_provider = transaction_provider or _default_transaction_provider
        self._customer_ids_provider = customer_ids_provider or _default_customer_ids_provider
        self._context_provider = context_provider or _default_context_provider
        self._alert_writer = alert_writer or _default_alert_writer
        self._work_order_writer = work_order_writer or _default_work_order_writer
        self._event_publisher = event_publisher or _default_event_publisher
        self._idem = idempotency_store if idempotency_store is not None \
            else RedisIdempotencyStore()
        self._batch_customer_limit = batch_customer_limit
        self._now_fn = now_fn or datetime.now

    # ------------------------------------------------------------------
    # 实时轨：大额交易事件
    # ------------------------------------------------------------------

    def on_large_transaction_event(self, payload, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """实时轨入口一：消费 stream:large_transaction。

        流程：schemas 校验 → 幂等检查 → 按 transaction_id 回查 fin_transaction →
        客户归属校验 → RuleContext（事件 payload 不作为规则事实）→
        RiskRuleMatch.match(REALTIME_RULE_IDS, 'event') → 告警/工单/事件三件套。
        """
        base = self._event_base("event")
        try:
            event = validate_event("large_transaction", payload)
        except (ValidationError, ValueError) as exc:
            base["status"] = "error"
            base["errors"].append(f"large_transaction 事件校验失败: {exc}")
            return base
        customer_id = event.customer_id
        transaction_id = event.transaction_id
        if customer_id <= 0 or transaction_id <= 0:
            base["status"] = "error"
            base["errors"].append(
                f"事件 customer_id/transaction_id 必须为正整数: "
                f"customer_id={customer_id!r}, transaction_id={transaction_id!r}"
            )
            return base
        trace_id = trace_id or str(uuid.uuid4())
        idem_key = IDEMPOTENCY_EVENT_KEY.format(
            trace_id=trace_id, event_type="large_transaction",
            customer_id=customer_id, entity_id=transaction_id,
        )

        # 幂等：同一 trace 重复投递不重复处理
        try:
            if self._idem.exists(idem_key):
                result = dict(base)
                result["status"] = "ok"
                result["processed_customers"] = [customer_id]
                result["idempotent"] = "skipped"
                result["trace_id"] = trace_id
                return result
        except Exception as exc:
            base["errors"].append(f"幂等检查不可用（Redis 异常，可能重复处理）: {exc}")

        # 回查源表：事件 payload 只作触发信号
        try:
            tx = self._transaction_provider(transaction_id)
        except RuleDataUnavailableError as exc:
            base["status"] = "degraded"
            base["errors"].append(f"交易回查不可用，不生成告警: {exc}")
            base["trace_id"] = trace_id
            return base
        if tx is None:
            base["status"] = "error"
            base["errors"].append(f"回查不到交易 transaction_id={transaction_id}，禁止用事件金额伪造命中")
            base["trace_id"] = trace_id
            return base
        tx_customer = getattr(tx, "customer_id", None)
        if tx_customer != customer_id:
            base["status"] = "error"
            base["errors"].append(
                f"事件客户与交易归属不一致: 事件 customer_id={customer_id}, "
                f"交易归属 customer_id={tx_customer}"
            )
            base["trace_id"] = trace_id
            return base

        try:
            ctx = self._build_context(customer_id)
            match_result = self._match(customer_id, list(REALTIME_RULE_IDS), "event", context=ctx)
        except ValueError as exc:
            base["status"] = "error"
            base["errors"].append(f"规则匹配参数错误: {exc}")
            base["trace_id"] = trace_id
            return base
        except Exception as exc:
            base["status"] = "error"
            base["errors"].append(f"规则匹配异常: {exc}")
            base["trace_id"] = trace_id
            return base

        final = self._process_match_result(
            customer_id, match_result, trace_or_run_id=trace_id,
            extra_details={"event_transaction_id": transaction_id},
        )
        final["trace_id"] = trace_id
        # 前置阶段（幂等检查等）的 degraded 风险必须保留并影响整体状态
        if base["errors"]:
            if final["status"] in ("ok", "no_hit"):
                final["status"] = "degraded"
            final["errors"] = base["errors"] + final["errors"]
        # 写库成功后 claim（至少一次语义；claim 失败记录风险不阻断）
        if final["status"] in ("ok", "degraded") and final["triggered_alerts"]:
            try:
                self._idem.claim(idem_key)
            except Exception as exc:
                final["status"] = "degraded"
                final["errors"].append(f"幂等标记失败（重复投递可能重复写告警）: {exc}")
        return final

    # ------------------------------------------------------------------
    # 实时轨：可疑意图事件
    # ------------------------------------------------------------------

    def on_suspicious_intent_event(self, payload, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """实时轨入口二：消费 stream:suspicious_intent。

        suspicious intent 同样只是触发信号：intent_type/confidence/suspicious_text/
        evidence/session_id/trace_id 完整保留到 trigger_details，规则事实仍回查源表。
        事件校验失败、customer_id 缺失或查询失败时不生成完整风险告警。
        """
        base = self._event_base("event")
        try:
            event = validate_event("suspicious_intent", payload)
        except (ValidationError, ValueError) as exc:
            base["status"] = "error"
            base["errors"].append(f"suspicious_intent 事件校验失败: {exc}")
            return base
        customer_id = event.customer_id
        if customer_id <= 0:
            base["status"] = "error"
            base["errors"].append(f"事件 customer_id 必须为正整数: {customer_id!r}")
            return base
        trace_id = trace_id or str(uuid.uuid4())
        session_id = event.session_id or ""
        idem_key = IDEMPOTENCY_EVENT_KEY.format(
            trace_id=trace_id, event_type="suspicious_intent",
            customer_id=customer_id, entity_id=session_id or "no-session",
        )
        try:
            if self._idem.exists(idem_key):
                result = dict(base)
                result["status"] = "ok"
                result["processed_customers"] = [customer_id]
                result["idempotent"] = "skipped"
                result["trace_id"] = trace_id
                return result
        except Exception as exc:
            base["errors"].append(f"幂等检查不可用（Redis 异常，可能重复处理）: {exc}")

        # 意图证据：完整保留（不进规则判定，只进 trigger_details 留痕）
        intent_evidence = {
            "intent_type": event.intent_type,
            "confidence": event.confidence,
            "suspicious_text": event.suspicious_text,
            "evidence": event.evidence,
            "session_id": event.session_id,
            "event_trace_id": trace_id,
        }
        try:
            ctx = self._build_context(customer_id)
            match_result = self._match(customer_id, list(REALTIME_RULE_IDS), "event", context=ctx)
        except ValueError as exc:
            base["status"] = "error"
            base["errors"].append(f"规则匹配参数错误: {exc}")
            base["trace_id"] = trace_id
            return base
        except Exception as exc:
            base["status"] = "error"
            base["errors"].append(f"规则匹配异常: {exc}")
            base["trace_id"] = trace_id
            return base

        final = self._process_match_result(
            customer_id, match_result, trace_or_run_id=trace_id,
            extra_details={"suspicious_intent": intent_evidence},
        )
        final["trace_id"] = trace_id
        # 前置阶段（幂等检查等）的 degraded 风险必须保留并影响整体状态
        if base["errors"]:
            if final["status"] in ("ok", "no_hit"):
                final["status"] = "degraded"
            final["errors"] = base["errors"] + final["errors"]
        if final["status"] in ("ok", "degraded") and final["triggered_alerts"]:
            try:
                self._idem.claim(idem_key)
            except Exception as exc:
                final["status"] = "degraded"
                final["errors"].append(f"幂等标记失败（重复投递可能重复写告警）: {exc}")
        return final

    # ------------------------------------------------------------------
    # 批量轨
    # ------------------------------------------------------------------

    def scan_daily_rules(self, customer_ids: Optional[List[int]] = None,
                         run_id: Optional[str] = None) -> Dict[str, Any]:
        """日批入口：对 DAILY_RULE_IDS（10 条）批量扫描。

        customer_ids 仅测试/局部扫描/已授权调用使用；缺省走 customer_ids_provider
        （显式上限）。单客户失败不中断其他客户；run_id 贯穿本批（审计/幂等）。
        """
        return self._scan(SCAN_TYPE_DAILY, list(DAILY_RULE_IDS), customer_ids, run_id)

    def scan_weekly_rules(self, customer_ids: Optional[List[int]] = None,
                          run_id: Optional[str] = None) -> Dict[str, Any]:
        """周批入口：对 WEEKLY_RULE_IDS（2 条）批量扫描。"""
        return self._scan(SCAN_TYPE_WEEKLY, list(WEEKLY_RULE_IDS), customer_ids, run_id)

    def _scan(self, scan_type: str, rule_scope: List[str],
              customer_ids: Optional[List[int]], run_id: Optional[str]) -> Dict[str, Any]:
        now = self._now_fn()
        run_id = run_id or f"{scan_type}-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        aggregate: Dict[str, Any] = {
            "status": "no_hit",
            "trigger_source": "scheduler",
            "scan_type": scan_type,
            "run_id": run_id,
            "processed_customers": [],
            "triggered_alerts": [],
            "created_work_orders": [],
            "published_events": [],
            "errors": [],
            "idempotent_skipped": 0,
            "insufficient_notes": [],
        }
        if customer_ids is None:
            try:
                customer_ids = self._customer_ids_provider(self._batch_customer_limit)
            except RuleDataUnavailableError as exc:
                aggregate["status"] = "degraded"
                aggregate["errors"].append(f"批量轨客户ID来源不可用（EB-F-01）: {exc}")
                return aggregate
            except Exception as exc:
                aggregate["status"] = "degraded"
                aggregate["errors"].append(f"批量轨客户ID来源异常: {exc}")
                return aggregate
        else:
            if not isinstance(customer_ids, (list, tuple)):
                raise ValueError(f"customer_ids 必须是列表或 None，收到: {type(customer_ids)!r}")
            if len(customer_ids) > self._batch_customer_limit:
                raise ValueError(
                    f"customer_ids 超过批量上限 {self._batch_customer_limit}（无上限读取禁止）"
                )
        if not customer_ids:
            return aggregate  # 无客户 → no_hit，无副作用

        any_hit = False
        any_degraded = False
        all_failed = True
        for cid in customer_ids:
            try:
                if isinstance(cid, bool) or not isinstance(cid, int) or cid <= 0:
                    raise ValueError(f"客户ID必须为正整数: {cid!r}")
                ctx = self._build_context(cid)
                match_result = self._match(cid, rule_scope, "scheduler", context=ctx)
                per = self._process_match_result(
                    cid, match_result, trace_or_run_id=run_id, scan_run_id=run_id,
                )
                aggregate["processed_customers"].append(cid)
                aggregate["triggered_alerts"].extend(per["triggered_alerts"])
                aggregate["created_work_orders"].extend(per["created_work_orders"])
                aggregate["published_events"].extend(per["published_events"])
                aggregate["errors"].extend(per["errors"])
                aggregate["insufficient_notes"].extend(per.get("insufficient_notes", []))
                aggregate["idempotent_skipped"] += per.get("idempotent_skipped", 0)
                if per["status"] in ("ok", "degraded"):
                    all_failed = False
                if per["status"] == "degraded":
                    any_degraded = True
                if per["triggered_alerts"]:
                    any_hit = True
            except Exception as exc:
                # 单客户失败不中断其他客户
                aggregate["errors"].append(f"customer_id={cid} 扫描失败: {exc}")
                any_degraded = True
        if all_failed:
            aggregate["status"] = "degraded" if aggregate["errors"] else "no_hit"
        elif aggregate["errors"] or any_degraded:
            aggregate["status"] = "degraded"
        elif any_hit:
            aggregate["status"] = "ok"
        else:
            aggregate["status"] = "no_hit"
        return aggregate

    # ------------------------------------------------------------------
    # 内部：context 构建 与 引擎结果 → 副作用三件套
    # ------------------------------------------------------------------

    def _build_context(self, customer_id: int) -> RuleContext:
        """构建 RuleContext：ref_time 固定为当前时刻（同批规则一致）+ 注入 provider 上下文。

        生产默认不注入业务字段：组B check 函数自带真实数据源回退
        （如 RW-016 年龄自动读 base_user.extra_data、RW-014/006/013 等缺失时
        返回 insufficient_data 并留痕，绝不静默默认）。
        """
        extra = self._context_provider(customer_id) or {}
        if not isinstance(extra, dict):
            raise ValueError(f"context_provider 必须返回 dict，收到: {type(extra)!r}")
        return RuleContext(ref_time=self._now_fn(), **extra)

    @staticmethod
    def _event_base(trigger_source: str) -> Dict[str, Any]:
        return {
            "status": "ok",
            "trigger_source": trigger_source,
            "processed_customers": [],
            "triggered_alerts": [],
            "created_work_orders": [],
            "published_events": [],
            "errors": [],
            "insufficient_notes": [],
        }

    def _process_match_result(self, customer_id: int, match_result, trace_or_run_id: str,
                              extra_details: Optional[Dict[str, Any]] = None,
                              scan_run_id: Optional[str] = None) -> Dict[str, Any]:
        """组C RiskRuleMatchResult → 告警/工单/事件三件套（组F 核心映射）。

        状态处理原则（任务§九）：
        - error → 不写告警/不建工单/不发事件，返回 error；
        - no_hit → 无副作用返回 no_hit；
        - degraded 且 severity/confidence 为 None → 不生成看似完整的告警，返回 degraded；
        - degraded 但存在 confirmed hit 且 severity/confidence 完整 → 写入已确认规则，
          整体结果保持 degraded（报告已说明）；
        - ok 且有命中 → 三件套。
        """
        base = {
            "status": match_result.status,
            "trigger_source": match_result.trigger_source,
            "processed_customers": [],
            "triggered_alerts": [],
            "created_work_orders": [],
            "published_events": [],
            "errors": [],
            "insufficient_notes": [],
        }
        engine_errors = [f"[{e.rule_id}] {e.error}" for e in (match_result.errors or [])]
        insufficient_notes = [
            f"[{i.rule_id}] 数据不足无法判定: {i.reason or i.missing_fields}"
            for i in (match_result.insufficient_rules or [])
        ]

        if match_result.status == "error":
            base["errors"] = engine_errors or ["规则引擎返回 error"]
            return base
        if not match_result.triggered_rules:
            # 无命中：无副作用；状态沿用引擎分级（ok=仅数据不足/no_hit=干净未命中/
            # degraded=存在取数失败）；insufficient 与 errors 分别留痕，不互相改写
            base["processed_customers"] = [customer_id]
            base["errors"] = engine_errors
            base["insufficient_notes"] = insufficient_notes
            return base
        severity = match_result.severity
        confidence = match_result.confidence
        if severity is None or confidence is None:
            # 历史查询不可用：拒绝生成看似完整的告警（组C契约）
            base["status"] = "degraded"
            base["processed_customers"] = [customer_id]
            base["errors"] = engine_errors + [
                "severity/confidence 不完整（重复/升级历史查询不可用），拒绝写库"
            ]
            base["insufficient_notes"] = insufficient_notes
            return base
        if severity not in ("low", "medium", "high"):
            base["status"] = "degraded"
            base["processed_customers"] = [customer_id]
            base["errors"] = engine_errors + [f"引擎输出非法 severity: {severity!r}，拒绝写库"]
            base["insufficient_notes"] = insufficient_notes
            return base

        base["processed_customers"] = [customer_id]
        base["insufficient_notes"] = insufficient_notes
        errors: List[str] = list(engine_errors)  # insufficient 不改写状态分级（引擎口径）
        alert_rows: List[Dict[str, Any]] = []
        idem_skipped = 0

        # ---- 1. 告警：每命中规则独立一行 ----
        for rule in match_result.triggered_rules:
            if scan_run_id is not None:
                idem_key = IDEMPOTENCY_SCAN_KEY.format(
                    run_id=scan_run_id, customer_id=customer_id, rule_id=rule.rule_id)
                try:
                    if self._idem.exists(idem_key):
                        idem_skipped += 1
                        continue  # 本批本规则已完成（写后标记），跳过
                except Exception as exc:
                    errors.append(f"批量幂等检查不可用（可能重复写告警）: {exc}")
            trigger_details = self._build_trigger_details(
                match_result, rule, trace_or_run_id, extra_details)
            try:
                alert = self._alert_writer(
                    customer_id=customer_id,
                    rule_id=rule.rule_id,
                    rule_name=rule.rule_name,
                    severity=severity,
                    confidence=Decimal(str(round(float(confidence), 3))),
                    trigger_details=trigger_details,
                    related_transaction_id=rule.primary_transaction_id,  # 无主交易用 None，不臆造
                )
            except Exception as exc:
                errors.append(f"{rule.rule_id} 告警写入异常: {exc}")
                continue
            if alert is None or getattr(alert, "id", None) in (None, -1):
                errors.append(f"{rule.rule_id} 告警写入失败（未创建）")
                continue
            alert_rows.append({"alert": alert, "rule": rule})
            base["triggered_alerts"].append({
                "alert_id": alert.id,
                "rule_id": rule.rule_id,
                "rule_name": rule.rule_name,
                "severity": severity,
                "confidence": float(confidence),
                "related_transaction_id": rule.primary_transaction_id,
            })
            if scan_run_id is not None:
                try:
                    self._idem.claim(idem_key)  # 写入成功后才标记完成
                except Exception as exc:
                    errors.append(f"批量幂等标记失败（本批重跑可能重复写 {rule.rule_id}）: {exc}")

        if not alert_rows:
            if idem_skipped:
                # 引擎有命中但本 run 已处理过（写后标记）：无副作用，按 ok + 标记返回
                base["status"] = "ok"
                base["idempotent_skipped"] = idem_skipped
            else:
                base["status"] = "degraded" if errors else "no_hit"
            base["errors"] = errors
            return base

        # ---- 2. 工单：同客户同批最多一个（就高原则）----
        try:
            order = self._create_work_order(customer_id, alert_rows, match_result)
        except Exception as exc:
            order = None
            errors.append(f"工单创建异常: {exc}")
        if order is None:
            errors.append("工单创建失败（告警已保留，闭环未伪造）")
        else:
            base["created_work_orders"].append({
                "order_id": order.id,
                "order_no": order.order_no,
                "priority": SEVERITY_TO_PRIORITY.get(severity, "中"),
                "related_entity_type": "alert",
                "related_entity_id": order.related_entity_id,
                "rule_ids": [r["rule"].rule_id for r in alert_rows],
            })

        # ---- 3. 事件：每行预警发布一个 risk_alert ----
        for row in alert_rows:
            published = self._publish_alert_event(customer_id, row, severity, trace_or_run_id)
            if published is None:
                errors.append(f"{row['rule'].rule_id} risk_alert 事件发布失败")
                continue
            base["published_events"].append(published)

        # ---- 4. 状态：写入/发布失败 → degraded（绝不声称已创建/已发布）----
        base["status"] = "degraded" if errors else match_result.status
        base["errors"] = errors
        return base

    def _build_trigger_details(self, match_result, rule, trace_or_run_id: str,
                               extra_details: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """trigger_details 合同（任务§十）：trigger_source / trace_id 或 run_id /
        规则命中详情 / related_transaction_ids / primary_transaction_id /
        engine_status / 规则错误（如有）/ 事件轨证据（如有）/ 升级证据（如有）。"""
        details: Dict[str, Any] = {
            "trigger_source": match_result.trigger_source,
            "trace_id" if match_result.trigger_source == "event" else "run_id": trace_or_run_id,
            "rule_details": rule.details or {},
            "related_transaction_ids": rule.related_transaction_ids or [],
            "primary_transaction_id": rule.primary_transaction_id,
            "engine_status": match_result.status,
            "rule_errors": [e.error for e in (match_result.errors or [])
                            if getattr(e, "rule_id", None) == rule.rule_id],
        }
        if extra_details:
            details.update(extra_details)
        if match_result.escalated:
            details["escalation"] = {
                "escalated": match_result.escalated,
                "escalation_count": match_result.escalation_count,
                "escalation_rule_ids": match_result.escalation_rule_ids,
                "escalation_reason": match_result.escalation_reason,
            }
        return details

    def _create_work_order(self, customer_id: int, alert_rows: List[Dict[str, Any]],
                           match_result) -> Optional[Any]:
        """同客户同批合并一个风险处置工单（就高原则）。

        主告警选择（稳定且已在报告说明）：引擎按 (priority, rule_id) 排序产出命中规则，
        alert_rows 按该顺序创建 → **主告警 = 批次内最先创建的告警**（即最高优先级规则）；
        related_entity_id 指向该真实告警 ID，不写不存在的 ID。
        """
        primary = alert_rows[0]
        severity = match_result.severity
        alert_level = SEVERITY_TO_ALERT_LEVEL.get(severity, severity)
        now = self._now_fn()
        rule_ids = [row["rule"].rule_id for row in alert_rows]
        description = json.dumps(
            {
                "hit_rule_count": len(alert_rows),
                "rules": [
                    {"rule_id": row["rule"].rule_id, "rule_name": row["rule"].rule_name,
                     "alert_id": row["alert"].id, "severity": severity}
                    for row in alert_rows
                ],
                "escalated": match_result.escalated,
                "escalation_count": match_result.escalation_count,
                "escalation_rule_ids": match_result.escalation_rule_ids,
            },
            ensure_ascii=False,
        )
        order_data = {
            "order_no": f"WO-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}",
            "order_type": WORK_ORDER_TYPE,
            "source": WORK_ORDER_SOURCE,
            "customer_id": customer_id,
            "title": f"风控预警：客户{customer_id}命中{len(alert_rows)}条规则（{alert_level}）",
            "description": description,
            "priority": SEVERITY_TO_PRIORITY.get(severity, "中"),
            "status": WORK_ORDER_STATUS,
            "related_entity_type": "alert",
            "related_entity_id": primary["alert"].id,
        }
        return self._work_order_writer(order_data)

    def _publish_alert_event(self, customer_id: int, row: Dict[str, Any], severity: str,
                             trace_or_run_id: str) -> Optional[Dict[str, Any]]:
        """发布单行告警的 stream:risk_alert 事件（payload 必须通过 RiskAlertEvent 校验）。"""
        alert = row["alert"]
        rule = row["rule"]
        payload = {
            "customer_id": customer_id,
            "alert_id": alert.id,
            "rule_id": rule.rule_id,
            "severity": severity,
            "trigger_details": {
                "rule_name": rule.rule_name,
                "alert_level": SEVERITY_TO_ALERT_LEVEL.get(severity, severity),
                "engine_status": "ok",
            },
            "created_at": self._now_fn().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            validate_event(RISK_ALERT_EVENT_TYPE, payload)  # 发布前 schema 自检
            message_id = self._event_publisher(
                stream_key=RISK_ALERT_STREAM, event_type=RISK_ALERT_EVENT_TYPE,
                payload=payload, source_agent=SOURCE_AGENT, trace_id=trace_or_run_id,
            )
        except Exception as exc:
            logger.error("risk_alert 事件发布失败: %s", exc)
            return None
        return {
            "message_id": message_id,
            "stream_key": RISK_ALERT_STREAM,
            "event_type": RISK_ALERT_EVENT_TYPE,
            "trace_id": trace_or_run_id,
            "alert_id": alert.id,
            "rule_id": rule.rule_id,
        }


# ======================================================================
# EventBus handler 适配（业务结果 dict ≠ EventBus ACK 布尔）
# ======================================================================

def large_transaction_event_handler(event_type: str, payload: Dict[str, Any],
                                    trace_id: str) -> bool:
    """EventBus handler 适配：stream:large_transaction。

    返回 True/False 语义（当前 EventBus 实际合同：False → 死信队列）：
    业务 status=error → False；ok/no_hit/degraded → True（degraded 已结构化留痕，
    避免环境性降级刷爆死信队列，口径已登记组F报告）。
    """
    result = RiskAgent().on_large_transaction_event(payload, trace_id=trace_id)
    logger.info("large_transaction 事件处理结果: status=%s trace_id=%s",
                result.get("status"), trace_id)
    return result.get("status") != "error"


def suspicious_intent_event_handler(event_type: str, payload: Dict[str, Any],
                                    trace_id: str) -> bool:
    """EventBus handler 适配：stream:suspicious_intent（语义同上）。"""
    result = RiskAgent().on_suspicious_intent_event(payload, trace_id=trace_id)
    logger.info("suspicious_intent 事件处理结果: status=%s trace_id=%s",
                result.get("status"), trace_id)
    return result.get("status") != "error"


__all__ = [
    "RiskAgent", "RedisIdempotencyStore",
    "large_transaction_event_handler", "suspicious_intent_event_handler",
    "SEVERITY_TO_PRIORITY", "RISK_ALERT_STREAM", "RISK_ALERT_EVENT_TYPE",
    "BATCH_CUSTOMER_LIMIT", "IDEMPOTENCY_EVENT_KEY", "IDEMPOTENCY_SCAN_KEY",
]
