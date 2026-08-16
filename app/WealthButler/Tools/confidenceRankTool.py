"""记忆候选重排工具（组D）

职责：只对**已经召回**的记忆候选列表做最终排序（需求§5.4.1 综合重排公式），
不负责召回、不计算置信度、不回写 confidence——"最终排序分"不是置信度，不能回写为 confidence。

公式（严格按需求§5.4.1）：
    timeliness = exp(-age_days / 180)
    final_score = 0.4×语义相关性 + 0.3×置信度 + 0.15×时效性 + 0.15×场景权重

排序：按 final_score 从高到低；分数相同时保持输入顺序（稳定排序）。
空候选列表返回 {"ranked": []}；候选缺字段/类型错误/负 age/分数越界 → 抛 ValueError
（项目统一的结构化错误，不静默截断、不补零、不接受非法值）。

权重说明：0.4/0.3/0.15/0.15 为团队拟定的示例权重（需求§10 第2项：排序逻辑有内在依据但未经实测），
**待最终确认**；本文件只在常量区定义一次，禁止散落为魔法数字。

EB-B-16/EB-C-01：生产继承真实 BaseTool；测试用行为一致替身（MOCK_ONLY）隔离验证。
"""
import math
from typing import Any, Dict, List

from pydantic import BaseModel, Field, ValidationError

from app.Base.Ai.base.baseTool import BaseTool  # 生产继承真实 BaseTool（EB-B-16 见模块说明）

# 四因子权重（团队拟定示例值，待最终确认——需求§10 第2项；单点定义，禁止散落）
WEIGHT_SEMANTIC = 0.4
WEIGHT_CONFIDENCE = 0.3
WEIGHT_TIMELINESS = 0.15
WEIGHT_SCENARIO = 0.15
# 时效性半衰期：180 天（exp(-age_days/180)）
TIMELINESS_HALF_LIFE_DAYS = 180
# 结果舍入精度（与 BaseConfidenceCalc 保持一致：round 4 位，测试全覆盖）
ROUND_NDIGITS = 4


class ConfidenceCandidate(BaseModel):
    """单个记忆候选（召回层产出；本工具只消费、不召回）。

    strict=True 原因：pydantic 宽松模式会把 "3" 静默转 int、True 静默转 1/1.0，
    违反"类型错误必须结构化拒绝、不得静默接受非法值"的合同——踩坑修正。
    """

    content: str
    semantic_score: float = Field(ge=0.0, le=1.0, strict=True, description="语义相关性得分（0-1）")
    confidence: float = Field(ge=0.0, le=1.0, strict=True, description="记忆置信度（0-1，来自 BaseConfidenceCalc）")
    age_days: int = Field(ge=0, strict=True, description="记忆年龄（天，>=0 整数）")
    scenario_weight: float = Field(ge=0.0, le=1.0, strict=True, description="场景权重（0-1）")


class FinalConfidenceRankInput(BaseModel):
    """FinalConfidenceRank 的 Function Calling 参数 schema（BaseTool.run 校验用）。"""

    candidates: List[ConfidenceCandidate] = Field(
        default_factory=list,
        description="已召回的候选列表；每项含 content/semantic_score/confidence/age_days/scenario_weight",
    )


class FinalConfidenceRank(BaseTool):
    """记忆候选最终重排工具（公开名 FinalConfidenceRank，Agent设计§7.3）。

    入参：candidates（已召回候选列表）。
    出参：{"ranked": [{"content": str, "final_score": float}]}，按 final_score 降序、同分保持输入顺序。
    只做纯排序，不查库、不写库、不计算置信度。
    """

    name = "FinalConfidenceRank"
    description = (
        "记忆候选最终重排工具（纯排序）：对已召回的候选列表按 "
        "0.4×语义相关性 + 0.3×置信度 + 0.15×exp(-age_days/180) + 0.15×场景权重 计算 final_score，"
        "降序输出（同分保持输入顺序）。本工具只排序，不召回、不计算置信度、不写库；"
        "final_score 是排序分，不是置信度，不回写 confidence。"
    )
    args_schema = FinalConfidenceRankInput

    def __init__(self, name=None, description=None, args_schema=None):
        super().__init__(name=name, description=description, args_schema=args_schema)

    def execute(self, **kwargs) -> Dict[str, Any]:
        """执行重排（BaseTool.run 已用 args_schema 校验过 kwargs）。

        Returns:
            {"ranked": [{"content": str, "final_score": float}]}，JSON 可序列化。
        """
        ranked = self.rank(kwargs["candidates"])
        return {"ranked": [{"content": item["content"], "final_score": item["final_score"]}
                           for item in ranked]}

    @staticmethod
    def rank(candidates) -> List[Dict[str, Any]]:
        """重排核心逻辑（纯函数，供 Tool 与测试直接调用）。

        输入逐项经 ConfidenceCandidate 校验（缺字段/类型错误/负 age/分数越界 → ValidationError
        包装为 ValueError），不静默截断、不补零。空列表返回 []。"""
        if not candidates:
            return []
        scored = []
        for index, candidate in enumerate(candidates, start=1):
            try:
                item = candidate if isinstance(candidate, ConfidenceCandidate) \
                    else ConfidenceCandidate(**candidate)
            except ValidationError as e:
                raise ValueError(f"第{index}个候选非法: {e}") from e
            timeliness = math.exp(-item.age_days / TIMELINESS_HALF_LIFE_DAYS)
            final_score = (
                WEIGHT_SEMANTIC * item.semantic_score
                + WEIGHT_CONFIDENCE * item.confidence
                + WEIGHT_TIMELINESS * timeliness
                + WEIGHT_SCENARIO * item.scenario_weight
            )
            scored.append({"content": item.content, "final_score": round(final_score, ROUND_NDIGITS)})
        # Python sorted 稳定排序：同分时保持输入顺序
        scored.sort(key=lambda item: item["final_score"], reverse=True)
        return scored


__all__ = ["FinalConfidenceRank", "FinalConfidenceRankInput", "ConfidenceCandidate"]
