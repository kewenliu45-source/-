"""认证与授权工具模块。

当前使用 .env 中的固定账号，后续可替换为数据库用户表。
"""

import hmac

from starlette.requests import Request

from app.config import ADMIN_PASSWORD, ADMIN_USERNAME, USER_PASSWORD, USER_USERNAME

# ---------- 角色常量 ----------
ROLE_ADMIN = "admin"
ROLE_USER = "user"

# ---------- 放行路径 ----------
PUBLIC_PATHS = {
    "/login",
    "/logout",
    "/CHANJET_CHECK.txt",
    "/tplus/message/callback",
    "/tplus/oauth/callback",
    "/docs",
    "/openapi.json",
    "/redoc",
}

# 放行路径前缀
PUBLIC_PREFIXES = ("/static",)


def is_public_path(path: str) -> bool:
    """判断请求路径是否属于公开路径（无需登录）。"""
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def verify_login(username: str, password: str) -> dict | None:
    """校验用户名密码，返回用户对象或 None。

    使用 hmac.compare_digest 进行安全比较。
    """
    # 校验管理员账号
    if hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(
        password, ADMIN_PASSWORD
    ):
        return {"username": username, "role": ROLE_ADMIN}

    # 校验普通用户账号
    if hmac.compare_digest(username, USER_USERNAME) and hmac.compare_digest(
        password, USER_PASSWORD
    ):
        return {"username": username, "role": ROLE_USER}

    return None


def get_current_user(request: Request) -> dict | None:
    """从 session 中获取当前登录用户，未登录返回 None。"""
    return request.session.get("user")


def is_admin(request: Request) -> bool:
    """判断当前用户是否为管理员。"""
    user = get_current_user(request)
    return user is not None and user.get("role") == ROLE_ADMIN
