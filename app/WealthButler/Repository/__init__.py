"""Repository 层

职责：
- 封装数据访问逻辑，对上层屏蔽底层数据存储细节
- 提供业务相关的查询方法，减少 Service 层直接操作 Model
- 复用 BaseDBModel 的 CRUD 能力，补充业务特定的复杂查询

分层原则：
- Repository 不写业务逻辑判断，只做数据存取
- 复杂的业务规则（如风控规则计算）交给 Service 层
- 尽量复用 Model 层已提供的类方法，Repository 主要做组合与封装

已实现：
- CustomerProfileRepository    客户画像Repository
- TransactionRepository         交易流水Repository
- RiskAlertRepository           风控预警Repository
"""

from app.WealthButler.Repository.customerProfileRepository import CustomerProfileRepository
from app.WealthButler.Repository.transactionRepository import TransactionRepository
from app.WealthButler.Repository.riskAlertRepository import RiskAlertRepository

__all__ = [
    "CustomerProfileRepository",
    "TransactionRepository",
    "RiskAlertRepository",
]
