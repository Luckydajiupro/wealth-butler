from typing import List, Optional, Dict, Any
from decimal import Decimal

from app.WealthButler.Repository.riskAlertRepository import RiskAlertRepository
from app.WealthButler.Repository.transactionRepository import TransactionRepository
from app.WealthButler.Repository.customerProfileRepository import CustomerProfileRepository


class RiskService:
    """
    风控业务Service层
    处理风控预警相关的业务逻辑
    """

    @staticmethod
    def get_alerts_list(
        page: int = 1,
        per_page: int = 20,
        status: Optional[str] = None,
        risk_level: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取风控预警列表（支持分页与筛选）

        Args:
            page: 页码（从1开始）
            per_page: 每页条数
            status: 状态筛选（待处理/处理中/已处理/误报）
            risk_level: 风险等级筛选（high/medium/low/critical）

        Returns:
            包含列表数据和分页信息的字典
        """
        offset = (page - 1) * per_page

        # 根据筛选条件查询
        if status and risk_level:
            # 同时筛选状态和严重程度需要自定义查询
            alerts = RiskAlertRepository.get_alerts_by_status(status, limit=per_page, offset=offset)
            alerts = [a for a in alerts if a.severity == risk_level]
            total = RiskAlertRepository.count_by_filters(status=status, severity=risk_level)
        elif status:
            alerts = RiskAlertRepository.get_alerts_by_status(status, limit=per_page, offset=offset)
            total = RiskAlertRepository.count_by_filters(status=status)
        elif risk_level:
            alerts = RiskAlertRepository.get_alerts_by_severity(risk_level, limit=per_page, offset=offset)
            total = RiskAlertRepository.count_by_filters(severity=risk_level)
        else:
            # 无筛选条件，查询全部（按时间倒序）
            from app.WealthButler.Models.riskAlertModel import RiskAlertModel
            alerts = RiskAlertModel.get_all(limit=per_page, offset=offset, order_by="created_at", order="DESC")
            total = RiskAlertRepository.count_by_filters()

        # 转换为字典列表
        alerts_data = [
            {
                "id": alert.id,
                "customer_id": alert.customer_id,
                "rule_id": alert.rule_id,
                "rule_name": alert.rule_name,
                "severity": alert.severity,
                "confidence": float(alert.confidence) if alert.confidence else 0.0,
                "trigger_details": alert.trigger_details,
                "related_transaction_id": alert.related_transaction_id,
                "status": alert.status,
                "handler_id": alert.handler_id,
                "handle_result": alert.handle_result,
                "handled_at": str(alert.handled_at) if alert.handled_at else None,
                "created_at": str(alert.created_at) if alert.created_at else None,
            }
            for alert in alerts
        ]

        return {
            "alerts": alerts_data,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
        }

    @staticmethod
    def create_alert(
        customer_id: int,
        rule_id: str,
        rule_name: str,
        severity: str,
        confidence: Decimal,
        trigger_details: Optional[dict] = None,
        related_transaction_id: Optional[int] = None
    ) -> Optional[int]:
        """
        创建风控预警

        Returns:
            预警ID，失败返回None
        """
        alert = RiskAlertRepository.create(
            customer_id=customer_id,
            rule_id=rule_id,
            rule_name=rule_name,
            severity=severity,
            confidence=confidence,
            trigger_details=trigger_details,
            related_transaction_id=related_transaction_id
        )
        return alert.id if alert else None

    @staticmethod
    def handle_alert(
        alert_id: int,
        status: str,
        handler_id: int,
        handle_result: Optional[str] = None
    ) -> bool:
        """
        处理风控预警

        Args:
            alert_id: 预警ID
            status: 新状态
            handler_id: 处理人ID
            handle_result: 处理结果

        Returns:
            是否处理成功
        """
        return RiskAlertRepository.update_status(
            alert_id=alert_id,
            status=status,
            handler_id=handler_id,
            handle_result=handle_result
        )
