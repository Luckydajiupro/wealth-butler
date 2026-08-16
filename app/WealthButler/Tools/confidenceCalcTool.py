"""记忆置信度计算工具（组D）

职责：只计算单条记忆单元的置信度（需求§5.4.1 公式），不查库、不写库、不排序、不做合并。
与组C"风控置信度"是两套公式、互不复用（Agent设计§6.2/§7.2）：本公式用于记忆体系，
风控规则权重求和公式属于组C，组D 不得复用或修改。

公式（严格按需求§5.4.1）：
    gain = min(evidence_count × 0.05, 0.3)
    penalty = conflict_count × 0.1
    decay = max(0, 1 - age_days / 365 × 0.2)
    confidence = clamp((base + gain - penalty) × decay, 0, 1)

来源初始置信度（需求§5.4.1，供调用方填写 base，本工具不做 source→base 映射）：
    风评问卷0.90 / 交易行为数据0.80 / AI从对话中提取0.60 / 用户自述0.40 / 系统默认值0.20

EB-B-16/EB-C-01：本文件按项目标准继承真实 BaseTool；当前环境因 app/Base 双命名空间循环导入
无法直接加载，测试用行为一致替身（MOCK_ONLY）隔离验证，正式修复归李清华。
"""
from typing import Any, Dict

from pydantic import BaseModel, Field

from app.Base.Ai.base.baseTool import BaseTool  # 生产继承真实 BaseTool（EB-B-16 见模块说明）

# 公式常量（需求§5.4.1；集中管理，禁止散落魔法数字）
EVIDENCE_GAIN_RATE = 0.05        # 每条支持证据增益
EVIDENCE_GAIN_CAP = 0.3          # 证据增益上限（min 封顶）
CONFLICT_PENALTY_RATE = 0.1      # 每条冲突证据惩罚
DECAY_YEAR_RATE = 0.2            # 年度衰减系数（年-20%）
DECAY_DAYS_PER_YEAR = 365        # 年度天数
# 结果舍入精度：仓库无既有约定（组C风控置信度用2位仅适用于其自身输出），
# 本工具统一 round 4 位小数，写库层按模型 DECIMAL(4,3) 自行处理精度，测试全覆盖该约定
ROUND_NDIGITS = 4


class BaseConfidenceCalcInput(BaseModel):
    """BaseConfidenceCalc 的 Function Calling 参数 schema（BaseTool.run 校验用）。"""

    base: float = Field(
        ge=0.0, le=1.0, strict=True,
        description=(
            "来源初始置信度（0-1）：风评问卷0.90、交易行为数据0.80、AI从对话中提取0.60、"
            "用户自述0.40、系统默认值0.20（需求§5.4.1）"
        ),
    )
    evidence_count: int = Field(ge=0, strict=True, description="支持证据条数（>=0 的整数，bool 不被接受）")
    conflict_count: int = Field(ge=0, strict=True, description="冲突证据条数（>=0 的整数，bool 不被接受）")
    age_days: int = Field(ge=0, strict=True, description="记忆年龄（天，>=0 的整数，bool 不被接受）")


class BaseConfidenceCalc(BaseTool):
    """记忆置信度计算工具（公开名 BaseConfidenceCalc，Agent设计§7.2）。

    入参：base / evidence_count / conflict_count / age_days（校验见 BaseConfidenceCalcInput）。
    出参：{"confidence": float}，round 4 位小数。只做纯计算，不查库、不写库。
    """

    name = "BaseConfidenceCalc"
    description = (
        "记忆置信度计算工具（纯计算）：按公式 clamp((base + min(evidence_count×0.05, 0.3) "
        "- conflict_count×0.1) × max(0, 1-age_days/365×0.2), 0, 1) 计算单条记忆单元的置信度。"
        "本工具只计算置信度，不查询数据库、不写库、不排序、不合并；与风控规则置信度是两套公式，互不复用。"
    )
    args_schema = BaseConfidenceCalcInput

    def __init__(self, name=None, description=None, args_schema=None):
        super().__init__(name=name, description=description, args_schema=args_schema)

    def execute(self, **kwargs) -> Dict[str, Any]:
        """执行置信度计算（BaseTool.run 已用 args_schema 校验过 kwargs）。

        Returns:
            {"confidence": float}（round 4 位小数），JSON 可序列化。
        """
        confidence = self.calculate(
            base=kwargs["base"],
            evidence_count=kwargs["evidence_count"],
            conflict_count=kwargs["conflict_count"],
            age_days=kwargs["age_days"],
        )
        return {"confidence": confidence}

    @staticmethod
    def calculate(base, evidence_count, conflict_count, age_days) -> float:
        """置信度核心计算（纯函数，供 Tool 与测试直接调用）。

        类型要求：base 为数值（bool 不被接受），范围 [0,1]；三个计数为 >=0 的 int
        （bool 是 int 的子类，必须显式拒绝，否则 True 会被当作 1 计入证据/冲突/年龄）。
        非法输入抛 ValueError（项目统一的结构化错误口径，与组C参数校验一致）。"""
        for name, value in (("evidence_count", evidence_count),
                            ("conflict_count", conflict_count),
                            ("age_days", age_days)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} 必须是整数（bool 不被接受），收到: {value!r}")
            if value < 0:
                raise ValueError(f"{name} 必须 >= 0，收到: {value!r}")
        if isinstance(base, bool) or not isinstance(base, (int, float)):
            raise ValueError(f"base 必须是数值（bool 不被接受），收到: {base!r}")
        base_value = float(base)
        if not (0.0 <= base_value <= 1.0):
            raise ValueError(f"base 必须在 [0, 1] 内，收到: {base!r}")

        gain = min(evidence_count * EVIDENCE_GAIN_RATE, EVIDENCE_GAIN_CAP)
        penalty = conflict_count * CONFLICT_PENALTY_RATE
        decay = max(0.0, 1 - age_days / DECAY_DAYS_PER_YEAR * DECAY_YEAR_RATE)
        confidence = max(0.0, min(1.0, (base_value + gain - penalty) * decay))
        return round(confidence, ROUND_NDIGITS)


__all__ = ["BaseConfidenceCalc", "BaseConfidenceCalcInput"]
