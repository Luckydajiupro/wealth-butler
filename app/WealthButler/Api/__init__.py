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
- advisorApi.py      投顾相关接口（投顾列表、详情、预约咨询）
- productApi.py      理财产品接口（产品推荐、详情、购买）
- portfolioApi.py    资产配置接口（用户资产、配置方案、调仓建议）
- riskApi.py         风险评估接口（问卷、评分、风险等级）
- analysisApi.py     数据分析接口（市场趋势、用户画像、投资报告）

示例：
    from fastapi import APIRouter, Depends
    from Base.RicUtils.httpUtils import HttpResponse
    from WealthButler.Service.advisorService import AdvisorService

    router = APIRouter(prefix="/api/wealth/advisor", tags=["投顾服务"])

    @router.get("/list")
    def get_advisor_list(page: int = 1, size: int = 20):
        advisors, total = AdvisorService.list_advisors(page, size)
        return HttpResponse.ok(data={"advisors": advisors, "total": total})
"""

__all__ = []
