"""
WealthButler 前端页面路由
"""
from pathlib import Path
from typing import Optional

from fastapi import Cookie, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.Base.Service.authService import AuthService

FRONTEND_DIR = Path(__file__).parent.parent / "Frontend"


ROLE_PAGE_ROLES = {
    "/chat/advisor": "advisor",
    "/chat/operator": "operator",
    "/chat/risk": "risk_officer",
    "/chat/analyst": "business_admin",
    "/admin_dashboard": "business_admin",
    "/risk_dashboard": "risk_officer",
}


def _require_page_role(
    path: str,
    access_token: Optional[str],
    authorization: Optional[str],
):
    """Protect HTML workbenches at the server boundary.

    Browser navigation cannot attach the API client's Authorization header, so
    successful login also issues an HttpOnly cookie.  The header remains
    supported for automated clients and existing integrations.
    """
    token = access_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="缺少认证信息")
    user = AuthService.get_current_user(token)
    if not user or getattr(user, "status", None) != "active":
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    expected = ROLE_PAGE_ROLES[path]
    role_names = AuthService.get_user_role_info(user.id, user.source_module).get("role_names", [])
    if expected not in role_names:
        raise HTTPException(status_code=403, detail="当前角色无权访问该工作台")
    return user


def register_wealth_frontend_router(app: FastAPI):
    """注册财富管家前端页面路由"""

    # 注册静态文件服务（JS、CSS等）
    static_dir = FRONTEND_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

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

    @app.get("/chat/customer", tags=["财富管家-页面"])
    def customer_dashboard():
        """客户工作台"""
        file = FRONTEND_DIR / "pages" / "customer_dashboard.html"
        if file.exists():
            return FileResponse(str(file), media_type="text/html")
        return HTMLResponse("<h1>页面未找到</h1>", status_code=404)

    @app.get("/chat/advisor", tags=["财富管家-页面"])
    def advisor_dashboard(
        access_token: Optional[str] = Cookie(None, alias="wealth_access_token"),
        authorization: Optional[str] = Header(None),
    ):
        """理财顾问工作台"""
        _require_page_role("/chat/advisor", access_token, authorization)
        file = FRONTEND_DIR / "pages" / "advisor_dashboard.html"
        if file.exists():
            return FileResponse(str(file), media_type="text/html")
        return HTMLResponse("<h1>页面未找到</h1>", status_code=404)

    @app.get("/chat/risk", tags=["财富管家-页面"])
    def risk_dashboard(
        access_token: Optional[str] = Cookie(None, alias="wealth_access_token"),
        authorization: Optional[str] = Header(None),
    ):
        """风控专员工作台"""
        _require_page_role("/chat/risk", access_token, authorization)
        file = FRONTEND_DIR / "pages" / "risk_dashboard.html"
        if file.exists():
            return FileResponse(str(file), media_type="text/html")
        return HTMLResponse("<h1>页面未找到</h1>", status_code=404)

    @app.get("/chat/operator", tags=["财富管家-页面"])
    def operator_dashboard(
        access_token: Optional[str] = Cookie(None, alias="wealth_access_token"),
        authorization: Optional[str] = Header(None),
    ):
        """客户经理工作台"""
        _require_page_role("/chat/operator", access_token, authorization)
        file = FRONTEND_DIR / "pages" / "operator_dashboard.html"
        if file.exists():
            return FileResponse(str(file), media_type="text/html")
        return HTMLResponse("<h1>页面未找到</h1>", status_code=404)

    @app.get("/chat/analyst", tags=["财富管家-页面"])
    def analyst_dashboard(
        access_token: Optional[str] = Cookie(None, alias="wealth_access_token"),
        authorization: Optional[str] = Header(None),
    ):
        """业务管理员工作台"""
        _require_page_role("/chat/analyst", access_token, authorization)
        file = FRONTEND_DIR / "pages" / "admin_dashboard.html"
        if file.exists():
            return FileResponse(str(file), media_type="text/html")
        return HTMLResponse("<h1>页面未找到</h1>", status_code=404)

    @app.get("/admin_dashboard", tags=["财富管家-页面"])
    def admin_dashboard_direct(
        access_token: Optional[str] = Cookie(None, alias="wealth_access_token"),
        authorization: Optional[str] = Header(None),
    ):
        """业务管理员工作台（直接路径）"""
        _require_page_role("/admin_dashboard", access_token, authorization)
        file = FRONTEND_DIR / "pages" / "admin_dashboard.html"
        if file.exists():
            return FileResponse(str(file), media_type="text/html")
        return HTMLResponse("<h1>页面未找到</h1>", status_code=404)

    @app.get("/risk_dashboard", tags=["财富管家-页面"])
    def risk_dashboard_direct(
        access_token: Optional[str] = Cookie(None, alias="wealth_access_token"),
        authorization: Optional[str] = Header(None),
    ):
        """风控专员工作台（直接路径）"""
        _require_page_role("/risk_dashboard", access_token, authorization)
        file = FRONTEND_DIR / "pages" / "risk_dashboard.html"
        if file.exists():
            return FileResponse(str(file), media_type="text/html")
        return HTMLResponse("<h1>页面未找到</h1>", status_code=404)
