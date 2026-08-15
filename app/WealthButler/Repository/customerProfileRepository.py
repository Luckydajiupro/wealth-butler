from typing import Optional, List
from decimal import Decimal

from app.WealthButler.Models.customerProfileModel import CustomerProfileModel


class CustomerProfileRepository:
    """
    客户画像Repository层
    封装客户画像表的查询与更新操作
    """

    @staticmethod
    def get_by_user_id(customer_id: int) -> Optional[CustomerProfileModel]:
        """
        根据客户ID查询画像

        Args:
            customer_id: 客户ID

        Returns:
            客户画像对象，不存在返回None
        """
        return CustomerProfileModel.find_by_customer_id(customer_id)

    @staticmethod
    def update_risk_score(
        customer_id: int,
        risk_score: Decimal,
        risk_level: str,
        dimension_scores: Optional[dict] = None,
        updated_reason: str = "事件"
    ) -> bool:
        """
        更新客户风险评分

        Args:
            customer_id: 客户ID
            risk_score: 新的风险评分
            risk_level: 风险等级 (C1-C5)
            dimension_scores: 四维度分数字典 {dimension1_score, dimension2_score, ...}
            updated_reason: 更新原因

        Returns:
            是否更新成功
        """
        profile = CustomerProfileModel.find_by_customer_id(customer_id)
        if not profile:
            return False

        update_data = {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "updated_reason": updated_reason
        }

        if dimension_scores:
            update_data.update(dimension_scores)

        return profile.update(**update_data)

    @staticmethod
    def get_list(
        risk_level: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[CustomerProfileModel]:
        """
        查询客户画像列表

        Args:
            risk_level: 风险等级筛选 (可选)
            limit: 返回条数
            offset: 偏移量

        Returns:
            客户画像列表
        """
        if risk_level:
            return CustomerProfileModel.find_by_risk_level(risk_level)

        return CustomerProfileModel.get_all(limit=limit, offset=offset, order_by="updated_at", order="DESC")

    @staticmethod
    def create(customer_id: int, **kwargs) -> Optional[CustomerProfileModel]:
        """
        创建客户画像

        Args:
            customer_id: 客户ID
            **kwargs: 其他字段

        Returns:
            创建的画像对象，失败返回None
        """
        profile = CustomerProfileModel(customer_id=customer_id, **kwargs)
        profile_id = profile.save()
        if profile_id > 0:
            return profile
        return None
