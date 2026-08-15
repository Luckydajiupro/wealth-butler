"""
WealthButler 前端页面路由
"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

FRONTEND_DIR = Path(__file__).parent.parent / "Frontend"


def register_wealth_frontend_router(app: FastAPI):
    """注册财富管家前端页面路由"""

    @app.get("/", tags=["财富管家-页面"])
    def login_page():
        """财富管家系统登录页面"""
        file = FRONTEND_DIR / "login.html"
        if file.exists():
            return FileResponse(str(file), media_type="text/html")
        return HTMLResponse("<h1>页面未找到</h1>", status_code=404)

    @app.get("/login", tags=["财富管家-页面"])
    def login_page_alias():
        """登录页面（别名）"""
        file = FRONTEND_DIR / "login.html"
        if file.exists():
            return FileResponse(str(file), media_type="text/html")
        return HTMLResponse("<h1>页面未找到</h1>", status_code=404)
