"""
智能财富管家系统启动文件

独立的业务模块启动入口，复用Base脚手架能力
"""
import sys
import os
import importlib
import pkgutil
from concurrent.futures import ThreadPoolExecutor

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from app.Base.Config.logConfig import setup_logging

setup_logging()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.WealthButler.runtimeConfig import (
    load_operator_runtime_config,
    load_web_runtime_config,
)


web_config = load_web_runtime_config()


def _register_scheduler_modules_once() -> tuple[str, ...]:
    """仅导入带装饰器的调度模块，避免 auto_register 对同一函数二次注册。"""
    from app.Base.Service import scheduler as scheduler_package

    module_names = sorted(
        item.name for item in pkgutil.iter_modules(scheduler_package.__path__)
        if item.name not in {"auto_register", "__init__"} and not item.name.startswith("_")
    )
    for name in module_names:
        importlib.import_module(f"app.Base.Service.scheduler.{name}")
    return tuple(module_names)


def _assert_unique_scheduler_jobs(scheduler_client) -> None:
    """启动前拒绝重复 job id，防止同一批任务被执行两次。"""
    # TaskSchedulerClient.get_jobs() 会读取尚未启动 Job 的 next_run_time，
    # APScheduler 此时还没有该属性，因此直接读取底层 Job.id。
    job_ids = [job.id for job in scheduler_client.scheduler.get_jobs()]
    duplicates = sorted({job_id for job_id in job_ids if job_ids.count(job_id) > 1})
    if duplicates:
        raise RuntimeError("调度任务重复注册: " + ", ".join(duplicates))


def _get_scheduler_client():
    """加载调度器客户端；启动时可与无关的路由导入安全重叠。"""
    from app.Base.Service.schedulerService import get_base_module_scheduler_client

    return get_base_module_scheduler_client()


def _register_routes_once(app: FastAPI) -> None:
    """延迟导入并注册路由，保证 ``import main`` 不探测外部服务。"""
    if getattr(app.state, "wealth_routes_registered", False):
        return
    from app.Base.Api.authApi import register_auth_router
    from app.WealthButler.Api import (
        register_advisor_api,
        register_analyst_api,
        register_compliance_write_api,
        register_holdings_api,
        register_operator_api,
        register_phase5_contract_api,
        register_risk_api,
        register_wealth_chat_router,
        register_wealth_frontend_router,
        register_workorder_api,
    )

    register_auth_router(app)
    register_wealth_frontend_router(app)
    register_wealth_chat_router(app)
    register_risk_api(app)
    register_holdings_api(app)
    register_workorder_api(app)
    register_advisor_api(app)
    register_operator_api(app)
    register_analyst_api(app)
    register_compliance_write_api(app)
    register_phase5_contract_api(app)
    app.state.wealth_routes_registered = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    scheduler_client = None
    operator_resources = None
    try:
        # 调度器模块加载与路由导入互不修改同一对象，可重叠其冷启动开销。
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="scheduler-loader") as pool:
            scheduler_future = pool.submit(_get_scheduler_client)
            _register_routes_once(app)
            scheduler_client = scheduler_future.result()

        # Operator 默认关闭；显式开启时任何配置、Schema 或连接问题都会阻止启动，
        # 从不回退到 Fake Runtime。
        from app.WealthButler.Service.chatService import ChatService

        ChatService.configure_operator_runtime(None)
        operator_config = load_operator_runtime_config()
        if operator_config.enabled:
            from app.WealthButler.Service.operatorRuntimeAssembly import (
                build_operator_runtime_resources,
            )

            operator_resources = await build_operator_runtime_resources(operator_config)
            ChatService.configure_operator_runtime(operator_resources.runtime)
            operator_resources.start_retry_consumer()
            app.state.operator_runtime_mode = "real"
        else:
            app.state.operator_runtime_mode = "disabled"

        # 启动时：启动所有 EventBus 消费者
        from app.WealthButler.EventBus.consumer import start_all_consumers

        print("[Startup] 启动 EventBus 消费者...")
        start_all_consumers()

        # 调度装饰器在模块导入时已注册任务；不要再调用 auto_register 二次添加。
        print("[Startup] 注册定时任务...")
        _register_scheduler_modules_once()
        _assert_unique_scheduler_jobs(scheduler_client)
        scheduler_client.start()

        print("[Startup] 智能财富管家系统启动完成")

        yield
    finally:
        if scheduler_client is not None and scheduler_client.scheduler.running:
            scheduler_client.shutdown(wait=False)
        from app.WealthButler.EventBus.consumer import stop_all_consumers

        stop_all_consumers()
        if operator_resources is not None:
            await operator_resources.close()

        print("[Shutdown] 智能财富管家系统关闭")


# 创建FastAPI应用
app = FastAPI(
    title="智能财富管家系统",
    description="Intelligent Wealth Butler System - AI驱动的财富管理平台",
    version="1.0.0",
    lifespan=lifespan,
    debug=web_config.debug,
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(web_config.cors_origins),
    allow_credentials=web_config.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("智能财富管家系统 (Intelligent Wealth Butler)")
    print("=" * 60)
    print(f"项目根目录: {project_root}")
    print(f"Python路径已配置: {sys.path[0]}")
    print("-" * 60)
    print("正在启动服务...")
    print("API文档: http://127.0.0.1:8010/docs")
    print("前端登录: http://127.0.0.1:8010/")
    print("=" * 60)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8010,
        log_level=web_config.log_level,
        access_log=web_config.access_log,
    )
