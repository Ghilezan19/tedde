"""
Authentication routes for admin dashboards.

GET  /login          — Login page (Jinja2 template)
POST /login          — Validate password, set signed cookie, redirect
GET  /logout         — Clear session cookie, redirect to /login
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import settings
from services.auth_service import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    create_session_cookie,
    get_current_role,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(settings.templates_dir_abs))


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request, next: str = "/admin") -> HTMLResponse:
    role = get_current_role(request)
    if role == "superadmin":
        return RedirectResponse(url="/super-admin", status_code=status.HTTP_302_FOUND)
    if role == "admin":
        return RedirectResponse(url=next or "/admin", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "next": next, "error": None},
    )


@router.post("/login", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def login_submit(
    request: Request,
    password: str = Form(...),
    next: str = Form(default="/admin"),
) -> RedirectResponse | HTMLResponse:
    if password == settings.superadmin_password:
        role = "superadmin"
        redirect_to = "/super-admin"
    elif password == settings.admin_password:
        role = "admin"
        redirect_to = next if next and next.startswith("/") else "/admin"
    else:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "next": next, "error": "Parolă incorectă."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    cookie_value = create_session_cookie(role)  # type: ignore[arg-type]
    response = RedirectResponse(url=redirect_to, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie_value,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout", include_in_schema=False)
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
