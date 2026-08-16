"""风控监测Agent 规则定义层（组B）

模块职责：
- 唯一事实来源 AML_RULES：20 条反洗钱规则（RW-001~RW-020）的元数据（scope/风险等级/权重/优先级/阈值/源表字段）；
- 20 个独立规则检查函数 check_rw001 ~ check_rw020，每条函数只读数据、只做单规则判定，返回 RuleHit | None；
- 所有阈值集中在本模块顶部常量区，禁止散落裸数字（《研判规则提取与落地方案》§1 要求）。

组B边界（不在本模块实现）：规则引擎聚合（ruleEngine.py）、RiskRuleMatch、三级预警分级、风控置信度、
30 天重复触发聚合、fin_risk_alert/biz_work_order 写库、EventBus、API——全部留给组C/F。

设计要点：
- 检查函数统一签名 check_rwXXX(customer_id, context=None) -> Optional[RuleHit]；
  未命中返回 None；命中返回 RuleHit(status='hit')；依赖数据缺失返回 RuleHit(status='insufficient_data')，
  严格区分"未命中"与"无法判定"（《风控监测Agent轨道开发计划》组A结论）。
- 数据库访问全部经过模块内 _fetch_* / _get_* 提供函数（复用 Models 既有查询方法，惰性导入模型类）：
  单元测试通过 mock.patch.object 替换提供函数，即可完全不依赖真实数据库。
- 交易方向约定（备案 EB-B-01）：fin_transaction 无方向字段，本层按"入账交易 payer_account_name 非空且
  counterparty_account 为空；转出交易 counterparty_account 非空且 payer_account_name 为空"推断方向，
  两条线都非空的记录不参与方向判定。该约定已由聂柏确认（2026-08，见组A组B报告确认纪要）。
- 本模块不包含任何动态执行代码路径，金额统一用 Decimal 比较，所有金额单位为人民币元。
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ======================================================================
# 阈值集中管理（来源：《反洗钱可疑交易识别规则.md》JR-AML-RULE-2024-001 第二章；
# 报告线另见需求文档§5.2"大额交易报告线"。金额单位：人民币元；边界均为 >=（含等值），
# 特殊注明 < 或 > 的除外；时间窗口"自然日"=含基准日在内的日历日，"小时"=滚动小时。）
# ======================================================================

# 大额交易报告线（需求文档§5.2）
AML_REPORT_LINE_CASH = Decimal("50000")       # 现金：单笔/当日累计 >= 5万元
AML_REPORT_LINE_TRANSFER = Decimal("200000")  # 转账：单笔 >= 20万元

# RW-001 大额现金交易（单日累计现金 >= 5万元，或等值1万美元）
RW001_DAILY_CASH_LIMIT = Decimal("50000")     # 边界：>=；窗口：1个自然日
RW001_DAILY_CASH_LIMIT_USD = Decimal("10000")  # 等值1万美元分支（备案 EB-B-02：无汇率来源，本组未启用）

# RW-002 频繁小额交易（蚂蚁搬家）
RW002_WINDOW_DAYS = 7                         # 7个自然日
RW002_MIN_TX_COUNT = 20                       # 笔数 >= 20
RW002_MIN_TOTAL_AMOUNT = Decimal("100000")    # 累计金额 >= 10万元
# 补充条件"单笔低于大额报告标准"复用 AML_REPORT_LINE_CASH / AML_REPORT_LINE_TRANSFER

# RW-003 资金快进快出（入账后24小时内转出 >= 入账金额90%，且转出 >= 5万元）
RW003_WINDOW_HOURS = 24                       # 滚动小时，含24小时整点
RW003_MIN_OUTFLOW_RATIO = Decimal("0.90")     # 0-1 小数（90%）
RW003_MIN_OUTFLOW_AMOUNT = Decimal("50000")   # 转出金额下限
RW003_INFLOW_LOOKBACK_DAYS = 7                # 入账候选回看窗口（自然日，超出不再配对）

# RW-004 分散转入集中转出
RW004_WINDOW_DAYS = 5                         # 5个自然日
RW004_MIN_SOURCE_ACCOUNTS = 5                 # 不同来源账户 >= 5
RW004_MIN_OUTFLOW_TOTAL = Decimal("200000")   # 转出金额 >= 20万元
RW004_CONCENTRATION_RATIO = Decimal("0.80")   # 转出对手方集中度 >= 80%

# RW-005 集中转入分散转出
RW005_WINDOW_DAYS = 5                         # 5个自然日
RW005_MIN_INFLOW_SINGLE = Decimal("100000")   # 单笔大额转入 >= 10万元
RW005_FOLLOW_DAYS = 3                         # 随后3个自然日（含第3天全天）
RW005_MIN_DISPERSED_ACCOUNTS = 5              # 分散转出账户 >= 5
# 补充条件"单笔转出低于大额报告标准"复用 AML_REPORT_LINE_TRANSFER

# RW-006 交易金额与客户身份严重不符（单日交易 >= 申报年收入×3 且 >= 10万元）
RW006_INCOME_MULTIPLIER = 3
RW006_MIN_DAILY_AMOUNT = Decimal("100000")

# RW-007 短期内频繁开销户（同一证件30日内开户>=3次 或 开户后30天内销户>=2次）
RW007_OPEN_WINDOW_DAYS = 30
RW007_MIN_OPENS = 3
RW007_MIN_CLOSES_WITHIN_DAYS = 2
RW007_CLOSE_AFTER_OPEN_DAYS = 30

# RW-008 非正常时段大额交易（凌晨0:00-6:00 单笔>=10万 或 单日累计>=20万，且90天同时段无先例）
RW008_NIGHT_START_HOUR = 0
RW008_NIGHT_END_HOUR = 6                      # [0, 6) 小时，06:00 不含
RW008_NIGHT_SINGLE_LIMIT = Decimal("100000")
RW008_NIGHT_DAILY_LIMIT = Decimal("200000")
RW008_BASELINE_DAYS = 90                      # 90个自然日基线（不含基准日）
RW008_PRECEDENT_AMOUNT = Decimal("100000")    # "类似交易先例"口径：先例=夜间单笔>=10万（备案 EB-B-14）

# RW-009 交易金额刻意规避报告标准（30日内 >= 5笔"报告线整数减1"）
RW009_WINDOW_DAYS = 30
RW009_MIN_EVASION_COUNT = 5
# 规避金额集合 = 原文示例（49,999/199,999/9,999）+ 报告线（5万/20万/50万/200万）减1
RW009_EVASION_AMOUNTS = frozenset({
    Decimal("49999"), Decimal("199999"), Decimal("499999"), Decimal("1999999"), Decimal("9999"),
})

# RW-010 关联方之间异常资金往来（同一对手方7日内双向>=3次 且 净额<总额20%）
RW010_WINDOW_DAYS = 7
RW010_MIN_BIDIRECTIONAL_COUNT = 3
RW010_MAX_NET_RATIO = Decimal("0.20")         # 净额/总额 < 20%（严格小于）

# RW-011 涉及高风险国家/地区的资金往来（FATF黑/灰名单或OFAC制裁国家 且 金额>=1万元）
RW011_MIN_AMOUNT = Decimal("10000")
# 备案 EB-B-07：完整名单在规则附件四（动态更新），本常量仅含原文点名的示例国家，生产启用前须合规确认
RW011_HIGH_RISK_REGIONS = frozenset({"伊朗", "朝鲜", "叙利亚"})

# RW-012 基金产品频繁申购赎回（同一产品30日内申购>=3 且 赎回>=3，单次持有期<7天）
RW012_WINDOW_DAYS = 30
RW012_MIN_PURCHASES = 3
RW012_MIN_REDEMPTIONS = 3
RW012_MAX_HOLDING_DAYS = 7                    # 持有期 < 7个自然日（备案 EB-B-09：用相邻申购-赎回间隔近似）

# RW-013 PEP 关联账户异常（PEP标记 且 单笔>=20万/新增境外对手方/3月模式变化>50% 任一）
RW013_MIN_SINGLE_AMOUNT = Decimal("200000")
RW013_FOREIGN_LOOKBACK_DAYS = 90              # 新增境外对手方回看90个自然日
RW013_PATTERN_CHANGE_RATIO = Decimal("0.50")  # 交易模式变化 > 50%（严格大于）
RW013_PRIOR_MONTHS = 3                        # "前3个月"月均基线的月数
RW013_DOMESTIC_REGIONS = frozenset({"中国", "中国大陆"})  # 非境内即视为境外（港澳台口径备案 EB-B-13）

# RW-014 非本人账户代付投资款（资金来源账户名 != 投资账户名 且 代付>=5万元）
RW014_MIN_AMOUNT = Decimal("50000")

# RW-015 身份信息变更后立即大额交易（关键身份信息变更后72小时内 单笔>=10万元）
RW015_CHANGE_WINDOW_HOURS = 72                # 滚动小时，含72小时整点
RW015_MIN_AMOUNT = Decimal("100000")

# RW-016 老年客户异常大额资金转出（年龄>=65 且 [单笔转出>=10万 或 7日累计>=20万] 且 超12个月月均3倍）
RW016_MIN_AGE = 65
RW016_MIN_SINGLE_OUTFLOW = Decimal("100000")
RW016_7D_OUTFLOW_TOTAL = Decimal("200000")
RW016_WINDOW_DAYS = 7
RW016_AVG_WINDOW_DAYS = 365                   # 12个月月均基线窗口（自然日）
RW016_MONTHLY_AVG_MULTIPLIER = 3              # "超过...3倍"（严格大于，备案 EB-B-15：月均为0时口径）
RW016_MONTHS_PER_YEAR = 12                    # 年化月数（月均 = 365天转出总额 / 12）

# RW-017 新开户短期内大额交易（开户30个自然日内 单笔>=20万 或 累计>=50万）
RW017_OPEN_WINDOW_DAYS = 30
RW017_MIN_SINGLE_AMOUNT = Decimal("200000")
RW017_MIN_TOTAL_AMOUNT = Decimal("500000")

# RW-018 多账户关联资金归集（同一设备指纹关联>=3个账户，7日内归集入同一目标账户>=30万元）
RW018_WINDOW_DAYS = 7
RW018_MIN_LINKED_ACCOUNTS = 3
RW018_MIN_AGGREGATED_AMOUNT = Decimal("300000")

# RW-019 疑似涉赌/涉诈资金流转（三特征同时满足）
RW019_MAX_INFLOW_SINGLE = Decimal("5000")     # 入金单笔 < 5000元（严格小于）
RW019_MAX_INFLOW_DAILY = Decimal("20000")     # 入金日累计 < 20000元（严格小于）
RW019_MIN_OUTFLOW_SINGLE = Decimal("50000")   # 出金单笔 >= 50000元（或整数金额）
RW019_NIGHT_START_HOUR = 20                   # 入金集中时段 [20,24) ∪ [0,2) 小时
RW019_NIGHT_END_HOUR = 2

# RW-020 与离岸金融中心公司异常交易（离岸地区 且 金额>=10万元 且 非专业投资机构）
RW020_MIN_AMOUNT = Decimal("100000")
# 备案 EB-B-08：原文列举例含"等"字，集合完整性待合规确认
RW020_OFFSHORE_REGIONS = frozenset({
    "英属维尔京群岛", "BVI", "开曼群岛", "百慕大", "巴拿马", "塞舌尔",
})

# 权重档位（需求文档§5.4.2，团队拟定示例值，分类标准挂钩规则原文🔴🟠🟡🔵风险等级）
WEIGHT_STRONG = 0.35   # 强信号 = 🔴高风险
WEIGHT_MEDIUM = 0.20   # 中信号 = 🟠中高风险
WEIGHT_WEAK = 0.10     # 弱信号 = 🟡中风险 / 🔵低风险

# ======================================================================
# 聂柏确认口径（2026-08，见组A组B报告《聂柏确认纪要》）
# ① 三级预警分级 = 命中数档位 与 批次内最高规则风险等级档位 取高（"就高修正"）：
#    命中数档位：1条→low / 2-3条或重复→medium / >3条→high；
#    风险等级档位：🔴高风险→high / 🟠中高风险→medium / 🟡中风险·🔵低风险→low；
#    "30天内累计≥3次中风险预警升级"的预警行落 severity='high'（红档）；
#    critical 为模型既有枚举值但本迭代不启用（蒋智仁 A3 确认：升级不引入新档位，
#    否则 NL2SQL 白名单/查询口径要跟着变）。
#    severity 的计算与写库属组C职责，本层只提供映射依据，不做分级。
# ② "30天内累计触发≥3次中风险预警升级"按原文口径计数：统计风险等级为"中风险（🟡）"的规则
#    （MEDIUM_RISK_RULE_IDS）的预警行，不按 severity='medium' 行数计数。
# ======================================================================

# 规则原文风险等级 → 预警 severity 最低档位（就高修正依据，组C实现分级时直接使用）
RISK_LEVEL_MIN_SEVERITY: Dict[str, str] = {
    "高风险": "high",
    "中高风险": "medium",
    "中风险": "low",
    "低风险": "low",
}

# 原文风险等级为"中风险"的规则集合（30天升级机制的计数范围，确认口径②）
MEDIUM_RISK_RULE_IDS: Tuple[str, ...] = ("RW-001", "RW-007", "RW-012", "RW-015")

# 单客户单次流水拉取上限（备案 EB-B-12：超出截断可能漏检更早流水，测试数据量级下无影响）
QUERY_TX_LIMIT = 1000

# 规则中文名（唯一命名来源，check 函数与 AML_RULES 元数据共用，避免两处维护漂移）
RULE_NAMES: Dict[str, str] = {
    "RW-001": "大额现金交易",
    "RW-002": "频繁小额交易（蚂蚁搬家）",
    "RW-003": "资金快进快出",
    "RW-004": "分散转入集中转出",
    "RW-005": "集中转入分散转出",
    "RW-006": "交易金额与客户身份严重不符",
    "RW-007": "短期内频繁开销户",
    "RW-008": "非正常时段大额交易",
    "RW-009": "交易金额刻意规避报告标准",
    "RW-010": "关联方之间异常资金往来",
    "RW-011": "涉及高风险国家/地区的资金往来",
    "RW-012": "基金产品频繁申购赎回（清洗交易）",
    "RW-013": "政治公众人物（PEP）关联账户异常",
    "RW-014": "非本人账户代付投资款",
    "RW-015": "身份信息变更后立即大额交易",
    "RW-016": "老年客户异常大额资金转出",
    "RW-017": "新开户短期内大额交易",
    "RW-018": "多账户关联资金归集",
    "RW-019": "疑似涉赌/涉诈资金流转",
    "RW-020": "与离岸金融中心公司异常交易",
}

# ======================================================================
# 返回结构与入参结构（组B最小可测接口；组C按此聚合）
# ======================================================================


class RuleDataUnavailableError(RuntimeError):
    """规则数据获取失败（数据库/模型依赖不可用）。

    与"未命中（None）"和"数据不足（insufficient_data）"严格区分：
    本异常表示取数环节本身失败，应由组C规则引擎统一捕获并告警，不参与规则判定。
    """


class RuleHit(BaseModel):
    """单条规则的判定结果（组C聚合前的原始结果，不包含 severity/confidence/repeat）。"""

    rule_id: str
    rule_name: str
    status: Literal["hit", "insufficient_data"] = "hit"
    details: Dict[str, Any] = Field(default_factory=dict)
    related_transaction_ids: List[int] = Field(default_factory=list)
    primary_transaction_id: Optional[int] = None
    missing_fields: List[str] = Field(default_factory=list)


class RuleContext(BaseModel):
    """规则检查的外部数据注入（生产来源缺失时由调用方提供；缺省走模块内 _get_* 提供函数）。

    注入优先级：RuleContext 显式值 > 提供函数（数据库/画像） > 数据不足。
    任何字段都不得在规则函数内使用静默默认值。
    """

    ref_time: Optional[datetime] = None
    customer_name: Optional[str] = None                      # RW-014 投资账户名（备案 EB-B-10）
    age: Optional[int] = None                                # RW-016 年龄（备案 EB-B-03）
    declared_annual_income: Optional[Decimal] = None         # RW-006 申报年收入（备案 EB-B-04）
    pep_marked: Optional[bool] = None                        # RW-013 PEP标记（备案 EB-B-05）
    identity_changed_at: Optional[datetime] = None           # RW-015 关键身份信息变更时间（备案 EB-B-11）
    account_created_at: Optional[datetime] = None            # RW-017 开户时间
    same_id_card_account_events: Optional[List[dict]] = None  # RW-007 同证件账户开销户事件（备案 EB-B-06）
    is_professional_investor: Optional[bool] = None          # RW-020 专业投资机构标记


@dataclass(frozen=True)
class RuleMeta:
    """单条规则的元数据（AML_RULES 的元素结构）。"""

    rule_id: str                 # 严格 RW-001 ~ RW-020
    rule_name: str
    trigger_scope: str           # 'event'（实时/准实时）| 'daily'（日批）| 'weekly'（周批）
    risk_level: str              # 原文风险等级语义：高风险/中高风险/中风险/低风险
    weight_tier: float           # 强0.35 / 中0.20 / 弱0.10
    priority: int                # 1-5，数字越小优先级越高（规则原文第三章第四条）
    check_func: Callable[..., Optional[RuleHit]]  # 直接引用函数对象，禁止字符串
    thresholds: Dict[str, Any]   # 本规则阈值的集中清单（值为本模块常量，单点修改）
    source_tables: Tuple[str, ...]
    source_fields: Tuple[str, ...]
    rule_version: str = "1.0"
    enabled: bool = True


# ======================================================================
# 内部辅助函数
# ======================================================================


def _hit_result(rule_id: str, details: Optional[Dict[str, Any]] = None,
                related_ids: Optional[List[int]] = None,
                primary_id: Optional[int] = None) -> RuleHit:
    """构造"命中"结果。"""
    return RuleHit(
        rule_id=rule_id,
        rule_name=RULE_NAMES[rule_id],
        status="hit",
        details=details or {},
        related_transaction_ids=related_ids or [],
        primary_transaction_id=primary_id,
    )


def _insufficient_result(rule_id: str, missing_fields: List[str], reason: str = "") -> RuleHit:
    """构造"数据不足、无法判定"结果——与未命中严格区分，保证可追踪。"""
    return RuleHit(
        rule_id=rule_id,
        rule_name=RULE_NAMES[rule_id],
        status="insufficient_data",
        details={"reason": reason} if reason else {},
        missing_fields=missing_fields,
    )


def _natural_day_window(ref_time: datetime, days: int) -> Tuple[datetime, datetime]:
    """自然日窗口：以 ref_time 所在日为最后一天、向前共 days 个自然日，返回左闭右开 [start, end)。"""
    start_date = ref_time.date() - timedelta(days=days - 1)
    start = datetime.combine(start_date, time.min)
    end = datetime.combine(ref_time.date() + timedelta(days=1), time.min)
    return start, end


def _in_window(tx, start: datetime, end: datetime) -> bool:
    """交易是否落在 [start, end) 时间窗口内（transaction_time 为 None 的记录不参与判定）。"""
    t = getattr(tx, "transaction_time", None)
    return t is not None and start <= t < end


def _amount_or_none(tx) -> Optional[Decimal]:
    """统一金额类型：int/float/str/Decimal -> Decimal；None 返回 None（不参与聚合）。"""
    v = getattr(tx, "amount", None)
    return None if v is None else Decimal(str(v))


def _sum_amounts(txs: List[Any]) -> Decimal:
    """金额合计（跳过 amount 为 None 的异常记录）。"""
    total = Decimal("0")
    for t in txs:
        a = _amount_or_none(t)
        if a is not None:
            total += a
    return total


def _is_inflow(tx) -> bool:
    """交易方向约定（备案 EB-B-01）：入账交易 = payer_account_name 非空且 counterparty_account 为空。"""
    return bool(getattr(tx, "payer_account_name", None)) and not bool(getattr(tx, "counterparty_account", None))


def _is_outflow(tx) -> bool:
    """交易方向约定（备案 EB-B-01）：转出交易 = counterparty_account 非空且 payer_account_name 为空。"""
    return bool(getattr(tx, "counterparty_account", None)) and not bool(getattr(tx, "payer_account_name", None))


def _is_night_time(t: datetime, start_hour: int, end_hour: int) -> bool:
    """是否落在 [start_hour, end_hour) 小时段内（end_hour 小于 start_hour 表示跨午夜）。"""
    hour = t.hour
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def _event_time(event: Any, key: str) -> Optional[datetime]:
    """从 dict 或对象中读取事件时间字段（RW-007 开销户事件）。"""
    v = event.get(key) if isinstance(event, dict) else getattr(event, key, None)
    return v if isinstance(v, datetime) else None


# ======================================================================
# 数据提供函数（所有数据库访问的唯一出口；单元测试通过 mock 替换这些函数，不触碰真实数据库）
# ======================================================================


def _fetch_customer_transactions(customer_id: int, limit: int = QUERY_TX_LIMIT) -> List[Any]:
    """拉取客户最近 limit 笔交易流水（transaction_time 降序）。

    复用 TransactionModel.find_by_customer_id（其内部 SQL 全参数化）。
    惰性导入模型类：避免规则模块加载时触发 app.Base 包初始化（脚手架 Base/ 与 app.Base/
    双命名空间混用的导入问题由李清华另行处理，本模块不依赖模块加载期建连）。
    """
    try:
        from app.WealthButler.Models.transactionModel import TransactionModel
        return TransactionModel.find_by_customer_id(customer_id, limit=limit, offset=0)
    except Exception as e:  # 取数失败必须显式抛出，不得伪装成空列表（空列表=未命中）
        raise RuleDataUnavailableError(f"拉取客户 {customer_id} 交易流水失败: {e}") from e


def _get_user(customer_id: int) -> Optional[Any]:
    """复用 BaseUserExtModel.get_by_id（内部异常返回 None，无记录与取数失败统一为 None）。"""
    from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel
    return BaseUserExtModel.get_by_id(customer_id)


def _get_customer_age(customer_id: int) -> Optional[int]:
    """客户年龄（备案 EB-B-03：base_user 无年龄字段，仅尝试 extra_data.age 测试构造值；生产无来源返回 None）。"""
    user = _get_user(customer_id)
    if user is None:
        return None
    extra = getattr(user, "extra_data", None)
    if isinstance(extra, dict):
        age = extra.get("age")
        return int(age) if age is not None else None
    return None


def _get_account_created_at(customer_id: int) -> Optional[datetime]:
    """开户时间（base_user.created_at，真实字段）。"""
    user = _get_user(customer_id)
    return getattr(user, "created_at", None) if user is not None else None


def _get_identity_changed_at(customer_id: int) -> Optional[datetime]:
    """关键身份信息变更时间（备案 EB-B-11：base_user 无变更明细，用 updated_at 近似，
    无法区分"关键身份信息变更"与其他更新，口径待聂柏确认）。"""
    user = _get_user(customer_id)
    return getattr(user, "updated_at", None) if user is not None else None


def _get_customer_name(customer_id: int) -> Optional[str]:
    """投资账户姓名（备案 EB-B-10：base_user 无姓名字段，生产来源缺失，返回 None 交由调用方注入）。"""
    return None


def _get_declared_annual_income(customer_id: int) -> Optional[Decimal]:
    """申报年收入（备案 EB-B-04：无落点字段，生产来源缺失，返回 None 交由调用方注入）。"""
    return None


def _get_pep_marked(customer_id: int) -> Optional[bool]:
    """PEP/PEP关联人标记（备案 EB-B-05：无落点字段且不得伪造外部名单，返回 None 交由调用方注入）。"""
    return None


def _get_same_id_card_account_events(customer_id: int) -> Optional[List[dict]]:
    """同一证件关联账户的开销户事件（备案 EB-B-06：base_user 无证件号字段，无法按证件关联，返回 None）。"""
    return None


def _get_is_professional_investor(customer_id: int) -> Optional[bool]:
    """是否专业投资机构（fin_risk_assessment.is_professional_investor，真实字段；无评估记录返回 None）。"""
    try:
        from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel
        latest = RiskAssessmentModel.find_latest_by_customer_id(customer_id)
    except Exception as e:
        raise RuleDataUnavailableError(f"查询客户 {customer_id} 风评记录失败: {e}") from e
    if latest is None:
        return None
    return bool(getattr(latest, "is_professional_investor", False))


# ======================================================================
# 20 条规则检查函数（统一签名：check_rwXXX(customer_id, context=None) -> Optional[RuleHit]）
# ======================================================================


def check_rw001(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-001 大额现金交易：单日累计现金交易 >= 5万元（实时，弱信号，优先级3）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    txs = _fetch_customer_transactions(customer_id)
    start, end = _natural_day_window(ref, days=1)
    cash_txs = [t for t in txs
                if _in_window(t, start, end) and bool(getattr(t, "is_cash", False))
                and _amount_or_none(t) is not None]
    if not cash_txs:
        return None
    total = _sum_amounts(cash_txs)
    # 注：等值1万美元分支（RW001_DAILY_CASH_LIMIT_USD）因无汇率来源未启用（备案 EB-B-02）
    if total < RW001_DAILY_CASH_LIMIT:
        return None
    primary = max(cash_txs, key=lambda t: _amount_or_none(t))
    return _hit_result(
        "RW-001",
        details={"daily_cash_total": str(total), "cash_tx_count": len(cash_txs), "window_days": 1},
        related_ids=[t.id for t in cash_txs if t.id is not None],
        primary_id=primary.id,
    )


def check_rw002(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-002 频繁小额交易：7自然日内 >=20笔 且 累计 >=10万元，且每笔低于其大额报告线（日批，中信号，优先级4）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    txs = _fetch_customer_transactions(customer_id)
    start, end = _natural_day_window(ref, days=RW002_WINDOW_DAYS)
    window_txs = [t for t in txs if _in_window(t, start, end) and _amount_or_none(t) is not None]
    if len(window_txs) < RW002_MIN_TX_COUNT:
        return None
    # 补充条件：单笔低于大额报告标准（现金按5万、其余按转账20万），任何一笔超标即破坏"拆分规避"特征
    for t in window_txs:
        line = AML_REPORT_LINE_CASH if bool(getattr(t, "is_cash", False)) else AML_REPORT_LINE_TRANSFER
        if _amount_or_none(t) >= line:
            return None
    total = _sum_amounts(window_txs)
    if total < RW002_MIN_TOTAL_AMOUNT:
        return None
    primary = max(window_txs, key=lambda t: _amount_or_none(t))
    return _hit_result(
        "RW-002",
        details={"tx_count": len(window_txs), "total_amount": str(total),
                 "max_amount": str(_amount_or_none(primary)), "window_days": RW002_WINDOW_DAYS},
        related_ids=[t.id for t in window_txs if t.id is not None],
        primary_id=primary.id,
    )


def check_rw003(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-003 资金快进快出：入账后24小时内转出 >= 入账金额90% 且转出 >= 5万元（实时，中信号，优先级3）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    txs = _fetch_customer_transactions(customer_id)
    lookback_start, _ = _natural_day_window(ref, days=RW003_INFLOW_LOOKBACK_DAYS)
    inflows = [t for t in txs
               if _is_inflow(t) and _amount_or_none(t) is not None
               and t.transaction_time is not None and t.transaction_time >= lookback_start]
    outflows = [t for t in txs if _is_outflow(t) and _amount_or_none(t) is not None
                and t.transaction_time is not None]
    for inflow in inflows:
        t0 = inflow.transaction_time
        matched = [t for t in outflows if t0 < t.transaction_time <= t0 + timedelta(hours=RW003_WINDOW_HOURS)]
        if not matched:
            continue
        outflow_total = _sum_amounts(matched)
        ratio = outflow_total / _amount_or_none(inflow)
        if outflow_total >= RW003_MIN_OUTFLOW_AMOUNT and ratio >= RW003_MIN_OUTFLOW_RATIO:
            primary = max(matched, key=lambda t: _amount_or_none(t))
            return _hit_result(
                "RW-003",
                details={"inflow_amount": str(_amount_or_none(inflow)), "outflow_amount": str(outflow_total),
                         "ratio": str(round(ratio, 4)), "window_hours": RW003_WINDOW_HOURS},
                related_ids=[t.id for t in ([inflow] + matched) if t.id is not None],
                primary_id=primary.id,
            )
    return None


def check_rw004(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-004 分散转入集中转出：5自然日内 >=5个来源账户转入 且 转出 >=20万元 且 转出集中度 >=80%（日批，强信号，优先级2）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    txs = _fetch_customer_transactions(customer_id)
    start, end = _natural_day_window(ref, days=RW004_WINDOW_DAYS)
    inflows = [t for t in txs if _is_inflow(t) and _in_window(t, start, end)]
    outflows = [t for t in txs if _is_outflow(t) and _in_window(t, start, end)]
    distinct_sources = len({t.payer_account_name for t in inflows if t.payer_account_name})
    outflow_total = _sum_amounts(outflows)
    if distinct_sources < RW004_MIN_SOURCE_ACCOUNTS or outflow_total < RW004_MIN_OUTFLOW_TOTAL:
        return None
    by_counterparty: Dict[str, Decimal] = {}
    for t in outflows:
        cp = t.counterparty_account
        if cp:
            by_counterparty[cp] = by_counterparty.get(cp, Decimal("0")) + _amount_or_none(t)
    if not by_counterparty or outflow_total <= 0:
        return None
    top_cp, top_sum = max(by_counterparty.items(), key=lambda kv: kv[1])
    concentration = top_sum / outflow_total
    if concentration < RW004_CONCENTRATION_RATIO:
        return None
    primary = max(outflows, key=lambda t: _amount_or_none(t))
    return _hit_result(
        "RW-004",
        details={"distinct_source_accounts": distinct_sources, "outflow_total": str(outflow_total),
                 "top_counterparty": top_cp, "concentration_ratio": str(round(concentration, 4)),
                 "window_days": RW004_WINDOW_DAYS},
        related_ids=[t.id for t in txs if t.id is not None and _in_window(t, start, end)],
        primary_id=primary.id,
    )


def check_rw005(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-005 集中转入分散转出：5自然日内单笔转入 >=10万元，随后3自然日内向 >=5个账户分散转出，单笔转出 < 20万元（日批，强信号，优先级2）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    txs = _fetch_customer_transactions(customer_id)
    start, _ = _natural_day_window(ref, days=RW005_WINDOW_DAYS)
    inflows = [t for t in txs
               if _is_inflow(t) and t.transaction_time is not None and t.transaction_time >= start
               and (_amount_or_none(t) or Decimal("0")) >= RW005_MIN_INFLOW_SINGLE]
    outflows = [t for t in txs if _is_outflow(t) and t.transaction_time is not None]
    for inflow in inflows:
        t0 = inflow.transaction_time
        follow_end = datetime.combine(t0.date() + timedelta(days=RW005_FOLLOW_DAYS + 1), time.min)
        matched = [t for t in outflows if t0 < t.transaction_time < follow_end]
        if len({t.counterparty_account for t in matched if t.counterparty_account}) < RW005_MIN_DISPERSED_ACCOUNTS:
            continue
        if any(_amount_or_none(t) is not None and _amount_or_none(t) >= AML_REPORT_LINE_TRANSFER for t in matched):
            continue
        primary = max(matched, key=lambda t: _amount_or_none(t))
        return _hit_result(
            "RW-005",
            details={"inflow_amount": str(_amount_or_none(inflow)),
                     "distinct_outflow_accounts": len({t.counterparty_account for t in matched if t.counterparty_account}),
                     "follow_window_days": RW005_FOLLOW_DAYS},
            related_ids=[t.id for t in ([inflow] + matched) if t.id is not None],
            primary_id=primary.id,
        )
    return None


def check_rw006(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-006 交易金额与客户身份严重不符：单日交易 >= 申报年收入×3 且 >= 10万元（日批，中信号，优先级4）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    income = ctx.declared_annual_income if ctx.declared_annual_income is not None else _get_declared_annual_income(customer_id)
    if income is None:
        return _insufficient_result("RW-006", ["declared_annual_income"],
                                    "申报年收入无生产来源（备案 EB-B-04），请通过 RuleContext 注入")
    txs = _fetch_customer_transactions(customer_id)
    start, end = _natural_day_window(ref, days=1)
    day_txs = [t for t in txs if _in_window(t, start, end) and _amount_or_none(t) is not None]
    total = _sum_amounts(day_txs)
    if total < RW006_MIN_DAILY_AMOUNT or total < income * RW006_INCOME_MULTIPLIER:
        return None
    primary = max(day_txs, key=lambda t: _amount_or_none(t))
    return _hit_result(
        "RW-006",
        details={"daily_total": str(total), "annual_income": str(income),
                 "threshold": str(income * RW006_INCOME_MULTIPLIER)},
        related_ids=[t.id for t in day_txs if t.id is not None],
        primary_id=primary.id,
    )


def check_rw007(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-007 短期内频繁开销户：同一证件30自然日内开户 >=3次 或 开户后30天内销户 >=2次（周批，弱信号，优先级5）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    events = (ctx.same_id_card_account_events
              if ctx.same_id_card_account_events is not None
              else _get_same_id_card_account_events(customer_id))
    if events is None:
        return _insufficient_result("RW-007", ["same_id_card_account_events"],
                                    "证件号无生产字段（备案 EB-B-06），请通过 RuleContext 注入")
    if not events:
        return None
    open_start, _ = _natural_day_window(ref, days=RW007_OPEN_WINDOW_DAYS)
    opens = 0
    closes_within = 0
    for event in events:
        created = _event_time(event, "created_at")
        deleted = _event_time(event, "deleted_at")
        if created is not None and open_start <= created <= ref:
            opens += 1
        if created is not None and deleted is not None and deleted >= created \
                and deleted - created <= timedelta(days=RW007_CLOSE_AFTER_OPEN_DAYS):
            closes_within += 1
    if opens < RW007_MIN_OPENS and closes_within < RW007_MIN_CLOSES_WITHIN_DAYS:
        return None
    return _hit_result(
        "RW-007",
        details={"open_count": opens, "close_within_30d_count": closes_within},
    )


def check_rw008(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-008 非正常时段大额交易：0:00-6:00 单笔 >=10万元 或 单日累计 >=20万元，且90自然日同时段无先例（实时，弱信号，优先级5）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    txs = _fetch_customer_transactions(customer_id)
    start, end = _natural_day_window(ref, days=1)
    night_today = [t for t in txs
                   if _in_window(t, start, end) and _amount_or_none(t) is not None
                   and _is_night_time(t.transaction_time, RW008_NIGHT_START_HOUR, RW008_NIGHT_END_HOUR)]
    if not night_today:
        return None
    max_amount = max(_amount_or_none(t) for t in night_today)
    total = _sum_amounts(night_today)
    if max_amount < RW008_NIGHT_SINGLE_LIMIT and total < RW008_NIGHT_DAILY_LIMIT:
        return None
    # 先例检查（口径备案 EB-B-14）：过去90个自然日（不含今天）同时段存在单笔 >=10万元的交易即视为有先例
    prior_start = datetime.combine(ref.date() - timedelta(days=RW008_BASELINE_DAYS), time.min)
    prior_end = datetime.combine(ref.date(), time.min)
    has_precedent = any(
        _is_night_time(t.transaction_time, RW008_NIGHT_START_HOUR, RW008_NIGHT_END_HOUR)
        and (_amount_or_none(t) or Decimal("0")) >= RW008_PRECEDENT_AMOUNT
        for t in txs if _in_window(t, prior_start, prior_end)
    )
    if has_precedent:
        return None
    primary = max(night_today, key=lambda t: _amount_or_none(t))
    return _hit_result(
        "RW-008",
        details={"night_single_max": str(max_amount), "night_daily_total": str(total),
                 "baseline_days": RW008_BASELINE_DAYS},
        related_ids=[t.id for t in night_today if t.id is not None],
        primary_id=primary.id,
    )


def check_rw009(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-009 交易金额刻意规避报告标准：30自然日内 >=5笔"报告线整数减1"金额（日批，中信号，优先级4）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    txs = _fetch_customer_transactions(customer_id)
    start, end = _natural_day_window(ref, days=RW009_WINDOW_DAYS)
    evasion = [t for t in txs
               if _in_window(t, start, end) and _amount_or_none(t) in RW009_EVASION_AMOUNTS]
    if len(evasion) < RW009_MIN_EVASION_COUNT:
        return None
    return _hit_result(
        "RW-009",
        details={"evasion_count": len(evasion),
                 "amounts": [str(_amount_or_none(t)) for t in evasion],
                 "window_days": RW009_WINDOW_DAYS},
        related_ids=[t.id for t in evasion if t.id is not None],
    )


def check_rw010(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-010 关联方之间异常资金往来：同一对手方7自然日内双向交易 >=3次 且 净额 < 总额20%（日批，中信号，优先级4）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    txs = _fetch_customer_transactions(customer_id)
    start, end = _natural_day_window(ref, days=RW010_WINDOW_DAYS)
    inflows = [t for t in txs if _is_inflow(t) and _in_window(t, start, end)]
    outflows = [t for t in txs if _is_outflow(t) and _in_window(t, start, end)]
    in_map: Dict[str, List[Any]] = {}
    out_map: Dict[str, List[Any]] = {}
    for t in inflows:
        in_map.setdefault(t.payer_account_name, []).append(t)
    for t in outflows:
        out_map.setdefault(t.counterparty_account, []).append(t)
    for cp in sorted(set(in_map) & set(out_map)):
        count = len(in_map[cp]) + len(out_map[cp])
        if count < RW010_MIN_BIDIRECTIONAL_COUNT:
            continue
        in_sum = _sum_amounts(in_map[cp])
        out_sum = _sum_amounts(out_map[cp])
        total = in_sum + out_sum
        if total <= 0:
            continue
        net = abs(in_sum - out_sum)
        if net < total * RW010_MAX_NET_RATIO:
            related = in_map[cp] + out_map[cp]
            return _hit_result(
                "RW-010",
                details={"counterparty": cp, "bidirectional_count": count,
                         "net_amount": str(net), "total_amount": str(total),
                         "net_ratio": str(round(net / total, 4))},
                related_ids=[t.id for t in related if t.id is not None],
            )
    return None


def check_rw011(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-011 涉及高风险国家/地区的资金往来：对手方地区在FATF/OFAC名单 且 金额 >=1万元（实时，强信号，优先级1）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    txs = _fetch_customer_transactions(customer_id)
    start, end = _natural_day_window(ref, days=1)
    day_txs = [t for t in txs if _in_window(t, start, end)]
    if not day_txs:
        return None
    region_txs = [t for t in day_txs if getattr(t, "counterparty_region", None)]
    if not region_txs:
        return _insufficient_result("RW-011", ["counterparty_region"],
                                    "当日流水对手方地区全部为空，无法判定")
    hits = [t for t in region_txs
            if t.counterparty_region in RW011_HIGH_RISK_REGIONS
            and (_amount_or_none(t) or Decimal("0")) >= RW011_MIN_AMOUNT]
    if not hits:
        return None
    primary = max(hits, key=lambda t: _amount_or_none(t))
    return _hit_result(
        "RW-011",
        details={"region": primary.counterparty_region, "amount": str(_amount_or_none(primary))},
        related_ids=[t.id for t in hits if t.id is not None],
        primary_id=primary.id,
    )


def check_rw012(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-012 基金产品频繁申购赎回：同一产品30自然日内申购 >=3 且 赎回 >=3，且存在持有期 <7天的短持（日批，弱信号，优先级5）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    txs = _fetch_customer_transactions(customer_id)
    start, end = _natural_day_window(ref, days=RW012_WINDOW_DAYS)
    by_product: Dict[int, Dict[str, List[Any]]] = {}
    for t in txs:
        if not _in_window(t, start, end) or t.product_id is None:
            continue
        bucket = by_product.setdefault(t.product_id, {"申购": [], "赎回": []})
        if t.transaction_type in bucket:
            bucket[t.transaction_type].append(t)
    for product_id in sorted(by_product):
        bucket = by_product[product_id]
        purchases = sorted(bucket["申购"], key=lambda t: t.transaction_time)
        redemptions = sorted(bucket["赎回"], key=lambda t: t.transaction_time)
        if len(purchases) < RW012_MIN_PURCHASES or len(redemptions) < RW012_MIN_REDEMPTIONS:
            continue
        # 持有期近似（备案 EB-B-09）：赎回时间 - 该产品最近一次在先申购时间 < 7个自然日
        short_count = 0
        for r in redemptions:
            prior = [p for p in purchases if p.transaction_time < r.transaction_time]
            if prior and r.transaction_time - prior[-1].transaction_time < timedelta(days=RW012_MAX_HOLDING_DAYS):
                short_count += 1
        if short_count < 1:
            continue
        related = purchases + redemptions
        return _hit_result(
            "RW-012",
            details={"product_id": product_id, "purchase_count": len(purchases),
                     "redemption_count": len(redemptions), "short_holding_count": short_count},
            related_ids=[t.id for t in related if t.id is not None],
        )
    return None


def check_rw013(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-013 PEP关联账户异常：PEP标记 且（单笔>=20万元 或 新增境外对手方 或 3月交易模式变化>50%）任一（日批，强信号，优先级1）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    pep = ctx.pep_marked if ctx.pep_marked is not None else _get_pep_marked(customer_id)
    if pep is None:
        return _insufficient_result("RW-013", ["pep_marked"],
                                    "PEP标记无生产来源（备案 EB-B-05），请通过 RuleContext 注入")
    if not pep:
        return None
    txs = _fetch_customer_transactions(customer_id)
    day_start, day_end = _natural_day_window(ref, days=1)
    day_txs = [t for t in txs if _in_window(t, day_start, day_end) and _amount_or_none(t) is not None]

    # 情形一：单笔交易 >= 20万元
    if any(_amount_or_none(t) >= RW013_MIN_SINGLE_AMOUNT for t in day_txs):
        primary = max(day_txs, key=lambda t: _amount_or_none(t))
        return _hit_result("RW-013",
                           details={"reason": "single_large", "amount": str(_amount_or_none(primary))},
                           related_ids=[t.id for t in day_txs if t.id is not None],
                           primary_id=primary.id)

    # 情形二：新增境外交易对手方（90自然日内未出现过的非境内地区）
    prior_start = datetime.combine(ref.date() - timedelta(days=RW013_FOREIGN_LOOKBACK_DAYS), time.min)
    prior_end = datetime.combine(ref.date(), time.min)
    prior_regions = {t.counterparty_region for t in txs
                     if _in_window(t, prior_start, prior_end) and getattr(t, "counterparty_region", None)}
    for t in day_txs:
        region = getattr(t, "counterparty_region", None)
        if region and region not in RW013_DOMESTIC_REGIONS and region not in prior_regions:
            return _hit_result("RW-013",
                               details={"reason": "new_foreign_counterparty", "region": region},
                               related_ids=[t.id for t in day_txs if t.id is not None],
                               primary_id=t.id)

    # 情形三：近30日交易额较前3个月月均变化 > 50%
    cur_start, cur_end = _natural_day_window(ref, days=30)
    cur_total = _sum_amounts([t for t in txs if _in_window(t, cur_start, cur_end)])
    prior3_start = datetime.combine(ref.date() - timedelta(days=120), time.min)
    prior3_end = datetime.combine(ref.date() - timedelta(days=30), time.min)
    prior_total = _sum_amounts([t for t in txs if _in_window(t, prior3_start, prior3_end)])
    prior_month_avg = prior_total / Decimal(RW013_PRIOR_MONTHS)
    if prior_month_avg > 0:
        change = (cur_total - prior_month_avg) / prior_month_avg
        if change > RW013_PATTERN_CHANGE_RATIO:
            return _hit_result("RW-013",
                               details={"reason": "pattern_change", "cur_30d_total": str(cur_total),
                                        "prior_month_avg": str(prior_month_avg), "change_ratio": str(round(change, 4))},
                               related_ids=[t.id for t in txs if t.id is not None and _in_window(t, cur_start, cur_end)])
    return None


def check_rw014(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-014 非本人账户代付投资款：申购资金来源账户名 != 投资账户名 且 代付 >=5万元（实时，中信号，优先级3）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    name = ctx.customer_name if ctx.customer_name is not None else _get_customer_name(customer_id)
    if name is None:
        return _insufficient_result("RW-014", ["customer_name"],
                                    "投资账户名无生产字段（备案 EB-B-10），请通过 RuleContext 注入")
    txs = _fetch_customer_transactions(customer_id)
    start, end = _natural_day_window(ref, days=1)
    purchase_txs = [t for t in txs
                    if _in_window(t, start, end) and getattr(t, "transaction_type", None) == "申购"]
    if not purchase_txs:
        return None
    if not any(getattr(t, "payer_account_name", None) for t in purchase_txs):
        return _insufficient_result("RW-014", ["payer_account_name"], "当日申购流水付款人姓名全部为空")
    hits = [t for t in purchase_txs
            if t.payer_account_name and t.payer_account_name != name
            and (_amount_or_none(t) or Decimal("0")) >= RW014_MIN_AMOUNT]
    if not hits:
        return None
    primary = max(hits, key=lambda t: _amount_or_none(t))
    return _hit_result(
        "RW-014",
        details={"payer_account_name": primary.payer_account_name, "amount": str(_amount_or_none(primary))},
        related_ids=[t.id for t in hits if t.id is not None],
        primary_id=primary.id,
    )


def check_rw015(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-015 身份信息变更后立即大额交易：关键身份信息变更后72小时内出现单笔 >=10万元交易（实时，弱信号，优先级5）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    changed_at = ctx.identity_changed_at if ctx.identity_changed_at is not None else _get_identity_changed_at(customer_id)
    if changed_at is None:
        return _insufficient_result("RW-015", ["identity_changed_at"],
                                    "身份信息变更时间无生产来源（备案 EB-B-11），请通过 RuleContext 注入")
    if changed_at > ref:
        return None
    window_end = changed_at + timedelta(hours=RW015_CHANGE_WINDOW_HOURS)
    txs = _fetch_customer_transactions(customer_id)
    hits = [t for t in txs
            if t.transaction_time is not None and changed_at <= t.transaction_time <= window_end
            and (_amount_or_none(t) or Decimal("0")) >= RW015_MIN_AMOUNT]
    if not hits:
        return None
    primary = max(hits, key=lambda t: _amount_or_none(t))
    return _hit_result(
        "RW-015",
        details={"changed_at": changed_at.isoformat(), "amount": str(_amount_or_none(primary)),
                 "window_hours": RW015_CHANGE_WINDOW_HOURS},
        related_ids=[t.id for t in hits if t.id is not None],
        primary_id=primary.id,
    )


def check_rw016(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-016 老年客户异常大额资金转出：年龄 >=65 且（单笔转出 >=10万元 或 7日累计转出 >=20万元）
    且该笔交易超过过去12个月月均交易的3倍（实时，中信号，优先级5）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    age = ctx.age if ctx.age is not None else _get_customer_age(customer_id)
    if age is None:
        return _insufficient_result("RW-016", ["age"],
                                    "年龄无生产来源（备案 EB-B-03），请通过 RuleContext 注入")
    if age < RW016_MIN_AGE:
        return None
    txs = _fetch_customer_transactions(customer_id)
    start, end = _natural_day_window(ref, days=RW016_WINDOW_DAYS)
    outflows_7d = [t for t in txs if _is_outflow(t) and _in_window(t, start, end)
                   and _amount_or_none(t) is not None]
    if not outflows_7d:
        return None
    primary = max(outflows_7d, key=lambda t: _amount_or_none(t))
    primary_amount = _amount_or_none(primary)
    total_7d = _sum_amounts(outflows_7d)
    if primary_amount < RW016_MIN_SINGLE_OUTFLOW and total_7d < RW016_7D_OUTFLOW_TOTAL:
        return None
    # 12个月月均 = 最近365个自然日转出总额 / 12（月均为0时按字面口径：任何正数转出即"超过"，备案 EB-B-15）
    avg_start, avg_end = _natural_day_window(ref, days=RW016_AVG_WINDOW_DAYS)
    total_365 = _sum_amounts([t for t in txs
                              if _is_outflow(t) and _in_window(t, avg_start, avg_end)])
    monthly_avg = total_365 / Decimal(RW016_MONTHS_PER_YEAR)
    if primary_amount <= monthly_avg * RW016_MONTHLY_AVG_MULTIPLIER:
        return None
    return _hit_result(
        "RW-016",
        details={"age": age, "max_outflow": str(primary_amount), "outflow_7d_total": str(total_7d),
                 "monthly_avg": str(round(monthly_avg, 2))},
        related_ids=[t.id for t in outflows_7d if t.id is not None],
        primary_id=primary.id,
    )


def check_rw017(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-017 新开户短期内大额交易：开户30个自然日内单笔 >=20万元 或 累计 >=50万元（实时，中信号，优先级4）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    created_at = ctx.account_created_at if ctx.account_created_at is not None else _get_account_created_at(customer_id)
    if created_at is None:
        return _insufficient_result("RW-017", ["account_created_at"], "开户时间无生产来源，请通过 RuleContext 注入")
    days_since_open = (ref - created_at).total_seconds() / 86400
    if days_since_open < 0 or days_since_open > RW017_OPEN_WINDOW_DAYS:
        return None
    txs = _fetch_customer_transactions(customer_id)
    since_open = [t for t in txs
                  if t.transaction_time is not None and t.transaction_time >= created_at
                  and _amount_or_none(t) is not None]
    if not since_open:
        return None
    max_amount = max(_amount_or_none(t) for t in since_open)
    total = _sum_amounts(since_open)
    if max_amount < RW017_MIN_SINGLE_AMOUNT and total < RW017_MIN_TOTAL_AMOUNT:
        return None
    primary = max(since_open, key=lambda t: _amount_or_none(t))
    return _hit_result(
        "RW-017",
        details={"days_since_open": round(days_since_open, 2), "max_amount": str(max_amount),
                 "total_amount": str(total)},
        related_ids=[t.id for t in since_open if t.id is not None],
        primary_id=primary.id,
    )


def check_rw018(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-018 多账户关联资金归集：同一设备指纹关联 >=3个账户，7自然日内向本客户账户归集 >=30万元（周批，强信号，优先级1）。

    SQL 兜底口径（研判落地方案§2.4）：对转入本客户、且发起设备指纹相同的流水按设备指纹分组，
    组内不同来源账户（payer_account_name）>=3 且组合计 >=30万元即命中；Neo4j RELATION_TO 增强留给组F。
    """
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    txs = _fetch_customer_transactions(customer_id)
    start, end = _natural_day_window(ref, days=RW018_WINDOW_DAYS)
    inflows = [t for t in txs if _is_inflow(t) and _in_window(t, start, end)]
    if not inflows:
        return None
    with_device = [t for t in inflows if getattr(t, "device_fingerprint", None)]
    if not with_device:
        return _insufficient_result("RW-018", ["device_fingerprint"],
                                    "转入流水全部缺少设备指纹，无法建立账户关联")
    groups: Dict[str, List[Any]] = {}
    for t in with_device:
        groups.setdefault(t.device_fingerprint, []).append(t)
    for device in sorted(groups):
        members = groups[device]
        distinct_sources = len({t.payer_account_name for t in members if t.payer_account_name})
        aggregated = _sum_amounts(members)
        if distinct_sources >= RW018_MIN_LINKED_ACCOUNTS \
                and aggregated >= RW018_MIN_AGGREGATED_AMOUNT:
            primary = max(members, key=lambda t: _amount_or_none(t))
            return _hit_result(
                "RW-018",
                details={"device_fingerprint": device, "distinct_source_accounts": distinct_sources,
                         "aggregated_amount": str(aggregated), "window_days": RW018_WINDOW_DAYS},
                related_ids=[t.id for t in members if t.id is not None],
                primary_id=primary.id,
            )
    return None


def check_rw019(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-019 疑似涉赌/涉诈资金流转：三特征同时满足——入金单笔<5千且日累计<2万且集中于20:00-02:00；
    出金存在单笔 >=5万元或整数金额（日批，强信号，优先级1）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    txs = _fetch_customer_transactions(customer_id)
    start, end = _natural_day_window(ref, days=1)
    inflows = [t for t in txs if _is_inflow(t) and _in_window(t, start, end)
               and _amount_or_none(t) is not None]
    outflows = [t for t in txs if _is_outflow(t) and _in_window(t, start, end)
                and _amount_or_none(t) is not None]
    if not inflows or not outflows:
        return None
    feature1 = (
        all(_amount_or_none(t) < RW019_MAX_INFLOW_SINGLE for t in inflows)
        and _sum_amounts(inflows) < RW019_MAX_INFLOW_DAILY
        and all(_is_night_time(t.transaction_time, RW019_NIGHT_START_HOUR, RW019_NIGHT_END_HOUR)
                for t in inflows)
    )
    feature2 = any(
        _amount_or_none(t) >= RW019_MIN_OUTFLOW_SINGLE or (_amount_or_none(t) % 1 == 0)
        for t in outflows
    )
    if not (feature1 and feature2):
        return None
    primary = max(outflows, key=lambda t: _amount_or_none(t))
    return _hit_result(
        "RW-019",
        details={"inflow_count": len(inflows), "inflow_daily_total": str(_sum_amounts(inflows)),
                 "max_outflow": str(_amount_or_none(primary))},
        related_ids=[t.id for t in (inflows + outflows) if t.id is not None],
        primary_id=primary.id,
    )


def check_rw020(customer_id: int, context: Optional[RuleContext] = None) -> Optional[RuleHit]:
    """RW-020 与离岸金融中心公司异常交易：对手方地区为离岸金融中心 且 金额 >=10万元 且 客户非专业投资机构（日批，中信号，优先级4）。"""
    ctx = context or RuleContext()
    ref = ctx.ref_time or datetime.now()
    is_prof = (ctx.is_professional_investor
               if ctx.is_professional_investor is not None
               else _get_is_professional_investor(customer_id))
    if is_prof is None:
        return _insufficient_result("RW-020", ["is_professional_investor"],
                                    "客户无风评记录，专业投资机构标记不可得")
    if is_prof:
        return None
    txs = _fetch_customer_transactions(customer_id)
    start, end = _natural_day_window(ref, days=1)
    day_txs = [t for t in txs if _in_window(t, start, end)]
    if not day_txs:
        return None
    region_txs = [t for t in day_txs if getattr(t, "counterparty_region", None)]
    if not region_txs:
        return _insufficient_result("RW-020", ["counterparty_region"],
                                    "当日流水对手方地区全部为空，无法判定")
    hits = [t for t in region_txs
            if t.counterparty_region in RW020_OFFSHORE_REGIONS
            and (_amount_or_none(t) or Decimal("0")) >= RW020_MIN_AMOUNT]
    if not hits:
        return None
    primary = max(hits, key=lambda t: _amount_or_none(t))
    return _hit_result(
        "RW-020",
        details={"region": primary.counterparty_region, "amount": str(_amount_or_none(primary))},
        related_ids=[t.id for t in hits if t.id is not None],
        primary_id=primary.id,
    )


# ======================================================================
# 规则集合（组C按 rule_scope 筛选；AML_RULES 为唯一事实来源，RULE_BY_ID 为兼容别名）
# ======================================================================

REALTIME_RULE_IDS: Tuple[str, ...] = (
    "RW-001", "RW-003", "RW-008", "RW-011", "RW-014", "RW-015", "RW-016", "RW-017",
)
DAILY_RULE_IDS: Tuple[str, ...] = (
    "RW-002", "RW-004", "RW-005", "RW-006", "RW-009", "RW-010", "RW-012", "RW-013", "RW-019", "RW-020",
)
WEEKLY_RULE_IDS: Tuple[str, ...] = (
    "RW-007", "RW-018",
)

AML_RULES: Dict[str, RuleMeta] = {
    "RW-001": RuleMeta(
        rule_id="RW-001", rule_name=RULE_NAMES["RW-001"], trigger_scope="event",
        risk_level="中风险", weight_tier=WEIGHT_WEAK, priority=3, check_func=check_rw001,
        thresholds={"daily_cash_limit": RW001_DAILY_CASH_LIMIT,
                    "daily_cash_limit_usd": RW001_DAILY_CASH_LIMIT_USD},
        source_tables=("fin_transaction",),
        source_fields=("is_cash", "amount", "transaction_time"),
    ),
    "RW-002": RuleMeta(
        rule_id="RW-002", rule_name=RULE_NAMES["RW-002"], trigger_scope="daily",
        risk_level="中高风险", weight_tier=WEIGHT_MEDIUM, priority=4, check_func=check_rw002,
        thresholds={"window_days": RW002_WINDOW_DAYS, "min_tx_count": RW002_MIN_TX_COUNT,
                    "min_total_amount": RW002_MIN_TOTAL_AMOUNT},
        source_tables=("fin_transaction",),
        source_fields=("amount", "is_cash", "transaction_time"),
    ),
    "RW-003": RuleMeta(
        rule_id="RW-003", rule_name=RULE_NAMES["RW-003"], trigger_scope="event",
        risk_level="中高风险", weight_tier=WEIGHT_MEDIUM, priority=3, check_func=check_rw003,
        thresholds={"window_hours": RW003_WINDOW_HOURS, "min_outflow_ratio": RW003_MIN_OUTFLOW_RATIO,
                    "min_outflow_amount": RW003_MIN_OUTFLOW_AMOUNT},
        source_tables=("fin_transaction",),
        source_fields=("amount", "transaction_time", "payer_account_name", "counterparty_account"),
    ),
    "RW-004": RuleMeta(
        rule_id="RW-004", rule_name=RULE_NAMES["RW-004"], trigger_scope="daily",
        risk_level="高风险", weight_tier=WEIGHT_STRONG, priority=2, check_func=check_rw004,
        thresholds={"window_days": RW004_WINDOW_DAYS, "min_source_accounts": RW004_MIN_SOURCE_ACCOUNTS,
                    "min_outflow_total": RW004_MIN_OUTFLOW_TOTAL,
                    "concentration_ratio": RW004_CONCENTRATION_RATIO},
        source_tables=("fin_transaction",),
        source_fields=("counterparty_account", "payer_account_name", "amount", "transaction_time"),
    ),
    "RW-005": RuleMeta(
        rule_id="RW-005", rule_name=RULE_NAMES["RW-005"], trigger_scope="daily",
        risk_level="高风险", weight_tier=WEIGHT_STRONG, priority=2, check_func=check_rw005,
        thresholds={"window_days": RW005_WINDOW_DAYS, "min_inflow_single": RW005_MIN_INFLOW_SINGLE,
                    "follow_days": RW005_FOLLOW_DAYS, "min_dispersed_accounts": RW005_MIN_DISPERSED_ACCOUNTS},
        source_tables=("fin_transaction",),
        source_fields=("counterparty_account", "payer_account_name", "amount", "transaction_time"),
    ),
    "RW-006": RuleMeta(
        rule_id="RW-006", rule_name=RULE_NAMES["RW-006"], trigger_scope="daily",
        risk_level="中高风险", weight_tier=WEIGHT_MEDIUM, priority=4, check_func=check_rw006,
        thresholds={"income_multiplier": RW006_INCOME_MULTIPLIER,
                    "min_daily_amount": RW006_MIN_DAILY_AMOUNT},
        source_tables=("fin_transaction",),
        source_fields=("amount", "transaction_time"),
    ),
    "RW-007": RuleMeta(
        rule_id="RW-007", rule_name=RULE_NAMES["RW-007"], trigger_scope="weekly",
        risk_level="中风险", weight_tier=WEIGHT_WEAK, priority=5, check_func=check_rw007,
        thresholds={"open_window_days": RW007_OPEN_WINDOW_DAYS, "min_opens": RW007_MIN_OPENS,
                    "min_closes_within_days": RW007_MIN_CLOSES_WITHIN_DAYS},
        source_tables=("base_user",),
        source_fields=("created_at", "deleted_at"),
    ),
    "RW-008": RuleMeta(
        rule_id="RW-008", rule_name=RULE_NAMES["RW-008"], trigger_scope="event",
        risk_level="低风险", weight_tier=WEIGHT_WEAK, priority=5, check_func=check_rw008,
        thresholds={"night_start_hour": RW008_NIGHT_START_HOUR, "night_end_hour": RW008_NIGHT_END_HOUR,
                    "night_single_limit": RW008_NIGHT_SINGLE_LIMIT,
                    "night_daily_limit": RW008_NIGHT_DAILY_LIMIT, "baseline_days": RW008_BASELINE_DAYS},
        source_tables=("fin_transaction",),
        source_fields=("amount", "transaction_time"),
    ),
    "RW-009": RuleMeta(
        rule_id="RW-009", rule_name=RULE_NAMES["RW-009"], trigger_scope="daily",
        risk_level="中高风险", weight_tier=WEIGHT_MEDIUM, priority=4, check_func=check_rw009,
        thresholds={"window_days": RW009_WINDOW_DAYS, "min_evasion_count": RW009_MIN_EVASION_COUNT,
                    "evasion_amounts": RW009_EVASION_AMOUNTS},
        source_tables=("fin_transaction",),
        source_fields=("amount", "transaction_time"),
    ),
    "RW-010": RuleMeta(
        rule_id="RW-010", rule_name=RULE_NAMES["RW-010"], trigger_scope="daily",
        risk_level="中高风险", weight_tier=WEIGHT_MEDIUM, priority=4, check_func=check_rw010,
        thresholds={"window_days": RW010_WINDOW_DAYS, "min_bidirectional_count": RW010_MIN_BIDIRECTIONAL_COUNT,
                    "max_net_ratio": RW010_MAX_NET_RATIO},
        source_tables=("fin_transaction",),
        source_fields=("counterparty_account", "payer_account_name", "amount", "transaction_time"),
    ),
    "RW-011": RuleMeta(
        rule_id="RW-011", rule_name=RULE_NAMES["RW-011"], trigger_scope="event",
        risk_level="高风险", weight_tier=WEIGHT_STRONG, priority=1, check_func=check_rw011,
        thresholds={"min_amount": RW011_MIN_AMOUNT, "high_risk_regions": RW011_HIGH_RISK_REGIONS},
        source_tables=("fin_transaction",),
        source_fields=("counterparty_region", "amount"),
    ),
    "RW-012": RuleMeta(
        rule_id="RW-012", rule_name=RULE_NAMES["RW-012"], trigger_scope="daily",
        risk_level="中风险", weight_tier=WEIGHT_WEAK, priority=5, check_func=check_rw012,
        thresholds={"window_days": RW012_WINDOW_DAYS, "min_purchases": RW012_MIN_PURCHASES,
                    "min_redemptions": RW012_MIN_REDEMPTIONS, "max_holding_days": RW012_MAX_HOLDING_DAYS},
        source_tables=("fin_transaction", "fin_holdings"),
        source_fields=("transaction_type", "product_id", "transaction_time"),
    ),
    "RW-013": RuleMeta(
        rule_id="RW-013", rule_name=RULE_NAMES["RW-013"], trigger_scope="daily",
        risk_level="高风险", weight_tier=WEIGHT_STRONG, priority=1, check_func=check_rw013,
        thresholds={"min_single_amount": RW013_MIN_SINGLE_AMOUNT,
                    "foreign_lookback_days": RW013_FOREIGN_LOOKBACK_DAYS,
                    "pattern_change_ratio": RW013_PATTERN_CHANGE_RATIO},
        source_tables=("fin_transaction",),
        source_fields=("counterparty_region", "amount", "transaction_time"),
    ),
    "RW-014": RuleMeta(
        rule_id="RW-014", rule_name=RULE_NAMES["RW-014"], trigger_scope="event",
        risk_level="中高风险", weight_tier=WEIGHT_MEDIUM, priority=3, check_func=check_rw014,
        thresholds={"min_amount": RW014_MIN_AMOUNT},
        source_tables=("fin_transaction",),
        source_fields=("payer_account_name", "amount", "transaction_type"),
    ),
    "RW-015": RuleMeta(
        rule_id="RW-015", rule_name=RULE_NAMES["RW-015"], trigger_scope="event",
        risk_level="中风险", weight_tier=WEIGHT_WEAK, priority=5, check_func=check_rw015,
        thresholds={"change_window_hours": RW015_CHANGE_WINDOW_HOURS, "min_amount": RW015_MIN_AMOUNT},
        source_tables=("base_user", "fin_transaction"),
        source_fields=("updated_at", "amount", "transaction_time"),
    ),
    "RW-016": RuleMeta(
        rule_id="RW-016", rule_name=RULE_NAMES["RW-016"], trigger_scope="event",
        risk_level="中高风险", weight_tier=WEIGHT_MEDIUM, priority=5, check_func=check_rw016,
        thresholds={"min_age": RW016_MIN_AGE, "min_single_outflow": RW016_MIN_SINGLE_OUTFLOW,
                    "outflow_7d_total": RW016_7D_OUTFLOW_TOTAL, "window_days": RW016_WINDOW_DAYS,
                    "avg_window_days": RW016_AVG_WINDOW_DAYS,
                    "monthly_avg_multiplier": RW016_MONTHLY_AVG_MULTIPLIER},
        source_tables=("fin_transaction", "base_user"),
        source_fields=("amount", "transaction_type", "transaction_time"),
    ),
    "RW-017": RuleMeta(
        rule_id="RW-017", rule_name=RULE_NAMES["RW-017"], trigger_scope="event",
        risk_level="中高风险", weight_tier=WEIGHT_MEDIUM, priority=4, check_func=check_rw017,
        thresholds={"open_window_days": RW017_OPEN_WINDOW_DAYS, "min_single_amount": RW017_MIN_SINGLE_AMOUNT,
                    "min_total_amount": RW017_MIN_TOTAL_AMOUNT},
        source_tables=("base_user", "fin_transaction"),
        source_fields=("created_at", "amount", "transaction_time"),
    ),
    "RW-018": RuleMeta(
        rule_id="RW-018", rule_name=RULE_NAMES["RW-018"], trigger_scope="weekly",
        risk_level="高风险", weight_tier=WEIGHT_STRONG, priority=1, check_func=check_rw018,
        thresholds={"window_days": RW018_WINDOW_DAYS, "min_linked_accounts": RW018_MIN_LINKED_ACCOUNTS,
                    "min_aggregated_amount": RW018_MIN_AGGREGATED_AMOUNT},
        source_tables=("fin_transaction",),
        source_fields=("device_fingerprint", "payer_account_name", "amount", "transaction_time"),
    ),
    "RW-019": RuleMeta(
        rule_id="RW-019", rule_name=RULE_NAMES["RW-019"], trigger_scope="daily",
        risk_level="高风险", weight_tier=WEIGHT_STRONG, priority=1, check_func=check_rw019,
        thresholds={"max_inflow_single": RW019_MAX_INFLOW_SINGLE, "max_inflow_daily": RW019_MAX_INFLOW_DAILY,
                    "min_outflow_single": RW019_MIN_OUTFLOW_SINGLE,
                    "night_start_hour": RW019_NIGHT_START_HOUR, "night_end_hour": RW019_NIGHT_END_HOUR},
        source_tables=("fin_transaction",),
        source_fields=("amount", "transaction_time", "payer_account_name", "counterparty_account"),
    ),
    "RW-020": RuleMeta(
        rule_id="RW-020", rule_name=RULE_NAMES["RW-020"], trigger_scope="daily",
        risk_level="中高风险", weight_tier=WEIGHT_MEDIUM, priority=4, check_func=check_rw020,
        thresholds={"min_amount": RW020_MIN_AMOUNT, "offshore_regions": RW020_OFFSHORE_REGIONS},
        source_tables=("fin_transaction", "fin_risk_assessment"),
        source_fields=("counterparty_region", "amount"),
    ),
}

# 兼容别名：部分文档按 dict 索引规则（研判落地方案§1 的 AML_RULES: dict[str, RuleMeta] 命名即 AML_RULES 本身）
RULE_BY_ID: Dict[str, RuleMeta] = AML_RULES

__all__ = [
    "RuleDataUnavailableError", "RuleHit", "RuleContext", "RuleMeta",
    "RISK_LEVEL_MIN_SEVERITY", "MEDIUM_RISK_RULE_IDS",
    "AML_RULES", "RULE_BY_ID", "REALTIME_RULE_IDS", "DAILY_RULE_IDS", "WEEKLY_RULE_IDS",
    "check_rw001", "check_rw002", "check_rw003", "check_rw004", "check_rw005",
    "check_rw006", "check_rw007", "check_rw008", "check_rw009", "check_rw010",
    "check_rw011", "check_rw012", "check_rw013", "check_rw014", "check_rw015",
    "check_rw016", "check_rw017", "check_rw018", "check_rw019", "check_rw020",
]
