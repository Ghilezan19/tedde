"""
SMS gateway test page + proxy.

Targets a simple gateway like:
    POST {base}/send-sms   body: {"apiKey": "...", "phone": "...", "message": "..."}
    GET  {base}/health

The API key stays on the server — the browser only hits our proxy endpoints.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from config import settings
from services.auth_service import require_superadmin

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(settings.templates_dir_abs))

_HTTP_TIMEOUT_SEC = 10.0


def _gateway_url() -> str:
    url = (settings.sms_gateway_url or "").rstrip("/")
    if not url:
        raise HTTPException(
            status_code=503,
            detail="SMS_GATEWAY_URL nu este configurat în .env",
        )
    return url


class SendSmsBody(BaseModel):
    phone: str = Field(min_length=1, description="Numărul de telefon destinație")
    message: str = Field(min_length=1, description="Conținutul mesajului SMS")


@router.get("/sms-test", response_class=HTMLResponse, include_in_schema=False)
async def sms_test_page(
    request: Request,
    role: str = Depends(require_superadmin),
) -> HTMLResponse:
    """Render the SMS gateway test UI."""
    return templates.TemplateResponse(
        request,
        "sms_test.html",
        {
            "gateway_url": settings.sms_gateway_url or "",
            "api_key_configured": bool(settings.sms_gateway_api_key),
        },
    )


@router.get("/api/sms-gateway/health", summary="Proxy GET {gateway}/health")
async def sms_gateway_health(
    role: str = Depends(require_superadmin),
) -> dict[str, Any]:
    """Probe the SMS gateway /health endpoint."""
    url = _gateway_url() + "/health"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC) as client:
            response = await client.get(url)
    except httpx.RequestError as exc:
        return {
            "ok": False,
            "url": url,
            "error": f"Conexiune eșuată: {exc.__class__.__name__}: {exc}",
        }

    # Best-effort JSON parse; fall back to text
    try:
        body: Any = response.json()
    except Exception:
        body = response.text

    return {
        "ok": 200 <= response.status_code < 300,
        "url": url,
        "http_status": response.status_code,
        "body": body,
    }


@router.post("/api/sms-gateway/send", summary="Proxy POST {gateway}/send-sms")
async def sms_gateway_send(
    payload: SendSmsBody,
    role: str = Depends(require_superadmin),
) -> dict[str, Any]:
    """Forward a send-sms request to the configured gateway.

    API key is injected server-side (never exposed to the browser).
    """
    if not settings.sms_gateway_api_key:
        raise HTTPException(
            status_code=503,
            detail="SMS_GATEWAY_API_KEY nu este configurat în .env",
        )

    url = _gateway_url() + "/send-sms"
    body = {
        "apiKey": settings.sms_gateway_api_key,
        "phone": payload.phone.strip(),
        "message": payload.message,
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC) as client:
            response = await client.post(url, json=body)
    except httpx.RequestError as exc:
        logger.warning("[SMS-GW] request failed: %s", exc)
        return {
            "ok": False,
            "url": url,
            "error": f"Conexiune eșuată: {exc.__class__.__name__}: {exc}",
            "sent": {"phone": body["phone"], "message_length": len(body["message"])},
        }

    try:
        response_body: Any = response.json()
    except Exception:
        response_body = response.text

    logger.info(
        "[SMS-GW] sent phone=%s status=%s len=%d",
        body["phone"][:4] + "****",
        response.status_code,
        len(body["message"]),
    )

    return {
        "ok": 200 <= response.status_code < 300,
        "url": url,
        "http_status": response.status_code,
        "body": response_body,
        "sent": {"phone": body["phone"], "message_length": len(body["message"])},
    }
