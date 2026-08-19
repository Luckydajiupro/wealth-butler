"""业务 API 接口层

职责：
- 定义 RESTful API 路由与请求/响应模型
- 处理 HTTP 请求参数验证与响应格式化
- 调用 Service 层执行业务逻辑
- 实现权限校验与认证拦截

分层原则：
- 本层只做"接口适配"，不写业务逻辑
- 复杂逻辑交给 Service 层处理
- 统一使用 Base.RicUtils.httpUtils.HttpResponse 返回格式

典型模块：
- chatApi.py         对话接口（统一入口 + 5个Agent直连 + 二次确认 + 会话历史）
- advisorApi.py      投顾相关接口（投顾列表、详情、预约咨询）
- productApi.py      理财产品接口（产品推荐、详情、购买）
- portfolioApi.py    资产配置接口（用户资产、配置方案、调仓建议）
- riskApi.py         风险评估接口（问卷、评分、风险等级）
- analysisApi.py     数据分析接口（市场趋势、用户画像、投资报告）

示例：
    from fastapi import APIRouter, Depends
    from app.Base.RicUtils.httpUtils import HttpResponse
    from WealthButler.Service.advisorService import AdvisorService

    router = APIRouter(prefix="/api/wealth/advisor", tags=["投顾服务"])

    @router.get("/list")
    def get_advisor_list(page: int = 1, size: int = 20):
        advisors, total = AdvisorService.list_advisors(page, size)
        return HttpResponse.ok(data={"advisors": advisors, "total": total})
"""

def register_wealth_chat_router(app):
    from app.WealthButler.Api.chatApi import register_wealth_chat_router as register
    return register(app)


def register_risk_api(app):
    from app.WealthButler.Api.riskApi import register_risk_api as register
    return register(app)


def register_wealth_frontend_router(app):
    from app.WealthButler.Api.frontendApi import register_wealth_frontend_router as register
    return register(app)


def register_holdings_api(app):
    from app.WealthButler.Api.holdingsApi import register_holdings_api as register
    return register(app)


def register_workorder_api(app):
    from app.WealthButler.Api.workOrderApi import register_workorder_api as register
    return register(app)


def register_advisor_api(app):
    from app.WealthButler.Api.advisorApi import register_advisor_api as register
    return register(app)


def register_operator_api(app):
    from app.WealthButler.Api.operatorApi import register_operator_api as register
    return register(app)


def register_analyst_api(app):
    from app.WealthButler.Api.analystApi import register_analyst_api as register
    return register(app)


def register_compliance_write_api(app):
    # 延迟导入保持 ``import main`` 和 API 包检查不初始化数据库/Redis。
    from app.WealthButler.Api.complianceWriteApi import register_compliance_write_api as register
    return register(app)


def register_phase5_contract_api(app):
    from app.WealthButler.Api.phase5ContractApi import register_phase5_contract_api as register
    return register(app)

__all__ = [
    "register_wealth_chat_router",
    "register_risk_api",
    "register_wealth_frontend_router",
    "register_holdings_api",
    "register_workorder_api",
    "register_advisor_api",
    "register_operator_api",
    "register_analyst_api",
    "register_compliance_write_api",
    "register_phase5_contract_api",
]
