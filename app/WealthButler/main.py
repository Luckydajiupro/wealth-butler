"""
智能财富管家系统启动文件

独立的业务模块启动入口，复用Base脚手架能力
"""
from app.Base.Config.logConfig import setup_logging

setup_logging()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# 导入脚手架基础能力
from app.Base.Api.authApi import register_auth_router
from app.Base.Service.scheduler.auto_register import auto_register_all_scheduler

# 导入WealthButler业务模块
from app.WealthButler.EventBus.consumer import start_all_consumers
from app.WealthButler.Api import (
    register_wealth_chat_router,
    register_risk_api,
    register_wealth_frontend_router,
    register_holdings_api,
    register_workorder_api
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时：启动所有 EventBus 消费者
    print("🚀 启动 EventBus 消费者...")
    start_all_consumers()

    # 启动时：注册定时任务
    print("⏰ 注册定时任务...")
    auto_register_all_scheduler()

    print("✅ 智能财富管家系统启动完成")

    yield

    # 关闭时：消费者为守护线程，会自动退出
    print("👋 智能财富管家系统关闭")


# 创建FastAPI应用
app = FastAPI(
    title="智能财富管家系统",
    description="Intelligent Wealth Butler System - AI驱动的财富管理平台",
    version="1.0.0",
    lifespan=lifespan
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
# 1. 脚手架基础路由（认证）
register_auth_router(app)

# 2. WealthButler业务路由
register_wealth_frontend_router(app)  # 前端页面
register_wealth_chat_router(app)      # 对话接口
register_risk_api(app)                # 风控接口
register_holdings_api(app)            # 持仓接口
register_workorder_api(app)           # 工单接口


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(
        app=app,
        host="0.0.0.0",
        port=8010,
        log_level="info"
    )
