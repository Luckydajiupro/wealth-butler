"""Service 层

职责：
- 处理业务逻辑，协调多个 Repository 与 Model
- 实现领域服务，如风控规则引擎、投资组合分析、AI Agent 调度等
- 封装事务边界与数据一致性保证

分层原则：
- Service 层是业务逻辑的核心，不直接操作数据库
- 通过 Repository 访问数据，通过 Agent/Tool 调用外部能力
- 对 API 层提供清晰的业务方法签名

已实现：
- RiskService    风控业务Service
"""

from app.WealthButler.Service.riskService import RiskService

__all__ = ["RiskService"]
