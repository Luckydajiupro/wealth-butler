"""投顾适当性只读校验工具。"""

import logging
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from app.Base.Ai.base.baseTool import BaseTool
from app.WealthButler.Models.productModel import ProductModel
from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel

logger = logging.getLogger(__name__)


class SuitabilityCheckArgs(BaseModel):
    customer_id: int = Field(..., gt=0, description="客户 ID")
    product_id: int = Field(..., gt=0, description="产品 ID")


class SuitabilityCheckTool(BaseTool):
    """按有效风评和产品等级做强合规过滤，不修改任何数据。"""

    name = "SuitabilityCheck"
    description = (
        "校验客户当前有效风险评估与产品风险等级是否适配。私募基金、信托、"
        "资管等非标准化产品即使风险等级匹配，也只能返回仅预约，不执行交易。"
    )
    args_schema = SuitabilityCheckArgs

    MAX_PRODUCT_RISK = {"C1": "R2", "C2": "R3", "C3": "R4", "C4": "R5", "C5": "R5"}
    PRIVATE_PRODUCT_TYPES = {"私募基金", "私募证券投资基金", "信托", "保险", "资管计划", "专户理财"}

    def __init__(
        self,
        assessment_loader: Optional[Callable[[int], Any]] = None,
        product_loader: Optional[Callable[[int], Any]] = None,
    ):
        super().__init__()
        self.assessment_loader = assessment_loader or RiskAssessmentModel.find_valid_by_customer_id
        self.product_loader = product_loader or ProductModel.get_by_id

    def execute(self, customer_id: int, product_id: int) -> dict:
        try:
            assessment = self.assessment_loader(customer_id)
            product = self.product_loader(product_id)
        except Exception as exc:
            logger.warning("适当性数据读取失败: %s", exc)
            return self._rejected("适当性数据暂不可读取")

        if assessment is None:
            return self._rejected("客户没有当前有效的风险评估")
        if product is None:
            return self._rejected("产品不存在")

        risk_level = self._value(assessment, "risk_level")
        product_risk = self._value(product, "risk_level")
        if risk_level not in self.MAX_PRODUCT_RISK or product_risk not in {"R1", "R2", "R3", "R4", "R5"}:
            return self._rejected("客户或产品风险等级无效")

        product_rank = self._risk_rank(product_risk)
        max_rank = self._risk_rank(self.MAX_PRODUCT_RISK[risk_level])
        if product_rank is None or max_rank is None:
            return self._rejected("客户或产品风险等级无效")
        passed = product_rank <= max_rank
        admission_tier = "仅预约" if self._value(product, "product_type") in self.PRIVATE_PRODUCT_TYPES else "可执行"
        if not passed:
            return {
                "passed": False,
                "reason": f"客户{risk_level}不适配产品{product_risk}",
                "requires_disclosure": False,
                "admission_tier": admission_tier,
            }
        return {
            "passed": True,
            "reason": f"客户{risk_level}适配产品{product_risk}",
            "requires_disclosure": product_risk in {"R4", "R5"},
            "admission_tier": admission_tier,
        }

    @staticmethod
    def _value(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @staticmethod
    def _risk_rank(level: Any) -> Optional[int]:
        if isinstance(level, str) and len(level) == 2 and level[0] in {"C", "R"} and level[1].isdigit():
            rank = int(level[1])
            if 1 <= rank <= 5:
                return rank
        return None

    @staticmethod
    def _rejected(reason: str) -> dict:
        return {
            "passed": False,
            "reason": reason,
            "requires_disclosure": False,
            "admission_tier": "不可执行",
        }
