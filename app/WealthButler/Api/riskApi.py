from typing import Optional
from fastapi import APIRouter, Query

from app.Base.RicUtils.httpUtils import HttpResponse
from app.WealthButler.Service.riskService import RiskService


router = APIRouter(prefix="/api/risk", tags=["风控预警"])


@router.get("/alerts")
def get_risk_alerts(
    page: int = Query(1, ge=1, description="页码（从1开始）"),
    per_page: int = Query(20, ge=1, le=100, description="每页条数"),
    status: Optional[str] = Query(None, description="状态筛选：待处理/处理中/已处理/误报"),
    risk_level: Optional[str] = Query(None, description="风险等级筛选：low/medium/high/critical")
):
    """
    查询风控预警列表

    支持分页与筛选：
    - page: 页码（从1开始）
    - per_page: 每页条数（1-100）
    - status: 状态筛选（待处理/处理中/已处理/误报）
    - risk_level: 风险等级筛选（low/medium/high/critical）

    返回格式：
    {
        "status_code": 200,
        "data": {
            "alerts": [...],
            "total": 100,
            "page": 1,
            "per_page": 20,
            "total_pages": 5
        },
        "msg": "success."
    }
    """
    result = RiskService.get_alerts_list(
        page=page,
        per_page=per_page,
        status=status,
        risk_level=risk_level
    )

    return HttpResponse.ok(data=result, msg="查询成功")


def register_risk_api(app):
    """注册风控API路由"""
    app.include_router(router)
