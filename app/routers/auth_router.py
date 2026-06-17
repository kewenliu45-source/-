"""Login, logout, and admin user management routes."""

import logging
import os

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import ROLE_ADMIN, ROLE_USER, get_current_user, is_admin, verify_login
from app.config import BASE_DIR
from app.user_store import (
    create_user,
    delete_user,
    list_users,
    set_user_active,
    update_user_password,
    update_user_role,
)

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "app", "templates"))


@router.get("/login")
def login_page(request: Request):
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
    user = verify_login(username, password)
    if user:
        request.session.clear()
        request.session["user"] = user
        logger.info("login success: username=%s role=%s", user["username"], user["role"])
        return RedirectResponse("/", status_code=303)

    logger.warning("login failed: username=%s", username)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "用户名或密码错误", "username": username},
    )


@router.get("/logout")
def logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse("/login", status_code=303)


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    current_user = get_current_user(request)
    if not is_admin(request):
        return HTMLResponse("Forbidden", status_code=403)

    return templates.TemplateResponse(
        request=request,
        name="users.html",
        context={
            "current_user": current_user,
            "users": list_users(),
            "roles": [ROLE_ADMIN, ROLE_USER],
        },
    )


@router.post("/users", response_class=HTMLResponse)
def create_user_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    current_user = get_current_user(request)
    if not is_admin(request):
        return HTMLResponse("Forbidden", status_code=403)

    try:
        create_user(username=username, password=password, role=role)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="users.html",
            context={
                "current_user": current_user,
                "users": list_users(),
                "roles": [ROLE_ADMIN, ROLE_USER],
                "error": str(exc),
                "form": {"username": username, "role": role},
            },
            status_code=400,
        )

    logger.info(
        "user created: username=%s role=%s by=%s",
        username,
        role,
        current_user["username"] if current_user else "",
    )
    return RedirectResponse("/users?created=1", status_code=303)


def _redirect_users(msg: str, status: str = "ok") -> RedirectResponse:
    return RedirectResponse(f"/users?{status}={msg}", status_code=303)


def _users_page_with_error(request: Request, error: str):
    current_user = get_current_user(request)
    return templates.TemplateResponse(
        request=request,
        name="users.html",
        context={
            "current_user": current_user,
            "users": list_users(),
            "roles": [ROLE_ADMIN, ROLE_USER],
            "error": error,
        },
        status_code=400,
    )


@router.post("/users/{username}/role")
def change_user_role(request: Request, username: str, role: str = Form(...)):
    if not is_admin(request):
        return HTMLResponse("Forbidden", status_code=403)
    try:
        update_user_role(username, role)
    except ValueError as exc:
        return _users_page_with_error(request, str(exc))
    logger.info("role changed: username=%s role=%s by=%s", username, role, get_current_user(request)["username"])
    return _redirect_users("role updated")


@router.post("/users/{username}/password")
def change_user_password(request: Request, username: str, password: str = Form(...)):
    if not is_admin(request):
        return HTMLResponse("Forbidden", status_code=403)
    try:
        update_user_password(username, password)
    except ValueError as exc:
        return _users_page_with_error(request, str(exc))
    logger.info("password changed: username=%s by=%s", username, get_current_user(request)["username"])
    return _redirect_users("password updated")


@router.post("/users/{username}/active")
def toggle_user_active(request: Request, username: str, is_active: str = Form(...)):
    if not is_admin(request):
        return HTMLResponse("Forbidden", status_code=403)
    active = is_active == "1"
    try:
        set_user_active(username, active)
    except ValueError as exc:
        return _users_page_with_error(request, str(exc))
    action = "enabled" if active else "disabled"
    logger.info("user %s: username=%s by=%s", action, username, get_current_user(request)["username"])
    return _redirect_users(action)


@router.post("/users/{username}/delete")
def delete_user_route(request: Request, username: str):
    if not is_admin(request):
        return HTMLResponse("Forbidden", status_code=403)
    try:
        delete_user(username)
    except ValueError as exc:
        return _users_page_with_error(request, str(exc))
    logger.info("user deleted: username=%s by=%s", username, get_current_user(request)["username"])
    return _redirect_users("deleted")
