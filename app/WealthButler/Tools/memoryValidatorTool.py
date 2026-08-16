"""记忆单元六维校验工具（组D）

职责：只校验一个待写入记忆单元（需求§5.4.3 六维 + 组A/客服确认口径），
**不查库、不写库、不做合并、不做持久化**——唯一性维度只判断/报告重复，去重合并流程
由 MemoryService（组E）实现，本工具不得实现该流程。

六维校验（需求§5.4.3 + 组A第13节客服确认）：
1. 枚举：tag ∈ MEMORY_TAG_ENUM（完整枚举待确认，备案 EB-D-02）；info_type ∈ {fact, opinion}；
2. 数值：confidence ∈ [0,1]；evidence_count/conflict_count/recall_count 为非负整数（bool 不接受）；
3. 时间：格式 YYYY-MM-DD HH:MM:SS；create_time <= update_time <= 当前时间；
   valid_until 可为 None，非空时须晚于 create_time；
4. 来源：SOURCE_WHITELIST =（风评问卷/交易行为数据/AI从对话中提取/用户自述/系统默认值）；
5. 唯一性：唯一键 customer_id + tag；只报告重复，不合并；未提供已有 tag 集合 → cannot_check，
   不得假装通过；不同 customer_id 的相同 tag 不算重复（tag 集合由调用方按客户提供）；
6. 内容：非空字符串、去除首尾空白后仍非空、长度 <= 500 字符。

处置矩阵（组A第13节客服确认⑤）：
- 枚举/来源非法 → action=demote：status 语义 demoted、adjusted_confidence = confidence×0.8，
  生成违规项与告警语义（本工具不写库、不真正发布告警）；
- 时间逻辑非法 → action=reject；
- customer_id+tag 重复 → action=reject（提示需进入去重/合并流程）；
- 内容/数值/必填字段非法 → action=reject（无既有合同，本组定口径，备案 EB-D-05）；
- 唯一性无法检查（无已有 tag 集合）→ action=cannot_check，valid=False。

字段阶段约定（组A第13节客服确认②）：ProfileExtract 只出 6 个业务字段
（tag/content/info_type/source/confidence，视为**必填**）；技术字段
（unit_id/evidence_count/conflict_count/recall_count/create_time/update_time/valid_until/status）
由写入方补齐，视为**可检查**——提供则校验、未提供不违规。

数据合同备案 EB-D-01：表设计文档称 memory_units 元素为"14 个字段"，实际列出 13 个
（unit_id/tag/info_type/content/source/confidence/evidence_count/conflict_count/recall_count/
create_time/update_time/valid_until/status）；本组按实际 13 字段校验，不发明第 14 个字段。

EB-B-16/EB-C-01：生产继承真实 BaseTool；测试用行为一致替身（MOCK_ONLY）隔离验证。
"""
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field

from app.Base.Ai.base.baseTool import BaseTool  # 生产继承真实 BaseTool（EB-B-16 见模块说明）

# ======================================================================
# 权威常量（记忆域单点维护；MEMORY_TAG_ENUM 完整清单待确认，备案 EB-D-02）
# ======================================================================

# 已确认首批 tag（客服确认，组A第13节①）；risk_level、income 等示例值**不等于**已确认枚举，
# 未确认前不进入生产常量（测试临时枚举走 validate 的 tag_enum 注入，MOCK_ONLY）
MEMORY_TAG_ENUM: tuple = ("product_interest", "risk_preference",
                          "consultation_frequency", "complaint_history")

INFO_TYPE_ENUM: tuple = ("fact", "opinion")

# 来源白名单（中文键，客服确认①；对齐需求§5.4.1 五来源，"行为推断"取需求命名"交易行为数据"）
SOURCE_WHITELIST: tuple = ("风评问卷", "交易行为数据", "AI从对话中提取", "用户自述", "系统默认值")

STATUS_ENUM: tuple = ("active", "demoted", "archived")

# 时间格式：YYYY-MM-DD HH:MM:SS（客服确认④，MySQL DATETIME 默认格式，不用 ISO8601）
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_TIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

CONTENT_MAX_LENGTH = 500
DEMOTE_FACTOR = 0.8                 # 降级系数（客服确认⑤：confidence×0.8）
ROUND_NDIGITS = 4                   # 舍入精度（与组D另两个工具一致，测试全覆盖）

# 必填业务字段（ProfileExtract 六字段，客服确认②）
REQUIRED_BUSINESS_FIELDS: tuple = ("tag", "content", "info_type", "source", "confidence")


class MemoryValidatorInput(BaseModel):
    """MemoryValidator 的 Function Calling 参数 schema（BaseTool.run 校验用）。

    注意：memory_unit 为 dict，深层字段校验在 validate 逻辑内完成（含必填/可检查区分）；
    existing_tags/tag_enum/now 属于服务层/测试注入，不作为 Function Calling 参数暴露。
    """

    customer_id: int = Field(gt=0, description="客户ID（base_user.id，正整数）")
    memory_unit: Dict[str, Any] = Field(
        description=(
            "待校验记忆单元（dict）。必填业务字段：tag/content/info_type/source/confidence；"
            "可检查技术字段：unit_id/evidence_count/conflict_count/recall_count/"
            "create_time/update_time/valid_until/status。"
        )
    )


class MemoryValidator(BaseTool):
    """记忆单元六维校验工具（公开名 MemoryValidator，Agent设计§7.10）。

    入参：customer_id / memory_unit（校验见 MemoryValidatorInput；validate 另有测试/服务层注入参数）。
    出参：最低合同 {"valid": bool, "violations": [str]} + 扩展字段
    action(accept|demote|reject|cannot_check) / adjusted_confidence / normalized_memory_unit /
    checked_dimensions。只校验，不查库、不写库、不合并。
    """

    name = "MemoryValidator"
    description = (
        "记忆单元六维校验工具（只校验，不存储）：枚举（tag/info_type）、数值范围、时间逻辑、"
        "来源白名单、标签唯一性（customer_id+tag，只报告重复不合并）、内容格式六维校验。"
        "枚举/来源非法返回 demote（置信度×0.8）；时间/重复/内容/数值/必填非法返回 reject；"
        "无法获得已有 tag 集合时返回 cannot_check。本工具不查询数据库、不写库、不合并、不发布告警。"
    )
    args_schema = MemoryValidatorInput

    def __init__(self, name=None, description=None, args_schema=None):
        super().__init__(name=name, description=description, args_schema=args_schema)

    def execute(self, **kwargs) -> Dict[str, Any]:
        """执行校验（BaseTool.run 已用 args_schema 校验过 kwargs）。

        Returns:
            validate() 的结果字典（JSON 可序列化；时间字段均为字符串）。
        """
        return self.validate(customer_id=kwargs["customer_id"], memory_unit=kwargs["memory_unit"])

    # ------------------------------------------------------------------
    # 校验核心（纯逻辑，供 Tool 与测试直接调用）
    # ------------------------------------------------------------------

    @classmethod
    def validate(
        cls,
        customer_id,
        memory_unit,
        existing_tags: Optional[Iterable[str]] = None,
        tag_enum: Optional[Iterable[str]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """六维校验（服务层/测试注入参数说明）。

        Args:
            customer_id: 客户ID（正整数；bool 不被接受）。
            memory_unit: 待校验单元 dict。
            existing_tags: 该客户已有 tag 集合（服务层从 memory_units 提取后传入；
                           未提供 → 唯一性维度 cannot_check，绝不假装通过）。
            tag_enum: 覆盖 MEMORY_TAG_ENUM（仅测试临时枚举注入，MOCK_ONLY；生产不传）。
            now: 当前时间（仅测试注入；默认 datetime.now()）。

        Returns:
            {"valid", "violations", "action", "adjusted_confidence",
             "normalized_memory_unit", "checked_dimensions"}
        """
        now = now or datetime.now()
        # 参数层校验（调用方错误 → 抛 ValueError，与组C统一口径）
        if isinstance(customer_id, bool) or not isinstance(customer_id, int) or customer_id <= 0:
            raise ValueError(f"customer_id 必须是正整数（bool 不被接受），收到: {customer_id!r}")
        if not isinstance(memory_unit, dict):
            raise ValueError(f"memory_unit 必须是 dict，收到: {type(memory_unit)!r}")
        if existing_tags is not None and not isinstance(existing_tags, (list, tuple, set)):
            raise ValueError(f"existing_tags 必须是 tag 列表/集合或 None，收到: {type(existing_tags)!r}")

        unit: Dict[str, Any] = dict(memory_unit)
        active_tag_enum = tuple(tag_enum) if tag_enum is not None else MEMORY_TAG_ENUM

        violations: List[str] = []
        checked: Dict[str, str] = {
            "enum": "ok", "numeric": "ok", "time": "ok",
            "source": "ok", "uniqueness": "ok", "content": "ok",
        }
        reject = False
        demote = False

        # ---- 必填字段（ProfileExtract 六业务字段；缺失 → reject，备案 EB-D-05）----
        for key in REQUIRED_BUSINESS_FIELDS:
            if key not in unit or unit[key] is None:
                violations.append(f"缺少必填字段: {key}")
                reject = True

        # ---- 维度1 枚举：tag / info_type / status（非法 → demote）----
        if unit.get("tag") is not None:
            if unit["tag"] not in active_tag_enum:
                demote = True
                violations.append(
                    f"tag '{unit['tag']}' 不在 MEMORY_TAG_ENUM（完整枚举待确认，备案 EB-D-02）"
                )
        info_type = unit.get("info_type")
        if info_type is not None and info_type not in INFO_TYPE_ENUM:
            demote = True
            violations.append(f"info_type 只允许 fact/opinion，收到: {info_type!r}")
        status = unit.get("status")
        if status is not None and status not in STATUS_ENUM:
            demote = True
            violations.append(f"status 只允许 active/demoted/archived，收到: {status!r}")

        # ---- 维度2 数值：confidence ∈ [0,1]；计数为非负整数（bool 不接受）----
        confidence_ok = False
        confidence_value: Optional[float] = None
        if unit.get("confidence") is not None:
            c = unit["confidence"]
            if isinstance(c, bool) or not isinstance(c, (int, float)):
                violations.append(f"confidence 必须是数值（bool 不被接受），收到: {c!r}")
                reject = True
            else:
                c = float(c)
                if not (0.0 <= c <= 1.0):
                    violations.append(f"confidence 必须在 [0,1] 内，收到: {c!r}")
                    reject = True
                else:
                    confidence_ok = True
                    confidence_value = round(c, ROUND_NDIGITS)
        for key in ("evidence_count", "conflict_count", "recall_count"):
            value = unit.get(key)
            if value is None:
                continue  # 可检查字段：未提供不违规
            if isinstance(value, bool) or not isinstance(value, int):
                violations.append(f"{key} 必须是非负整数（bool 不被接受），收到: {value!r}")
                reject = True
            elif value < 0:
                violations.append(f"{key} 必须 >= 0，收到: {value!r}")
                reject = True

        # ---- 维度3 时间：格式 YYYY-MM-DD HH:MM:SS；create <= update <= now；valid_until ----
        def _parse_time(value, key):
            nonlocal reject  # 闭包内对 reject 的赋值必须声明 nonlocal，否则赋值会丢失（踩坑修正）
            if value is None:
                return None
            if not isinstance(value, str) or not _TIME_PATTERN.match(value):
                violations.append(f"{key} 时间格式必须为 YYYY-MM-DD HH:MM:SS，收到: {value!r}")
                reject = True
                return None
            try:
                return datetime.strptime(value, TIME_FORMAT)
            except ValueError:
                violations.append(f"{key} 不是有效日期时间: {value!r}")
                reject = True
                return None

        create_time = _parse_time(unit.get("create_time"), "create_time")
        update_time = _parse_time(unit.get("update_time"), "update_time")
        if create_time is not None and update_time is not None:
            if create_time > update_time:
                violations.append(
                    f"create_time 不能晚于 update_time: {unit.get('create_time')!r} > {unit.get('update_time')!r}"
                )
                reject = True
        if update_time is not None and update_time > now:
            violations.append(f"update_time 不能晚于当前时间: {unit.get('update_time')!r}")
            reject = True
        valid_until = unit.get("valid_until")
        if valid_until is not None:
            parsed_until = _parse_time(valid_until, "valid_until")
            if parsed_until is not None:
                if create_time is None:
                    violations.append("valid_until 校验需要 create_time（可检查字段未提供）")
                    reject = True
                elif parsed_until <= create_time:
                    violations.append(f"valid_until 必须晚于 create_time: {valid_until!r}")
                    reject = True

        # ---- 维度4 来源：SOURCE_WHITELIST（非法 → demote）----
        source = unit.get("source")
        if source is not None and source not in SOURCE_WHITELIST:
            demote = True
            violations.append(
                f"source '{source}' 不在来源白名单（风评问卷/交易行为数据/AI从对话中提取/用户自述/系统默认值）"
            )

        # ---- 维度5 唯一性：customer_id + tag；只报告重复，不合并；无集合 → cannot_check ----
        cannot_check = False
        tag_value = unit.get("tag")
        if tag_value is None:
            checked["uniqueness"] = "skipped"
        elif existing_tags is None:
            cannot_check = True
            checked["uniqueness"] = "cannot_check"
            violations.append(
                "唯一性维度无法检查：未提供该客户的已有 tag 集合（existing_tags），不得视为通过"
            )
        elif tag_value in existing_tags:
            reject = True
            violations.append(
                f"customer_id={customer_id} 已存在 tag '{tag_value}'，需进入去重/合并流程（本工具不实现合并）"
            )

        # ---- 维度6 内容：非空字符串、去空白后非空、<=500 字符 ----
        normalized_content: Optional[str] = None
        content = unit.get("content")
        if content is not None:
            if not isinstance(content, str):
                violations.append(f"content 必须是字符串，收到: {type(content)!r}")
                reject = True
            else:
                normalized_content = content.strip()
                if not normalized_content:
                    violations.append("content 去除首尾空白后为空")
                    reject = True
                elif len(normalized_content) > CONTENT_MAX_LENGTH:
                    violations.append(f"content 长度 {len(normalized_content)} 超过 {CONTENT_MAX_LENGTH} 字符上限")
                    reject = True

        # ---- 汇总：action 优先级 reject > demote > cannot_check > accept ----
        if reject:
            action, valid = "reject", False
        elif demote:
            action, valid = "demote", True
        elif cannot_check:
            action, valid = "cannot_check", False
        else:
            action, valid = "accept", True

        adjusted_confidence: Optional[float] = None
        if confidence_ok and confidence_value is not None:
            adjusted_confidence = round(confidence_value * DEMOTE_FACTOR, ROUND_NDIGITS) \
                if demote else confidence_value

        normalized = dict(unit)
        if normalized_content is not None:
            normalized["content"] = normalized_content
        if demote:
            normalized["status"] = "demoted"

        return {
            "valid": valid,
            "violations": violations,
            "action": action,
            "adjusted_confidence": adjusted_confidence,
            "normalized_memory_unit": normalized,
            "checked_dimensions": checked,
        }


__all__ = [
    "MemoryValidator", "MemoryValidatorInput",
    "MEMORY_TAG_ENUM", "INFO_TYPE_ENUM", "SOURCE_WHITELIST", "STATUS_ENUM",
    "CONTENT_MAX_LENGTH", "DEMOTE_FACTOR",
]
