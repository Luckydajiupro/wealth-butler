from typing import List, Optional
from datetime import datetime
from decimal import Decimal

from app.WealthButler.Models.riskAlertModel import RiskAlertModel


class RiskAlertRepository:
    """
    风控预警Repository层
    封装风控预警的创建、查询与状态更新操作，供风控监测Agent使用
    """

    @staticmethod
    def create(
        customer_id: int,
        rule_id: str,
        rule_name: str,
        severity: str,
        confidence: Decimal,
        trigger_details: Optional[dict] = None,
        related_transaction_id: Optional[int] = None
    ) -> Optional[RiskAlertModel]:
        """
        创建风控预警

        Args:
            customer_id: 客户ID
            rule_id: 规则ID（RW-001~RW-020）
            rule_name: 规则名称
            severity: 严重程度 (low/medium/high/critical)
            confidence: 置信度 0-1
            trigger_details: 触发详情字典
            related_transaction_id: 关联交易ID（可选）

        Returns:
            创建的预警对象，失败返回None
        """
        alert = RiskAlertModel(
            customer_id=customer_id,
            rule_id=rule_id,
            rule_name=rule_name,
            severity=severity,
            confidence=confidence,
            trigger_details=trigger_details,
            related_transaction_id=related_transaction_id
        )
        alert_id = alert.save()
        if alert_id > 0:
            return alert
        return None

    @staticmethod
    def get_pending_alerts(limit: int = 100) -> List[RiskAlertModel]:
        """
        查询待处理的风控预警

        Args:
            limit: 返回条数

        Returns:
            待处理预警列表（按严重程度和时间排序）
        """
        return RiskAlertModel.find_pending(limit=limit)

    @staticmethod
    def get_alerts_by_status(
        status: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[RiskAlertModel]:
        """
        按状态查询风控预警

        Args:
            status: 状态（待处理/处理中/已处理/误报）
            limit: 返回条数
            offset: 偏移量

        Returns:
            预警列表
        """
        return RiskAlertModel.find_by(
            status=status,
            limit=limit,
            offset=offset,
            order_by="created_at",
            order="DESC"
        )

    @staticmethod
    def get_alerts_by_severity(
        severity: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[RiskAlertModel]:
        """
        按严重程度查询风控预警

        Args:
            severity: 严重程度 (low/medium/high/critical)
            limit: 返回条数
            offset: 偏移量

        Returns:
            预警列表
        """
        return RiskAlertModel.find_by(
            severity=severity,
            limit=limit,
            offset=offset,
            order_by="created_at",
            order="DESC"
        )

    @staticmethod
    def update_status(
        alert_id: int,
        status: str,
        handler_id: Optional[int] = None,
        handle_result: Optional[str] = None
    ) -> bool:
        """
        更新预警状态

        Args:
            alert_id: 预警ID
            status: 新状态（待处理/处理中/已处理/误报）
            handler_id: 处理人ID（可选）
            handle_result: 处理结果（可选）

        Returns:
            是否更新成功
        """
        alert = RiskAlertModel.get_by_id(alert_id)
        if not alert:
            return False

        update_data = {"status": status}
        if handler_id:
            update_data["handler_id"] = handler_id
        if handle_result:
            update_data["handle_result"] = handle_result
        if status in ["已处理", "误报"]:
            update_data["handled_at"] = datetime.now()

        return alert.update(**update_data)

    @staticmethod
    def get_by_customer_id(customer_id: int, limit: int = 50) -> List[RiskAlertModel]:
        """
        查询指定客户的风控预警历史

        Args:
            customer_id: 客户ID
            limit: 返回条数

        Returns:
            预警列表
        """
        return RiskAlertModel.find_by_customer_id(customer_id, limit=limit)

    @staticmethod
    def get_by_rule_id(rule_id: str, days: int = 30) -> List[RiskAlertModel]:
        """
        查询指定规则的触发历史（支持规则效果分析）

        Args:
            rule_id: 规则ID
            days: 查询天数

        Returns:
            预警列表
        """
        return RiskAlertModel.find_by_rule_id(rule_id, days=days)

    @staticmethod
    def count_by_filters(
        status: Optional[str] = None,
        severity: Optional[str] = None
    ) -> int:
        """
        统计符合条件的预警数量

        Args:
            status: 状态筛选（可选）
            severity: 严重程度筛选（可选）

        Returns:
            预警数量
        """
        RiskAlertModel._ensure_table_exists()
        db = RiskAlertModel.get_db_connection()
        if db is None:
            return 0

        where_clauses = []
        params = []

        if status:
            where_clauses.append("status = %s")
            params.append(status)
        if severity:
            where_clauses.append("severity = %s")
            params.append(severity)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        sql = f"SELECT COUNT(*) as cnt FROM {RiskAlertModel.table_alias} {where_sql}"

        results = db.execute(sql, tuple(params))
        return results[0]['cnt'] if results else 0
