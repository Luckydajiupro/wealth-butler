"""RiskRuleMatch 工具（组C）

职责：把核心引擎 RiskRuleMatch.match 包装成 Agent 可调用的 Function Calling 工具（Agent设计§7.7）。
- 工具公开名称固定为 `RiskRuleMatch`（与核心引擎类同名是既有文档口径，Tool 类名加 Tool 后缀避免冲突）；
- 继承脚手架 BaseTool（复用 execute/run/to_openai_schema 协议）；
- 参数校验用独立 pydantic schema（RiskRuleMatchInput）——BaseTool.run 会先经 args_schema 校验再进 execute；
- context 不作为 Function Calling 参数暴露：数据缺口注入只允许服务层/测试内部使用（组B RuleContext 契约）。

边界（组C）：本工具是确定性规则匹配工具——不使用 LLM、不做人工可疑上报、不写数据库、不建工单、
不发布事件、不执行交易拦截；数据不足明确返回 insufficient_data，数据源失败返回结构化错误/降级状态。

EB-B-16/EB-C-01 说明：本文件按项目标准继承真实 BaseTool（from app.Base.Ai.base.baseTool import BaseTool）。
当前环境因 app/Base 双命名空间循环导入无法直接加载该模块，测试用行为一致替身（MOCK_ONLY，
见 tests/test_riskRuleMatchTool.py）隔离验证，正式修复归李清华；未修复前不宣称工具完成运行时联调。
"""
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from app.Base.Ai.base.baseTool import BaseTool  # 生产继承真实 BaseTool（EB-B-16 见模块说明）
from app.WealthButler.Rules.ruleEngine import RiskRuleMatch

# 20 条规则ID（与 AML_RULES 的键一致；Literal 枚举保证 Function Calling schema 的 enum 完整）
RULE_ID_LITERAL = Literal[
    "RW-001", "RW-002", "RW-003", "RW-004", "RW-005",
    "RW-006", "RW-007", "RW-008", "RW-009", "RW-010",
    "RW-011", "RW-012", "RW-013", "RW-014", "RW-015",
    "RW-016", "RW-017", "RW-018", "RW-019", "RW-020",
]


class RiskRuleMatchInput(BaseModel):
    """RiskRuleMatch 工具的 Function Calling 参数 schema（BaseTool.run 校验用）。

    rule_scope 的合法取值按 trigger_source 区分（引擎二次校验，双层防线）：
    event 只允许实时/准实时 8 条（RW-001/003/008/011/014/015/016/017）；
    scheduler 只允许日批/周批 12 条（RW-002/004/005/006/007/009/010/012/013/018/019/020）。
    """

    customer_id: int = Field(
        gt=0,
        description="待评估客户ID（base_user.id，正整数）。不允许传客户姓名或自然语言客户标识。",
    )
    rule_scope: List[RULE_ID_LITERAL] = Field(
        min_length=1,
        description=(
            "要评估的规则ID数组，每项只能是 RW-001 至 RW-020（不允许 'all'、不允许 MANUAL 等人工上报值）。"
            "trigger_source='event' 时只能传实时/准实时8条；trigger_source='scheduler' 时只能传日批/周批12条。"
        ),
    )
    trigger_source: Literal["event", "scheduler"] = Field(
        description=(
            "触发来源（不是风险等级）：event=实时/准实时事件触发（大额交易/可疑意图事件回查）；"
            "scheduler=日批/周批定时批量扫描。"
        ),
    )


class RiskRuleMatchTool(BaseTool):
    """确定性风控规则匹配工具（公开名 RiskRuleMatch，Agent设计§7.7）。

    入参：customer_id / rule_scope / trigger_source（校验见 RiskRuleMatchInput）。
    出参：RiskRuleMatchResult 的 JSON 序列化字典（model_dump(mode='json')），
    含命中规则+证据+关联流水、数据不足清单、错误清单、severity/alert_level、confidence、
    重复触发与30天升级信号；不含任何"业务动作已完成"标志（不写库、不建工单、不发事件）。
    """

    name = "RiskRuleMatch"
    description = (
        "确定性风控规则匹配工具：调用规则引擎评估反洗钱规则（RW-001~RW-020）。"
        "本工具不使用 LLM；不做人工可疑上报；不写数据库；不建工单；不发布事件；不执行交易拦截。"
        "返回规则命中与证据（关联流水ID）、三级预警分级（severity/alert_level）、风控置信度、"
        "30天重复触发与中风险累计升级信号。部分规则数据不足时明确返回 insufficient_data，"
        "数据源失败时返回结构化错误或 degraded 降级状态。"
    )
    args_schema = RiskRuleMatchInput

    def __init__(self, name=None, description=None, args_schema=None):
        super().__init__(name=name, description=description, args_schema=args_schema)

    def execute(self, **kwargs) -> Dict[str, Any]:
        """执行规则匹配（BaseTool.run 已用 args_schema 校验过 kwargs）。

        Returns:
            JSON 可序列化字典（RiskRuleMatchResult.model_dump(mode='json')），
            不返回 Pydantic 实例或数据库模型实例。"""
        result = RiskRuleMatch.match(
            customer_id=kwargs["customer_id"],
            rule_scope=kwargs["rule_scope"],
            trigger_source=kwargs["trigger_source"],
        )
        return result.model_dump(mode="json")


__all__ = ["RiskRuleMatchTool", "RiskRuleMatchInput"]
