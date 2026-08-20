from pathlib import Path
import re
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.Base.RicUtils.httpUtils import HttpResponse
from app.Base.Service.authService import AuthService
from app.Base.Models.roleModel import Permission
from app.Base.Models.menuModel import MenuModel

router = APIRouter(prefix="/api/auth", tags=["认证与用户管理"])

FRONTEND_DIR = Path(__file__).parent.parent / "Frontend"


# =========================
# Request Models
# =========================

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, description="密码")
    email: Optional[str] = None
    phone: Optional[str] = None
    source_module: str = Field("default", description="来源模块")
    extra_data: Optional[dict] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)


class UpdateProfileRequest(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    extra_data: Optional[dict] = None


class GrantRoleRequest(BaseModel):
    target_user_id: int
    role_name: str = Field(..., description="角色名")
    source_module: Optional[str] = None
    expires_at: Optional[datetime] = None


class SetUserRolesRequest(BaseModel):
    target_user_id: int
    role_names: List[str] = Field(..., description="角色名列表")
    source_module: Optional[str] = None


class UpdateStatusRequest(BaseModel):
    user_id: int
    status: str


class ResetPasswordRequest(BaseModel):
    user_id: int
    new_password: str = Field("123456", min_length=6)


class CreateRoleRequest(BaseModel):
    name: str = Field(..., max_length=50, description="角色标识")
    display_name: str = Field(..., max_length=100, description="显示名称")
    permissions: List[str] = Field(..., description="权限列表")
    description: Optional[str] = None
    source_module: str = "default"


class UpdateRolePermissionsRequest(BaseModel):
    role_name: str
    permissions: List[str]
    source_module: str = "default"


class CreateMenuRequest(BaseModel):
    parent_id: Optional[int] = None
    name: str = Field(..., max_length=50)
    path: str = Field(..., max_length=200)
    component: str = Field(..., max_length=200)
    icon: Optional[str] = Field(None, max_length=50)
    permission: Optional[str] = Field(None, max_length=100)
    sort_order: int = 0
    is_visible: bool = True
    source_module: str = "default"


class UpdateMenuRequest(BaseModel):
    parent_id: Optional[int] = None
    name: Optional[str] = Field(None, max_length=50)
    path: Optional[str] = Field(None, max_length=200)
    component: Optional[str] = Field(None, max_length=200)
    icon: Optional[str] = Field(None, max_length=50)
    permission: Optional[str] = Field(None, max_length=100)
    sort_order: Optional[int] = None
    is_visible: Optional[bool] = None


class SortMenuRequest(BaseModel):
    items: List[dict] = Field(..., description="[{id, sort_order}]")


security = HTTPBearer(auto_error=False)


def _user_identity(user) -> dict:
    """Return display and business identity fields across old/new schemas."""
    identity = {
        "display_name": None,
        "user_type": None,
        "employee_role": None,
        "advisor_level": None,
        "customer_level": None,
    }
    extra = getattr(user, "extra_data", None)
    if isinstance(extra, dict):
        identity["display_name"] = extra.get("display_name") or extra.get("real_name")
        for key in ("user_type", "employee_role", "advisor_level", "customer_level"):
            if extra.get(key) is not None:
                identity[key] = extra[key]
    try:
        from app.Base.Client.mysqlClient import MySQLClient
        client = MySQLClient()
        try:
            rows = client.execute_sync(
                "SELECT user_type, employee_role, advisor_level, customer_level, extra_data "
                "FROM base_user WHERE id=%s LIMIT 1", (user.id,)
            ) or []
        finally:
            client.close()
        if rows:
            row = rows[0]
            for key in ("user_type", "employee_role", "advisor_level", "customer_level"):
                if row.get(key) is not None:
                    identity[key] = row[key]
            row_extra = row.get("extra_data")
            if isinstance(row_extra, str):
                import json
                try:
                    row_extra = json.loads(row_extra)
                except (TypeError, ValueError):
                    row_extra = {}
            if isinstance(row_extra, dict):
                identity["display_name"] = (
                    row_extra.get("display_name") or row_extra.get("real_name")
                    or identity["display_name"]
                )
    except Exception:
        # Optional presentation metadata must not make a valid login fail on
        # an older base_user schema.
        pass
    identity["display_name"] = identity["display_name"] or getattr(user, "username", None)
    return identity


def _demo_login_kind(username: str, display_name: str, user_type: str) -> Optional[str]:
    """Identify accounts created by the supported quick-login seed rules."""
    normalized_type = str(user_type or "").upper()
    username = str(username or "")
    display_name = str(display_name or "")
    if normalized_type == "EMPLOYEE":
        return "employee_named" if username and username == display_name else None
    if normalized_type == "CUSTOMER" and display_name:
        numbered_name = re.fullmatch(rf"{re.escape(display_name)}\d{{3}}", username)
        return "customer_numbered" if numbered_name else None
    return None


# =========================
# Auth Helpers
# =========================

def _get_current_user(credentials: HTTPAuthorizationCredentials):
    if not credentials:
        raise HTTPException(status_code=401, detail="缺少认证信息")
    user = AuthService.get_current_user(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账户已被禁用")
    return user


def _require_consistent_browser_session(user, access_token: Optional[str]):
    """Reject a browser session whose page cookie and API bearer disagree."""
    if not access_token:
        return user
    cookie_user = AuthService.get_current_user(access_token)
    if not cookie_user or getattr(cookie_user, "status", None) != "active":
        raise HTTPException(status_code=401, detail="页面登录状态已失效，请重新登录")
    if int(cookie_user.id) != int(user.id):
        raise HTTPException(status_code=401, detail="登录会话不一致，请重新登录")
    return user


def _require_permission(credentials: HTTPAuthorizationCredentials, permission: str):
    user = _get_current_user(credentials)
    ok, msg = AuthService.require_permission(user.id, permission, user.source_module)
    if not ok:
        raise HTTPException(status_code=403, detail=msg)
    return user


# =========================
# 基础认证
# =========================

@router.post("/register")
def register(req: RegisterRequest):
    ok, user, msg = AuthService.register(
        username=req.username,
        password=req.password,
        source_module=req.source_module,
        email=req.email,
        phone=req.phone,
        extra_data=req.extra_data,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    role_info = AuthService.get_user_role_info(user.id, user.source_module)
    return HttpResponse.ok(
        data={
            "id": user.id,
            "username": user.username,
            "source_module": user.source_module,
            "roles": role_info["role_names"],
            "permissions": role_info["permissions"],
        },
        msg="注册成功",
    )


@router.post("/login")
def login(req: LoginRequest, response: Response):
    login_username = req.username.strip()
    from app.Base.Models.userModel import UserModel
    if not UserModel.find_by_username(login_username):
        from app.Base.Client.mysqlClient import MySQLClient

        client = MySQLClient()
        try:
            aliases = client.execute_sync(
                "SELECT username FROM base_user WHERE status='active' AND deleted_at IS NULL "
                "AND source_module IN ('fin','WealthButler') AND ("
                "JSON_UNQUOTE(JSON_EXTRACT(extra_data, '$.display_name'))=%s OR "
                "JSON_UNQUOTE(JSON_EXTRACT(extra_data, '$.real_name'))=%s) LIMIT 2",
                (login_username, login_username),
            ) or []
        finally:
            client.close()
        if len(aliases) == 1:
            login_username = str(aliases[0]["username"])
        elif len(aliases) > 1:
            raise HTTPException(status_code=400, detail="该姓名对应多个账号，请使用完整用户名登录")
    ok, user, access_token, refresh_token, msg = AuthService.login(
        username=login_username, password=req.password,
    )
    if not ok:
        raise HTTPException(status_code=401, detail=msg)
    role_info = AuthService.get_user_role_info(user.id, user.source_module)
    identity = _user_identity(user)
    # Workbench HTML navigation cannot attach the frontend's Bearer header.
    # Keep the token in an HttpOnly cookie for server-side page authorization;
    # API clients may continue using the returned access_token as before.
    response.set_cookie(
        key="wealth_access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=3600,
        path="/",
    )
    return HttpResponse.ok(
        data={
            "id": user.id,
            "username": user.username,
            "source_module": user.source_module,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "roles": role_info["role_names"],
            "permissions": role_info["permissions"],
            "is_admin": role_info["is_admin"],
            **identity,
        },
        msg="登录成功",
    )


@router.get("/demo-accounts")
def demo_accounts():
    """从当前数据库读取可用于验收的测试账号摘要。

    只返回用户名和业务角色，不返回密码、手机号、邮箱或 extra_data，
    避免登录页继续依赖旧 SQL 种子里的 employee00x/customer000x 账号。
    """
    from app.Base.Client.mysqlClient import MySQLClient

    client = MySQLClient()
    rows = client.execute_sync(
        """
        SELECT id, username, user_type, employee_role, advisor_level,
               customer_level, extra_data
        FROM base_user
        WHERE status='active' AND deleted_at IS NULL
          AND source_module IN ('fin', 'WealthButler')
        ORDER BY CASE WHEN user_type IN ('EMPLOYEE', 'employee') THEN 1 ELSE 2 END,
                 CASE employee_role
                   WHEN '理财顾问' THEN 1
                   WHEN '风控专员' THEN 2
                   WHEN '客户经理' THEN 3
                   WHEN '业务管理员' THEN 4
                   ELSE 5 END,
                 id
        LIMIT 60
        """
    ) or []
    accounts = []
    for row in rows:
        extra = row.get("extra_data")
        if isinstance(extra, str):
            try:
                import json
                extra = json.loads(extra)
            except (TypeError, ValueError):
                extra = {}
        extra = extra if isinstance(extra, dict) else {}
        display_name = extra.get("display_name") or extra.get("real_name")
        display_name = display_name or row["username"]
        quick_login_kind = _demo_login_kind(
            row["username"], display_name, row.get("user_type")
        )
        if not quick_login_kind:
            continue
        role = row.get("employee_role") or ("客户" if row.get("user_type") == "CUSTOMER" else "员工")
        accounts.append({
            "id": int(row["id"]),
            "username": row["username"],
            "user_type": row.get("user_type"),
            "role": role,
            "display_name": display_name,
            "quick_login_kind": quick_login_kind,
            "advisor_level": row.get("advisor_level"),
            "customer_level": row.get("customer_level"),
        })
    client.close()
    return HttpResponse.ok(data={"accounts": accounts})


@router.post("/refresh")
def refresh(req: RefreshRequest, response: Response):
    ok, new_token, msg = AuthService.refresh_access_token(req.refresh_token)
    if not ok:
        raise HTTPException(status_code=401, detail=msg)
    # Keep server-authorized page navigation and bearer API calls on the same
    # refreshed identity.
    response.set_cookie(
        key="wealth_access_token",
        value=new_token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=3600,
        path="/",
    )
    return HttpResponse.ok(data={"access_token": new_token})


@router.post("/logout")
def logout(response: Response):
    """Clear the HttpOnly workbench cookie; the browser clears bearer state."""
    response.delete_cookie(
        key="wealth_access_token",
        path="/",
        samesite="lax",
        secure=False,
        httponly=True,
    )
    return HttpResponse.ok(msg="退出登录成功")


# =========================
# 用户信息 (需认证)
# =========================

@router.get("/me")
def get_me(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    access_token: Optional[str] = Cookie(None, alias="wealth_access_token"),
):
    user = _get_current_user(credentials)
    _require_consistent_browser_session(user, access_token)
    role_info = AuthService.get_user_role_info(user.id, user.source_module)
    identity = _user_identity(user)
    return HttpResponse.ok(data={
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "source_module": user.source_module,
        "status": user.status,
        "roles": role_info["role_names"],
        "permissions": role_info["permissions"],
        "is_admin": role_info["is_admin"],
        "is_super_admin": role_info["is_super_admin"],
        **identity,
        "last_login_at": str(user.last_login_at) if user.last_login_at else None,
        "created_at": str(user.created_at) if user.created_at else None,
    })


@router.put("/me")
def update_profile(req: UpdateProfileRequest, credentials: HTTPAuthorizationCredentials = Depends(security)):
    user = _get_current_user(credentials)
    ok, msg = AuthService.update_profile(user.id, req.email, req.phone, req.extra_data)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return HttpResponse.ok(msg="资料更新成功")


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, credentials: HTTPAuthorizationCredentials = Depends(security)):
    user = _get_current_user(credentials)
    msg = AuthService.change_password(user.id, req.old_password, req.new_password)
    if msg:
        raise HTTPException(status_code=400, detail=msg)
    return HttpResponse.ok(msg="密码修改成功")


@router.get("/me/menus")
def get_my_menus(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """获取当前用户可见的菜单树"""
    user = _get_current_user(credentials)
    role_info = AuthService.get_user_role_info(user.id, user.source_module)

    # 获取用户所有菜单
    all_menus = MenuModel.find_by_module(user.source_module)

    # 过滤：permission 为空 OR permission 在用户权限中
    user_permissions = set(role_info["permissions"])
    visible_menus = [
        menu for menu in all_menus
        if not menu.permission or menu.permission in user_permissions
    ]

    # 组装成树形结构
    tree = MenuModel.build_tree(visible_menus)
    return HttpResponse.ok(data={"menus": tree})


# =========================
# 用户管理 (需 user:manage)
# =========================

@router.get("/users")
def list_users(
    source_module: Optional[str] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    _require_permission(credentials, Permission.USER_MANAGE)
    users, total = AuthService.list_users(
        source_module=source_module, status=status, keyword=keyword, limit=limit, offset=offset,
    )
    return HttpResponse.ok(data={"users": users, "total": total, "limit": limit, "offset": offset})


@router.put("/users/status")
def update_user_status(req: UpdateStatusRequest, credentials: HTTPAuthorizationCredentials = Depends(security)):
    _require_permission(credentials, Permission.USER_MANAGE)
    ok = AuthService.update_user_status(req.user_id, req.status)
    if not ok:
        raise HTTPException(status_code=400, detail="更新失败")
    return HttpResponse.ok(msg=f"用户状态已更新为 {req.status}")


@router.post("/users/reset-password")
def reset_password(req: ResetPasswordRequest, credentials: HTTPAuthorizationCredentials = Depends(security)):
    _require_permission(credentials, Permission.USER_MANAGE)
    msg = AuthService.reset_password(req.user_id, req.new_password)
    if msg:
        raise HTTPException(status_code=400, detail=msg)
    return HttpResponse.ok(msg="密码已重置")


# =========================
# 角色管理 (需 role:manage)
# =========================

@router.get("/roles")
def list_roles(
    source_module: str = "default",
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """获取所有角色"""
    _get_current_user(credentials)
    roles = AuthService.list_roles(source_module)
    return HttpResponse.ok(data={"roles": roles})


@router.post("/roles")
def create_role(req: CreateRoleRequest, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """创建自定义角色"""
    user = _require_permission(credentials, Permission.ROLE_MANAGE)
    ok, msg = AuthService.create_role(
        operator_id=user.id,
        name=req.name,
        display_name=req.display_name,
        permissions=req.permissions,
        source_module=req.source_module,
        description=req.description,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return HttpResponse.ok(msg="角色创建成功")


@router.put("/roles/permissions")
def update_role_permissions(req: UpdateRolePermissionsRequest, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """更新角色权限"""
    user = _require_permission(credentials, Permission.ROLE_MANAGE)
    ok, msg = AuthService.update_role_permissions(
        operator_id=user.id,
        role_name=req.role_name,
        permissions=req.permissions,
        source_module=req.source_module,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return HttpResponse.ok(msg="角色权限已更新")


@router.get("/permissions")
def list_permissions(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """获取所有可用权限"""
    _get_current_user(credentials)
    return HttpResponse.ok(data={"permissions": AuthService.get_available_permissions()})


# ---------- 用户角色分配 ----------

@router.post("/roles/grant")
def grant_role(req: GrantRoleRequest, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """授予用户角色"""
    user = _require_permission(credentials, Permission.ROLE_MANAGE)
    ok, msg = AuthService.grant_role(
        operator_id=user.id,
        target_user_id=req.target_user_id,
        role_name=req.role_name,
        source_module=req.source_module,
        expires_at=req.expires_at,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return HttpResponse.ok(msg="角色授予成功")


@router.post("/roles/revoke")
def revoke_role(req: GrantRoleRequest, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """撤销用户角色"""
    user = _require_permission(credentials, Permission.ROLE_MANAGE)
    ok, msg = AuthService.revoke_role(
        operator_id=user.id,
        target_user_id=req.target_user_id,
        role_name=req.role_name,
        source_module=req.source_module,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return HttpResponse.ok(msg="角色已撤销")


@router.post("/roles/set")
def set_user_roles(req: SetUserRolesRequest, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """替换用户的全部角色"""
    user = _require_permission(credentials, Permission.ROLE_MANAGE)
    ok, msg = AuthService.set_user_roles(
        operator_id=user.id,
        target_user_id=req.target_user_id,
        role_names=req.role_names,
        source_module=req.source_module,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return HttpResponse.ok(msg="角色设置成功")


@router.get("/users/{user_id}/roles")
def get_user_roles(user_id: int, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """获取用户角色信息"""
    user = _get_current_user(credentials)
    if user.id != user_id:
        _require_permission(credentials, Permission.USER_READ)
    from app.Base.Models.userModel import UserModel
    target = UserModel.get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    role_info = AuthService.get_user_role_info(user_id, target.source_module)
    return HttpResponse.ok(data={"user_id": user_id, "username": target.username, **role_info})


# =========================
# 菜单管理 (需 system:config)
# =========================

@router.get("/menus")
def get_menus(
    source_module: str = "default",
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    _require_permission(credentials, Permission.SYSTEM_CONFIG)
    menus = MenuModel.find_by_module(source_module)
    tree = MenuModel.build_tree(menus)
    return HttpResponse.ok(data={"menus": tree})


@router.post("/menus")
def create_menu(
    req: CreateMenuRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    _require_permission(credentials, Permission.SYSTEM_CONFIG)
    menu = MenuModel(**req.model_dump())
    menu.save()
    return HttpResponse.ok(data={"id": menu.id}, msg="创建成功")


@router.put("/menus/sort")
def sort_menus(
    req: SortMenuRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    _require_permission(credentials, Permission.SYSTEM_CONFIG)
    for item in req.items:
        menu = MenuModel.find_by_id(item["id"])
        if menu:
            menu.update(sort_order=item["sort_order"])
    return HttpResponse.ok(msg="排序更新成功")


@router.put("/menus/{menu_id}")
def update_menu(
    menu_id: int,
    req: UpdateMenuRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    _require_permission(credentials, Permission.SYSTEM_CONFIG)
    menu = MenuModel.find_by_id(menu_id)
    if not menu:
        raise HTTPException(status_code=404, detail="菜单不存在")

    update_data = req.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(menu, key, value)
    menu.save()

    return HttpResponse.ok(msg="更新成功")


@router.delete("/menus/{menu_id}")
def delete_menu(
    menu_id: int,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    _require_permission(credentials, Permission.SYSTEM_CONFIG)
    deleted = MenuModel.delete_with_children(menu_id)
    return HttpResponse.ok(data={"deleted": deleted}, msg=f"已删除 {deleted} 条菜单")


# =========================
# 注册路由 + 页面
# =========================

def register_auth_router(app):
    app.include_router(router)

    @app.get("/auth-test", tags=["页面"])
    def auth_test_page():
        file = FRONTEND_DIR / "auth_verify.html"
        if file.exists():
            return FileResponse(str(file), media_type="text/html")
        return HTMLResponse("<h1>页面未找到</h1>", status_code=404)

    @app.get("/superpowers", tags=["页面"])
    def superpowers_page():
        file = FRONTEND_DIR / "superpowers.html"
        if file.exists():
            return FileResponse(str(file), media_type="text/html")
        return HTMLResponse("<h1>页面未找到</h1>", status_code=404)
