"""
Session cookie authentication for admin dashboards.

Uses itsdangerous.TimestampSigner to sign cookie values.
Cookie format: "role:admin" or "role:superadmin", signed + timestamped.
Max age: 8 hours (28800 seconds).
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import Cookie, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from config import settings

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "tedde_session"
SESSION_MAX_AGE = 28800  # 8 hours

Role = Literal["admin", "superadmin"]


def _get_signer() -> TimestampSigner:
    return TimestampSigner(settings.session_secret_key)


def create_session_cookie(role: Role) -> str:
    """Sign and return a cookie value for the given role."""
    signer = _get_signer()
    return signer.sign(f"role:{role}").decode("utf-8")


def verify_session_cookie(cookie_value: str | None) -> Role | None:
    """
    Verify a signed session cookie.
    Returns the role string if valid, None otherwise.
    """
    if not cookie_value:
        return None
    signer = _get_signer()
    try:
        raw = signer.unsign(cookie_value, max_age=SESSION_MAX_AGE)
        value = raw.decode("utf-8")
        if value == "role:admin":
            return "admin"
        if value == "role:superadmin":
            return "superadmin"
        return None
    except (SignatureExpired, BadSignature):
        return None


def get_current_role(request: Request) -> Role | None:
    """Extract and verify the role from the request cookie."""
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    return verify_session_cookie(cookie_value)


def require_admin(request: Request) -> Role:
    """
    FastAPI dependency: require admin or superadmin role.
    Redirects to /login on failure.
    """
    role = get_current_role(request)
    if role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/login?next={request.url.path}"},
        )
    return role


def require_superadmin(request: Request) -> Role:
    """
    FastAPI dependency: require exactly superadmin role.
    Redirects to /login on failure (anonymous).
    Admin sessions go to /admin in one hop (avoids /login?next=/super-admin loops).
    """
    role = get_current_role(request)
    if role == "superadmin":
        return role
    if role == "admin":
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/admin"},
        )
    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": f"/login?next={request.url.path}"},
    )
