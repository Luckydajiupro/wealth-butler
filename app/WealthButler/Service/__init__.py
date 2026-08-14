"""业务服务层

职责：
- 封装核心业务逻辑（风险计算、产品推荐、资产配置算法等）
- 协调多个 Model 层的数据操作（跨表查询、事务管理）
- 调用外部服务（第三方 API、消息队列、缓存）
- 与 Agent 层交互（调用智能体完成复杂决策）

分层原则：
- 本层是"业务大脑"，包含核心算法与业务规则
- 可被 Api 层、Agent 层、定时任务调用
- 无状态设计，方法尽量为 @staticmethod
- 复杂事务使用 Base.Client.mysqlClient 的事务管理

典型模块：
- advisorService.py        投顾服务（投顾匹配、排班管理、咨询记录）
- productService.py        产品服务（产品筛选、收益计算、持仓管理）
- riskAssessService.py     风险评估（问卷评分、风险等级判定、动态调整）
- portfolioService.py      资产配置（现代投资组合理论、再平衡算法）
- recommendService.py      推荐引擎（基于用户画像的产品推荐、协同过滤）
- dataMiningService.py     数据挖掘（用户行为分析、市场趋势预测）

示例：
    from Base.Client.mysqlClient import get_mysql_client
    from WealthButler.Models.advisorModel import AdvisorModel

    class AdvisorService:
        @staticmethod
        def match_advisor(user_id: int, risk_level: str):
            '''根据用户风险等级匹配合适的投顾'''
            db = get_mysql_client()
            # 业务逻辑：查询投顾专长、当前负载、用户偏好等
            advisors = AdvisorModel.find_by_risk_specialty(risk_level)
            # 智能排序算法
            return sorted(advisors, key=lambda x: x.score, reverse=True)
"""

__all__ = []
