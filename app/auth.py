"""Authentication and authorization helpers."""

from starlette.requests import Request

from app.user_store import ROLE_ADMIN, ROLE_USER, authenticate_user

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

PUBLIC_PREFIXES = ("/static",)


def is_public_path(path: str) -> bool:
    """Return True when the request path can be used without login."""
    normalized_path = path.rstrip("/") or "/"
    if normalized_path in PUBLIC_PATHS:
        return True
    if "tplus/message/callback" in normalized_path:
        return True
    return any(normalized_path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def verify_login(username: str, password: str) -> dict | None:
    """Validate credentials and return the session-safe user object."""
    return authenticate_user(username, password)


def get_current_user(request: Request) -> dict | None:
    """Return the logged-in user object from session."""
    return request.session.get("user")


def is_admin(request: Request) -> bool:
    """Return True when the current user is an administrator."""
    user = get_current_user(request)
    return user is not None and user.get("role") == ROLE_ADMIN
