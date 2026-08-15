from app.Base.Api.ai.chatApi import register_ai_chat_router
from app.Base.Api.authApi import register_auth_router
from app.Base.Config.logConfig import setup_logging
from app.Base.Service.scheduler.auto_register import auto_register_all_scheduler

setup_logging()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# 导入 EventBus 消费者启动函数
from app.WealthButler.EventBus.consumer import start_all_consumers
# 导入 WealthButler 业务API
from app.WealthButler.Api import register_risk_api, register_wealth_chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时：启动所有 EventBus 消费者
    start_all_consumers()

    yield

    # 关闭时：消费者为守护线程，会自动退出


app = FastAPI(lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_ai_chat_router(app)
register_auth_router(app)
register_risk_api(app)
register_wealth_chat_router(app)

# 自动注册定时任务
auto_register_all_scheduler()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app=app, host="0.0.0.0", port=8010)
