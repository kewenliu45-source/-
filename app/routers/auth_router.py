"""登录 / 退出路由。"""

import os

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import get_current_user, verify_login
from app.config import BASE_DIR

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "app", "templates"))


@router.get("/login")
def login_page(request: Request):
    """GET /login — 已登录则跳转首页，否则显示登录表单。"""
    user = get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={},
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """POST /login — 校验用户名密码。"""
    user = verify_login(username, password)
    if user:
        request.session["user"] = user
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "用户名或密码错误"},
    )


@router.get("/logout")
def logout(request: Request):
    """GET /logout — 清除登录态并跳转到登录页。"""
    request.session.pop("user", None)
    return RedirectResponse("/login", status_code=303)
