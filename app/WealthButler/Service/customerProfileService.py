"""客户画像服务层

职责：
- 计算四维度打分（基础属性/投资经验/风险偏好/行为异常）
- 生成综合客户画像（C1-C5）
- 检查硬性熔断规则（FM-01~FM-05）
- 更新画像缓存

依据：
- 需求文档 §5.3 客户画像研判规则
- 《投资者风险画像研判规则》（JR-RULE-2024-001）
"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
import logging
import json

from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel
from app.WealthButler.Models.transactionModel import TransactionModel
from app.WealthButler.Models.holdingsModel import HoldingsModel
from app.Base.Models.userModel import UserModel
from app.Base.Client.redisClient import RedisClient

logger = logging.getLogger(__name__)


class CustomerProfileService:
    """客户画像服务"""

    # 风险等级分层标准（需求文档 §5.3 第十一条）
    RISK_LEVEL_MAPPING = [
        (0, 25, "C1"),    # 0-25分 C1(R1-R2)
        (26, 40, "C2"),   # 26-40分 C2(R1-R3)
        (41, 60, "C3"),   # 41-60分 C3(R1-R4需揭示书)
        (61, 80, "C4"),   # 61-80分 C4(R1-R5需揭示书)
        (81, 100, "C5")   # 81-100分 C5(R1-R5)
    ]

    @classmethod
    def calculate_financial_score(cls, customer_id: int) -> Decimal:
        """计算维度一：基础属性（满分25分）

        公式：(年龄分+学历分+职业分+收入分+资产分) ÷ 5 ÷ 10 × 25

        依据：需求文档 §5.3 第五条
        """
        try:
            # 获取客户基础信息
            user = UserModel.find_by_id(customer_id)
            if not user:
                logger.warning(f"客户{customer_id}不存在")
                return Decimal("5")  # 默认最低分

            # 解析extra_data获取详细信息
            extra_data = user.extra_data or {}

            # 1. 年龄分（6档：26-35最高10分，65+最低3分）
            age = cls._calculate_age(extra_data.get("birthday"))
            age_score = cls._get_age_score(age)

            # 2. 学历分（4档：高中4分~硕士以上10分）
            education = extra_data.get("education", "本科")
            education_score = {
                "高中": 4, "专科": 6, "本科": 8, "硕士": 10, "博士": 10
            }.get(education, 8)

            # 3. 职业分（8档：公务员/事业单位10分~无固定职业2分）
            occupation = extra_data.get("occupation", "企业员工")
            occupation_score = {
                "公务员": 10, "事业单位": 10, "国企员工": 9,
                "外企员工": 8, "企业员工": 7, "自由职业": 5,
                "个体户": 4, "无固定职业": 2
            }.get(occupation, 7)

            # 4. 年收入分（6档：<10万3分~>300万10分）
            annual_income = Decimal(str(extra_data.get("annual_income", 0)))
            income_score = cls._get_income_score(annual_income)

            # 5. 可投资资产分（7档：<5万2分~>1000万10分）
            investable_assets = Decimal(str(extra_data.get("investable_assets", 0)))
            asset_score = cls._get_asset_score(investable_assets)

            # 综合计算
            total = (age_score + education_score + occupation_score +
                    income_score + asset_score) / 5 / 10 * 25

            result = Decimal(str(round(total, 2)))
            logger.info(f"客户{customer_id}基础属性分={result}")
            return result

        except Exception as e:
            logger.error(f"计算基础属性分失败: {e}", exc_info=True)
            return Decimal("5")

    @classmethod
    def calculate_investment_experience_score(cls, customer_id: int) -> Decimal:
        """计算维度二：投资经验（满分25分）

        公式：(投资年限分+产品复杂度分+交易频率分+历史收益分) ÷ 4 ÷ 10 × 25

        依据：需求文档 §5.3 第六条
        """
        try:
            # 获取交易历史
            db = TransactionModel.get_db_connection()
            if not db:
                return Decimal("5")

            # 1. 投资年限分（6档：无经验2分~10年以上10分）
            sql = """SELECT MIN(created_at) as first_trade
                     FROM fin_transaction
                     WHERE customer_id = %s"""
            results = db.execute(sql, (customer_id,))

            if results and results[0]['first_trade']:
                first_trade = results[0]['first_trade']
                years = (datetime.now() - first_trade).days / 365
                years_score = cls._get_years_score(years)
            else:
                years_score = 2  # 无经验

            # 2. 产品复杂度分（6档：仅存款2分~期货期权私募10分）
            holdings = HoldingsModel.find_by_customer_id(customer_id)
            complexity_score = cls._get_complexity_score(holdings)

            # 3. 交易频率分（4档：极低频/低频/中频递增，高频倒扣为6分）
            sql = """SELECT COUNT(*) as trade_count
                     FROM fin_transaction
                     WHERE customer_id = %s
                     AND created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)"""
            results = db.execute(sql, (customer_id,))
            trade_count = results[0]['trade_count'] if results else 0
            frequency_score = cls._get_frequency_score(trade_count)

            # 4. 近三年年化收益分（6档：无记录3分，<-15%为3分，5%-15%为8分）
            profit_score = cls._get_profit_score(customer_id)

            # 综合计算
            total = (years_score + complexity_score + frequency_score + profit_score) / 4 / 10 * 25
            result = Decimal(str(round(total, 2)))
            logger.info(f"客户{customer_id}投资经验分={result}")
            return result

        except Exception as e:
            logger.error(f"计算投资经验分失败: {e}", exc_info=True)
            return Decimal("5")

    @classmethod
    def calculate_risk_preference_score(cls, customer_id: int) -> Decimal:
        """计算维度三：风险偏好（满分30分，上限30/下限0）

        公式：风险测评得分 + 情绪化交易扣分 + 亏损承受调整

        依据：需求文档 §5.3 第七条
        """
        try:
            score = Decimal("15")  # 基准分

            # 1. 风险测评得分（从风险评估表读取，换算为5/10/15/20/25分）
            assessment = RiskAssessmentModel.find_latest_by_customer_id(customer_id)
            if assessment:
                questionnaire_score = cls._convert_questionnaire_score(assessment.total_score)
                score = Decimal(str(questionnaire_score))

            # 2. 情绪化交易扣分（AI行为分析识别）
            emotion_penalty = cls._calculate_emotion_penalty(customer_id)
            score -= Decimal(str(emotion_penalty))

            # 3. 亏损承受能力调整
            if assessment:
                # 从问卷answers中读取第9题（亏损承受能力）
                answers = assessment.answers
                if isinstance(answers, dict):
                    loss_tolerance_option = answers.get(9, answers.get("9", 2))
                elif isinstance(answers, list):
                    answer = next(
                        (item for item in answers if item.get("question_no") == 9),
                        {},
                    )
                    loss_tolerance_option = answer.get("option_index", 2)
                else:
                    loss_tolerance_option = 2
                loss_adjustment = [-5, -2, 0, 3, 5][min(loss_tolerance_option, 4)]
                score += Decimal(str(loss_adjustment))

            # 限制在0-30范围
            result = min(max(score, Decimal("0")), Decimal("30"))
            logger.info(f"客户{customer_id}风险偏好分={result}")
            return result

        except Exception as e:
            logger.error(f"计算风险偏好分失败: {e}", exc_info=True)
            return Decimal("15")

    @classmethod
    def calculate_investment_goal_score(cls, customer_id: int) -> Decimal:
        """计算维度四：行为异常（满分20分，修正因子）

        8种异常行为识别，计分规则：
        - 无异常20分
        - 1-2项低风险15分
        - 1-2项中风险10分
        - 3项以上中风险5分
        - 任何高风险异常0分

        依据：需求文档 §5.3 第八条
        """
        try:
            anomalies = cls._detect_anomalies(customer_id)

            # 统计异常等级
            high_risk_count = sum(1 for a in anomalies if a["level"] == "高")
            medium_risk_count = sum(1 for a in anomalies if a["level"] == "中")
            low_risk_count = sum(1 for a in anomalies if a["level"] == "低")

            # 判定分数
            if high_risk_count > 0:
                score = 0
            elif medium_risk_count >= 3:
                score = 5
            elif medium_risk_count >= 1:
                score = 10
            elif low_risk_count >= 1:
                score = 15
            else:
                score = 20

            result = Decimal(str(score))
            logger.info(f"客户{customer_id}行为异常分={result} (异常数: 高{high_risk_count}/中{medium_risk_count}/低{low_risk_count})")
            return result

        except Exception as e:
            logger.error(f"计算行为异常分失败: {e}", exc_info=True)
            return Decimal("15")

    @classmethod
    def get_comprehensive_profile(cls, customer_id: int, updated_reason: str = "定期") -> Optional[CustomerProfileModel]:
        """获取综合画像（四维度+总分+风险等级）

        Args:
            customer_id: 客户ID
            updated_reason: 更新触发原因（定期/事件/行为/市场/人工触发）

        Returns:
            Optional[CustomerProfileModel]: 客户画像记录
        """
        try:
            # 计算四维度分数
            dim1 = cls.calculate_financial_score(customer_id)
            dim2 = cls.calculate_investment_experience_score(customer_id)
            dim3 = cls.calculate_risk_preference_score(customer_id)
            dim4 = cls.calculate_investment_goal_score(customer_id)

            # 综合评分（需求文档 §5.3 第十条）
            risk_score = dim1 + dim2 + dim3 + dim4

            # 映射到风险等级
            risk_level = cls._map_score_to_level(risk_score)

            # 检查硬性熔断规则
            fm_flags = cls.check_fm_rules(customer_id)

            # 计算资产配置和产品偏好（简化版）
            asset_allocation = cls._analyze_asset_allocation(customer_id)
            product_preference = cls._analyze_product_preference(customer_id)

            # 查询或创建画像记录
            profile = CustomerProfileModel.find_by_customer_id(customer_id)

            if profile:
                # 更新现有记录
                old_risk_level = profile.risk_level
                old_risk_score = profile.risk_score

                profile.risk_level = risk_level
                profile.risk_score = risk_score
                profile.dimension1_score = dim1
                profile.dimension2_score = dim2
                profile.dimension3_score = dim3
                profile.dimension4_score = dim4
                profile.fm_flags = fm_flags
                profile.asset_allocation = asset_allocation
                profile.product_preference = product_preference
                profile.updated_reason = updated_reason
                profile.confidence_score = Decimal("0.80")  # 默认置信度
                profile.update()

                # 发布画像更新事件到EventBus
                try:
                    from app.WealthButler.EventBus.eventBus import EventBus
                    from uuid import uuid4

                    # 构建更新字段
                    updated_fields = {}
                    if old_risk_level != risk_level:
                        updated_fields["risk_level"] = risk_level
                    if old_risk_score != risk_score:
                        updated_fields["risk_score"] = float(risk_score)
                    updated_fields["dimension1_score"] = float(dim1)
                    updated_fields["dimension2_score"] = float(dim2)
                    updated_fields["dimension3_score"] = float(dim3)
                    updated_fields["dimension4_score"] = float(dim4)

                    # 映射更新原因到update_reason
                    reason_mapping = {
                        "定期": "behavior_change",
                        "事件": "risk_reassessment",
                        "行为": "behavior_change",
                        "市场": "behavior_change",
                        "人工触发": "manual"
                    }
                    update_reason_code = reason_mapping.get(updated_reason, "behavior_change")

                    payload = {
                        "customer_id": customer_id,
                        "updated_fields": updated_fields,
                        "update_reason": update_reason_code
                    }

                    trace_id = str(uuid4())
                    EventBus.publish(
                        stream_key="stream:profile_updated",
                        event_type="profile_updated",
                        payload=payload,
                        source_agent="advisor_agent",
                        trace_id=trace_id
                    )

                    logger.info(
                        f"[CustomerProfileService] 画像更新事件已发布: customer_id={customer_id}, "
                        f"updated_fields={list(updated_fields.keys())}, trace_id={trace_id}"
                    )
                except Exception as e:
                    logger.error(f"[CustomerProfileService] 发布画像更新事件失败: {e}", exc_info=True)
                    # 事件发布失败不影响主流程
            else:
                # 创建新记录
                profile = CustomerProfileModel(
                    customer_id=customer_id,
                    risk_level=risk_level,
                    risk_score=risk_score,
                    dimension1_score=dim1,
                    dimension2_score=dim2,
                    dimension3_score=dim3,
                    dimension4_score=dim4,
                    fm_flags=fm_flags,
                    asset_allocation=asset_allocation,
                    product_preference=product_preference,
                    updated_reason=updated_reason,
                    confidence_score=Decimal("0.80")
                )
                if profile.save() <= 0:
                    raise RuntimeError(f"客户{customer_id}画像写入失败")

            # 更新Redis缓存
            cls._update_cache(customer_id, profile)

            logger.info(f"客户{customer_id}画像更新完成：{risk_level}({risk_score}分)")
            return profile

        except Exception as e:
            logger.error(f"生成综合画像失败: {e}", exc_info=True)
            return None

    @classmethod
    def check_fm_rules(cls, customer_id: int) -> List[str]:
        """检查硬性熔断规则（FM-01~FM-05）

        依据：需求文档 §5.3 第九条

        Returns:
            List[str]: 命中的熔断规则编号列表
        """
        fm_flags = []

        try:
            user = UserModel.find_by_id(customer_id)
            if not user:
                return fm_flags

            extra_data = user.extra_data or {}
            age = cls._calculate_age(extra_data.get("birthday"))

            # FM-01 年龄限制
            if age < 18:
                fm_flags.append("FM-01-禁止开户")
            elif 18 <= age <= 22:
                fm_flags.append("FM-01-R4+需监护人")
            elif age > 70:
                fm_flags.append("FM-01-R3+需网点签署")
            elif age > 80:
                fm_flags.append("FM-01-仅允许R1-R2")

            # FM-02 无收入低资产
            annual_income = Decimal(str(extra_data.get("annual_income", 0)))
            investable_assets = Decimal(str(extra_data.get("investable_assets", 0)))

            if annual_income == 0 and investable_assets < 10000:
                fm_flags.append("FM-02-仅允许R1-R2")
            elif annual_income == 0 and 10000 <= investable_assets < 50000:
                fm_flags.append("FM-02-仅允许R1-R3且R3≤30%")

            # FM-03 风评过期
            if RiskAssessmentModel.check_expired(customer_id):
                fm_flags.append("FM-03-风评过期冻结新购")

            # FM-04 身份信息异常（简化实现）
            # 实际需检查证件过期、联网核查等，此处仅做示例

            # FM-05 异常交易熔断（简化实现）
            # 实际需检查单日亏损、连续赎回等，此处仅做示例

            logger.info(f"客户{customer_id}熔断检查完成：{fm_flags}")
            return fm_flags

        except Exception as e:
            logger.error(f"检查熔断规则失败: {e}", exc_info=True)
            return fm_flags

    # ========== 辅助方法 ==========

    @staticmethod
    def _calculate_age(birthday_str: Optional[str]) -> int:
        """计算年龄"""
        if not birthday_str:
            return 35  # 默认年龄
        try:
            birthday = datetime.strptime(birthday_str, "%Y-%m-%d")
            return (datetime.now() - birthday).days // 365
        except:
            return 35

    @staticmethod
    def _get_age_score(age: int) -> int:
        """年龄分（6档）"""
        if age < 26:
            return 8
        elif 26 <= age <= 35:
            return 10
        elif 36 <= age <= 45:
            return 9
        elif 46 <= age <= 55:
            return 7
        elif 56 <= age <= 65:
            return 5
        else:
            return 3

    @staticmethod
    def _get_income_score(annual_income: Decimal) -> int:
        """年收入分（6档）"""
        if annual_income < 100000:
            return 3
        elif annual_income < 300000:
            return 5
        elif annual_income < 500000:
            return 7
        elif annual_income < 1000000:
            return 9
        else:
            return 10

    @staticmethod
    def _get_asset_score(assets: Decimal) -> int:
        """资产分（7档）"""
        if assets < 50000:
            return 2
        elif assets < 200000:
            return 4
        elif assets < 500000:
            return 6
        elif assets < 1000000:
            return 7
        elif assets < 5000000:
            return 8
        elif assets < 10000000:
            return 9
        else:
            return 10

    @staticmethod
    def _get_years_score(years: float) -> int:
        """投资年限分（6档）"""
        if years < 0.5:
            return 2
        elif years < 1:
            return 4
        elif years < 3:
            return 6
        elif years < 5:
            return 8
        elif years < 10:
            return 9
        else:
            return 10

    @staticmethod
    def _get_complexity_score(holdings: List) -> int:
        """产品复杂度分（6档）"""
        # 简化实现：根据持仓数量判断
        if not holdings:
            return 2
        elif len(holdings) <= 2:
            return 4
        elif len(holdings) <= 5:
            return 6
        else:
            return 8

    @staticmethod
    def _get_frequency_score(trade_count: int) -> int:
        """交易频率分（4档，高频倒扣）"""
        weekly_avg = trade_count / 13  # 90天约13周
        if weekly_avg < 0.5:
            return 3
        elif weekly_avg < 1:
            return 6
        elif weekly_avg < 3:
            return 9
        else:
            return 6  # 高频倒扣

    @staticmethod
    def _get_profit_score(customer_id: int) -> int:
        """历史收益分（6档）"""
        # 简化实现：返回中等分
        return 6

    @staticmethod
    def _convert_questionnaire_score(total_score: Decimal) -> int:
        """将问卷百分制换算为风险偏好维度分（5/10/15/20/25）"""
        score_int = int(total_score)
        if 20 <= score_int <= 35:
            return 5
        elif 36 <= score_int <= 50:
            return 10
        elif 51 <= score_int <= 65:
            return 15
        elif 66 <= score_int <= 80:
            return 20
        else:
            return 25

    @staticmethod
    def _calculate_emotion_penalty(customer_id: int) -> int:
        """计算情绪化交易扣分（简化实现）"""
        # 实际需分析追涨杀跌、恐慌赎回、FOMO加仓等行为
        # 此处返回0表示无情绪化交易
        return 0

    @staticmethod
    def _detect_anomalies(customer_id: int) -> List[Dict]:
        """检测8种异常行为（简化实现）"""
        # 实际需检测：频繁赎回、大额集中交易、非正常时段交易等
        # 此处返回空列表表示无异常
        return []

    @staticmethod
    def _analyze_asset_allocation(customer_id: int) -> Dict:
        """分析资产配置（简化实现）"""
        return {"stock": 0.3, "bond": 0.5, "cash": 0.2}

    @staticmethod
    def _analyze_product_preference(customer_id: int) -> Dict:
        """分析产品偏好（简化实现）"""
        return {"preferred_types": ["混合基金", "债券基金"], "risk_appetite": "稳健"}

    @classmethod
    def _map_score_to_level(cls, score: Decimal) -> str:
        """将分数映射到风险等级"""
        score_int = int(score)
        for min_score, max_score, level in cls.RISK_LEVEL_MAPPING:
            if min_score <= score_int <= max_score:
                return level
        return "C1"

    @staticmethod
    def _update_cache(customer_id: int, profile: CustomerProfileModel):
        """更新Redis缓存"""
        try:
            redis_client = RedisClient()
            cache_key = f"profile:{customer_id}"
            cache_data = {
                "risk_level": profile.risk_level,
                "risk_score": float(profile.risk_score),
                "updated_at": profile.updated_at.isoformat() if profile.updated_at else None
            }
            redis_client.set(cache_key, json.dumps(cache_data), ex=7*24*3600)  # 7天TTL
        except Exception as e:
            logger.warning(f"更新缓存失败: {e}")
