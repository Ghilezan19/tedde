"""
Configure API — read and write .env settings from the UI.

GET  /api/config        — return current .env values (passwords masked)
POST /api/config/save   — write new values to .env (creates .env.bak.{ts} backup first)
GET  /configure         — serve the Configure dashboard HTML page
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from config import settings
from debug_agent_log import agent_log
from services.auth_service import require_superadmin

router = APIRouter()
templates = Jinja2Templates(directory=str(settings.templates_dir_abs))

_ENV_FILE = Path(__file__).parent.parent.parent / ".env"

# Keys whose values are masked in the GET response
_SENSITIVE_KEYS = {
    "CAMERA_PASSWORD",
    "CAMERA2_PASSWORD",
    "ADMIN_PASSWORD",
    "SUPERADMIN_PASSWORD",
    "SESSION_SECRET_KEY",
    "SMS_HTTP_HEADERS_JSON",
    "SMS_GATEWAY_API_KEY",
}

# Keys that must NOT be written through this API
_READONLY_KEYS = {"SESSION_SECRET_KEY"}


def _read_env() -> dict[str, str]:
    """Parse .env into a key→value dict (skips comments and blanks)."""
    result: dict[str, str] = {}
    if not _ENV_FILE.exists():
        return result
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            result[key.strip()] = value.strip()
    return result


def _safe_env_for_templates(env: dict[str, str]) -> dict[str, str]:
    """
    Empty or invalid numeric .env values break Jinja (e.g. ``|float`` on Configure page).
    """
    e = dict(env)

    def _float_key(key: str, default: str) -> None:
        raw = (e.get(key) or "").strip().replace(",", ".")
        if not raw:
            e[key] = default
            return
        try:
            e[key] = str(float(raw))
        except ValueError:
            e[key] = default

    def _int_range(key: str, default: str, lo: int, hi: int) -> None:
        raw = (e.get(key) or "").strip().replace(",", ".")
        if not raw:
            e[key] = default
            return
        try:
            iv = int(float(raw))
            e[key] = str(max(lo, min(hi, iv)))
        except ValueError:
            e[key] = default

    _float_key("ALPR_DETECTOR_CONF_THRESH", "0.1")
    _float_key("ALPR_PREDICT_UPSCALE", "1.5")
    _int_range("RECORDING_DURATION_SECONDS", "60", 5, 600)
    return e


def _write_env(new_values: dict[str, str]) -> None:
    """
    Write (or update) keys in .env while preserving comments and ordering.
    Keys that don't exist yet are appended at the bottom.
    Creates a timestamped backup before writing.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = _ENV_FILE.parent / f".env.bak.{ts}"
    if _ENV_FILE.exists():
        shutil.copy2(_ENV_FILE, backup_path)

    existing_lines = _ENV_FILE.read_text(encoding="utf-8").splitlines() if _ENV_FILE.exists() else []
    written_keys: set[str] = set()
    output_lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            output_lines.append(line)
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in new_values and key not in _READONLY_KEYS:
                output_lines.append(f"{key}={new_values[key]}")
                written_keys.add(key)
                continue
        output_lines.append(line)

    # Append any keys not already in the file
    for key, value in new_values.items():
        if key not in written_keys and key not in _READONLY_KEYS:
            output_lines.append(f"{key}={value}")

    _ENV_FILE.write_text("\n".join(output_lines) + "\n", encoding="utf-8")


@router.get("/configure", response_class=HTMLResponse, include_in_schema=False)
async def configure_page(
    request: Request,
    role: str = Depends(require_superadmin),
) -> HTMLResponse:
    """Configure dashboard — requires superadmin role (exposed via public tunnel)."""
    # #region agent log
    agent_log(
        hypothesis_id="A",
        location="config_api.configure_page",
        message="enter",
        data={"env_file_exists": _ENV_FILE.exists()},
    )
    # #endregion
    env = _safe_env_for_templates(_read_env())
    # Mask sensitive values
    masked: dict[str, str] = {}
    for k, v in env.items():
        masked[k] = "••••••••" if k in _SENSITIVE_KEYS else v

    return templates.TemplateResponse(
        request,
        "configure.html",
        {"env": masked},
    )


@router.get("/api/config", summary="Read current .env settings")
async def get_config(
    role: str = Depends(require_superadmin),
) -> dict[str, Any]:
    """Return all .env key-value pairs with sensitive fields masked."""
    env = _read_env()
    masked: dict[str, str] = {}
    for k, v in env.items():
        masked[k] = "" if k in _SENSITIVE_KEYS else v
    return {"ok": True, "config": masked}


@router.post("/api/config/save", summary="Save settings to .env")
async def save_config(
    request: Request,
    role: str = Depends(require_superadmin),
) -> JSONResponse:
    """
    Accept a JSON body with key-value pairs and write them to .env.
    Readonly keys are silently ignored. Creates a .env.bak.{ts} backup.
    """
    body: dict[str, Any] = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(
            {"ok": False, "error": "Body must be a JSON object"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    new_values: dict[str, str] = {
        str(k).upper(): str(v)
        for k, v in body.items()
        if k and v is not None
    }

    # Remove readonly keys
    for k in _READONLY_KEYS:
        new_values.pop(k, None)

    _write_env(new_values)

    return JSONResponse({"ok": True, "saved": list(new_values.keys())})
