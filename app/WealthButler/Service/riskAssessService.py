"""风险评估问卷服务层

职责：
- 提供16题风评问卷
- 计算风险等级（C1-C5）
- 适当性匹配检查
- 保存评估结果

依据：
- 需求文档 §5.1 适当性匹配规则
- 《个人投资者适当性管理指南》（JR-AST-2024-001）第七条、第十条
"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
import logging

from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel

logger = logging.getLogger(__name__)


class RiskAssessService:
    """风险评估问卷服务"""

    # 16题风评问卷定义
    QUESTIONNAIRE = [
        # 年龄维度（权重10%）
        {
            "id": 1,
            "dimension": "年龄",
            "question": "您的年龄是？",
            "options": [
                {"label": "18-25岁", "score": 10},
                {"label": "26-35岁", "score": 9},
                {"label": "36-45岁", "score": 8},
                {"label": "46-55岁", "score": 6},
                {"label": "56-65岁", "score": 4},
                {"label": "65岁以上", "score": 2}
            ]
        },
        # 收入状况维度（权重20%）
        {
            "id": 2,
            "dimension": "收入状况",
            "question": "您的年收入是？",
            "options": [
                {"label": "10万元以下", "score": 3},
                {"label": "10-30万元", "score": 5},
                {"label": "30-50万元", "score": 7},
                {"label": "50-100万元", "score": 9},
                {"label": "100万元以上", "score": 10}
            ]
        },
        {
            "id": 3,
            "dimension": "收入状况",
            "question": "您的收入来源稳定性如何？",
            "options": [
                {"label": "非常不稳定", "score": 2},
                {"label": "不太稳定", "score": 4},
                {"label": "比较稳定", "score": 7},
                {"label": "非常稳定", "score": 10}
            ]
        },
        # 资产规模维度（权重20%）
        {
            "id": 4,
            "dimension": "资产规模",
            "question": "您的可投资金融资产规模是？",
            "options": [
                {"label": "5万元以下", "score": 2},
                {"label": "5-20万元", "score": 4},
                {"label": "20-50万元", "score": 6},
                {"label": "50-100万元", "score": 8},
                {"label": "100万元以上", "score": 10}
            ]
        },
        {
            "id": 5,
            "dimension": "资产规模",
            "question": "本次投资金额占您总资产的比例是？",
            "options": [
                {"label": "10%以下", "score": 10},
                {"label": "10%-30%", "score": 8},
                {"label": "30%-50%", "score": 5},
                {"label": "50%-70%", "score": 3},
                {"label": "70%以上", "score": 1}
            ]
        },
        # 投资经验维度（权重20%）
        {
            "id": 6,
            "dimension": "投资经验",
            "question": "您的投资年限是？",
            "options": [
                {"label": "无投资经验", "score": 2},
                {"label": "1年以下", "score": 4},
                {"label": "1-3年", "score": 6},
                {"label": "3-5年", "score": 8},
                {"label": "5年以上", "score": 10}
            ]
        },
        {
            "id": 7,
            "dimension": "投资经验",
            "question": "您持有过的最复杂金融产品是？",
            "options": [
                {"label": "仅存款/货币基金", "score": 2},
                {"label": "债券基金", "score": 4},
                {"label": "混合基金", "score": 6},
                {"label": "股票/股票基金", "score": 8},
                {"label": "期货期权/私募", "score": 10}
            ]
        },
        {
            "id": 8,
            "dimension": "投资经验",
            "question": "您的投资交易频率是？",
            "options": [
                {"label": "几乎不交易", "score": 3},
                {"label": "每月1-2次", "score": 6},
                {"label": "每周1-2次", "score": 9},
                {"label": "每周3次以上", "score": 6}  # 高频倒扣
            ]
        },
        # 风险承受能力维度（权重20%）
        {
            "id": 9,
            "dimension": "风险承受能力",
            "question": "您能承受的最大投资亏损比例是？",
            "options": [
                {"label": "不能承受任何亏损", "score": 1},
                {"label": "5%以内", "score": 3},
                {"label": "10%-20%", "score": 6},
                {"label": "20%-40%", "score": 9},
                {"label": "40%以上", "score": 10}
            ]
        },
        {
            "id": 10,
            "dimension": "风险承受能力",
            "question": "如果投资出现20%亏损，您会？",
            "options": [
                {"label": "立即全部赎回", "score": 2},
                {"label": "赎回部分止损", "score": 4},
                {"label": "继续持有观望", "score": 7},
                {"label": "逢低加仓", "score": 10}
            ]
        },
        {
            "id": 11,
            "dimension": "风险承受能力",
            "question": "您对投资波动的态度是？",
            "options": [
                {"label": "无法接受任何波动", "score": 2},
                {"label": "能接受小幅波动", "score": 5},
                {"label": "能接受中等波动", "score": 8},
                {"label": "能接受大幅波动", "score": 10}
            ]
        },
        # 投资目标维度（权重10%）
        {
            "id": 12,
            "dimension": "投资目标",
            "question": "您的投资期限是？",
            "options": [
                {"label": "3个月以内", "score": 3},
                {"label": "3-12个月", "score": 5},
                {"label": "1-3年", "score": 7},
                {"label": "3-5年", "score": 9},
                {"label": "5年以上", "score": 10}
            ]
        },
        {
            "id": 13,
            "dimension": "投资目标",
            "question": "您期望的年化收益率是？",
            "options": [
                {"label": "2%以下（保本为主）", "score": 2},
                {"label": "2%-5%", "score": 4},
                {"label": "5%-10%", "score": 6},
                {"label": "10%-20%", "score": 8},
                {"label": "20%以上", "score": 10}
            ]
        },
        {
            "id": 14,
            "dimension": "投资目标",
            "question": "您的投资目的是？",
            "options": [
                {"label": "资产保值", "score": 3},
                {"label": "稳定增值", "score": 5},
                {"label": "资产增值", "score": 7},
                {"label": "追求高收益", "score": 10}
            ]
        },
        # 其他维度
        {
            "id": 15,
            "dimension": "其他",
            "question": "您是否了解投资相关的金融知识？",
            "options": [
                {"label": "完全不了解", "score": 2},
                {"label": "了解一点", "score": 5},
                {"label": "比较了解", "score": 8},
                {"label": "非常了解", "score": 10}
            ]
        },
        {
            "id": 16,
            "dimension": "其他",
            "question": "您是否有稳定的紧急备用金？",
            "options": [
                {"label": "没有", "score": 2},
                {"label": "1-3个月开支", "score": 5},
                {"label": "3-6个月开支", "score": 8},
                {"label": "6个月以上开支", "score": 10}
            ]
        }
    ]

    # 六维度权重（需求文档 §5.1）
    DIMENSION_WEIGHTS = {
        "年龄": 0.10,
        "收入状况": 0.20,
        "资产规模": 0.20,
        "投资经验": 0.20,
        "风险承受能力": 0.20,
        "投资目标": 0.10
    }

    # 风险等级映射（需求文档 §5.1 第十条）
    RISK_LEVEL_MAPPING = [
        (20, 35, "C1"),  # 20-35分 C1保守型
        (36, 50, "C2"),  # 36-50分 C2稳健型
        (51, 65, "C3"),  # 51-65分 C3平衡型
        (66, 80, "C4"),  # 66-80分 C4进取型
        (81, 100, "C5")  # 81-100分 C5激进型
    ]

    # 适当性匹配矩阵（需求文档 §5.1 第十二条、第十四条）
    SUITABILITY_MATRIX = {
        "C1": {"allowed": ["R1", "R2"], "forbidden": ["R3", "R4", "R5"]},
        "C2": {"allowed": ["R1", "R2", "R3"], "forbidden": ["R4", "R5"]},
        "C3": {"allowed": ["R1", "R2", "R3"], "with_disclosure": ["R4"], "forbidden": ["R5"]},
        "C4": {"allowed": ["R1", "R2", "R3", "R4"], "with_disclosure": ["R5"], "forbidden": []},
        "C5": {"allowed": ["R1", "R2", "R3", "R4", "R5"], "with_disclosure": [], "forbidden": []}
    }

    @classmethod
    def get_questionnaire(cls) -> List[Dict]:
        """获取16题风评问卷

        Returns:
            List[Dict]: 问卷题目列表
        """
        return cls.QUESTIONNAIRE

    @classmethod
    def calculate_risk_level(cls, answers: Dict[int, int]) -> Tuple[Decimal, str]:
        """计算风险等级（C1-C5）

        Args:
            answers: 答题记录，格式：{question_id: selected_option_index}

        Returns:
            Tuple[Decimal, str]: (总分, 风险等级)

        算法依据：
        - 六维度加权：年龄10%/收入20%/资产20%/经验20%/承受能力20%/目标10%
        - 分级标准：20-35(C1)/36-50(C2)/51-65(C3)/66-80(C4)/81-100(C5)
        """
        try:
            # 按维度聚合分数
            dimension_scores = {}
            for question in cls.QUESTIONNAIRE:
                q_id = question["id"]
                dimension = question["dimension"]

                if q_id not in answers:
                    logger.warning(f"问题{q_id}未作答，跳过")
                    continue

                option_index = answers[q_id]
                if option_index < 0 or option_index >= len(question["options"]):
                    logger.warning(f"问题{q_id}选项索引{option_index}无效")
                    continue

                score = question["options"][option_index]["score"]

                if dimension not in dimension_scores:
                    dimension_scores[dimension] = []
                dimension_scores[dimension].append(score)

            # 计算各维度平均分
            dimension_avg = {}
            for dim, scores in dimension_scores.items():
                dimension_avg[dim] = sum(scores) / len(scores) if scores else 0

            # 加权计算总分
            total_score = Decimal("0")
            for dim, weight in cls.DIMENSION_WEIGHTS.items():
                if dim in dimension_avg:
                    total_score += Decimal(str(dimension_avg[dim])) * Decimal(str(weight)) * Decimal("10")

            # 限制在0-100范围
            total_score = min(max(total_score, Decimal("0")), Decimal("100"))

            # 映射到风险等级
            risk_level = cls._map_score_to_level(total_score)

            logger.info(f"风险评估完成：总分={total_score}, 等级={risk_level}")
            return total_score, risk_level

        except Exception as e:
            logger.error(f"计算风险等级失败: {e}", exc_info=True)
            # 默认返回最保守等级
            return Decimal("20"), "C1"

    @classmethod
    def _map_score_to_level(cls, score: Decimal) -> str:
        """将分数映射到风险等级"""
        score_int = int(score)
        for min_score, max_score, level in cls.RISK_LEVEL_MAPPING:
            if min_score <= score_int <= max_score:
                return level
        # 默认返回最保守等级
        return "C1"

    @classmethod
    def check_suitability(cls, customer_level: str, product_level: str) -> Dict[str, any]:
        """适当性匹配检查

        Args:
            customer_level: 客户风险等级（C1-C5）
            product_level: 产品风险等级（R1-R5）

        Returns:
            Dict: {
                "matched": bool,  # 是否匹配
                "action": str,    # "allow"|"disclosure"|"forbidden"
                "message": str    # 提示信息
            }

        依据：
        - 需求文档 §5.1 第十二条、第十四条
        - C1只能买R1-R2；C2至R3；C3至R3(R4需揭示书)；C4至R4(R5需揭示书)；C5全可
        """
        if customer_level not in cls.SUITABILITY_MATRIX:
            return {
                "matched": False,
                "action": "forbidden",
                "message": f"无效的客户风险等级: {customer_level}"
            }

        matrix = cls.SUITABILITY_MATRIX[customer_level]

        # 检查是否在允许列表
        if product_level in matrix.get("allowed", []):
            return {
                "matched": True,
                "action": "allow",
                "message": "适当性匹配通过"
            }

        # 检查是否需要风险揭示书
        if product_level in matrix.get("with_disclosure", []):
            return {
                "matched": True,
                "action": "disclosure",
                "message": f"购买{product_level}产品需签署风险揭示书"
            }

        # 禁止购买
        if product_level in matrix.get("forbidden", []):
            return {
                "matched": False,
                "action": "forbidden",
                "message": f"{customer_level}客户不得购买{product_level}产品（需求文档§5.1第十四条）"
            }

        # 默认禁止
        return {
            "matched": False,
            "action": "forbidden",
            "message": "适当性匹配未通过"
        }

    @classmethod
    def save_assessment_result(
        cls,
        customer_id: int,
        answers: Dict[int, int],
        total_score: Decimal,
        risk_level: str,
        is_professional_investor: bool = False
    ) -> Optional[RiskAssessmentModel]:
        """保存评估结果

        Args:
            customer_id: 客户ID
            answers: 答题记录
            total_score: 总分
            risk_level: 风险等级
            is_professional_investor: 是否专业投资者

        Returns:
            Optional[RiskAssessmentModel]: 保存的评估记录
        """
        try:
            assessment_time = datetime.now()
            valid_until = assessment_time + timedelta(days=365)  # 12个月有效期

            assessment = RiskAssessmentModel(
                customer_id=customer_id,
                total_score=total_score,
                risk_level=risk_level,
                answers=answers,
                is_professional_investor=is_professional_investor,
                assessment_time=assessment_time,
                valid_until=valid_until
            )

            result = assessment.insert()
            logger.info(f"风险评估结果已保存：customer_id={customer_id}, level={risk_level}")
            return result

        except Exception as e:
            logger.error(f"保存风险评估结果失败: {e}", exc_info=True)
            return None

    @classmethod
    def get_latest_assessment(cls, customer_id: int) -> Optional[RiskAssessmentModel]:
        """获取客户最新的风险评估记录"""
        return RiskAssessmentModel.find_latest_by_customer_id(customer_id)

    @classmethod
    def get_valid_assessment(cls, customer_id: int) -> Optional[RiskAssessmentModel]:
        """获取客户当前有效的风险评估记录（未过期）"""
        return RiskAssessmentModel.find_valid_by_customer_id(customer_id)

    @classmethod
    def check_assessment_expired(cls, customer_id: int) -> bool:
        """检查客户风险评估是否已过期（支持FM-03熔断规则）"""
        return RiskAssessmentModel.check_expired(customer_id)
