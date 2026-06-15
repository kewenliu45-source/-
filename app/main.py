import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.auth import is_public_path, get_current_user
from app.config import SESSION_SECRET_KEY
from app.routers import auth_router, page_router, tplus_oauth_router, upload_router

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(_BASE_DIR, "static")

app = FastAPI(title="智能库存预警系统")

# ---------- 登录拦截中间件 ----------
# 注意中间件执行顺序：后添加的 middleware 先执行（在外层）。
# AuthMiddleware 先添加（内层），SessionMiddleware 后添加（外层），
# 这样请求先经过 SessionMiddleware 初始化 session，再进入 AuthMiddleware 判断登录态。
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # 公开路径直接放行
        if is_public_path(path):
            return await call_next(request)
        # 已登录用户放行
        if get_current_user(request) is not None:
            return await call_next(request)
        # 未登录 → 重定向到登录页
        return RedirectResponse("/login", status_code=303)


app.add_middleware(AuthMiddleware)

# ---------- Session 中间件（后添加 → 外层 → 先执行）----------
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/CHANJET_CHECK.txt", include_in_schema=False)
def chanjet_check_file():
    return FileResponse(os.path.join(_STATIC_DIR, "CHANJET_CHECK.txt"), media_type="text/plain")

app.include_router(auth_router.router)
app.include_router(page_router.router)
app.include_router(upload_router.router)
app.include_router(tplus_oauth_router.router)
