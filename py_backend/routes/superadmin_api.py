"""
Super-Admin API routes.

All endpoints require superadmin role cookie.

GET  /super-admin                      — Super-admin dashboard page
GET  /api/superadmin/tokens            — Current token count + monthly stats
PATCH /api/superadmin/tokens           — Set token count
GET  /api/superadmin/events-by-day     — All events grouped by day (with SMS/feedback status)
POST /api/superadmin/clear-all         — Delete all data (requires confirm body)
POST /api/superadmin/cleanup-now       — Run cleanup manually
GET  /api/superadmin/cleanup-log       — Last cleanup log
PATCH /api/superadmin/cleanup-config   — Update cleanup_days and auto_cleanup_enabled
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

import startup_check
from config import settings
from debug_agent_log import agent_log
from services.auth_service import require_superadmin

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(settings.templates_dir_abs))

# In-memory cleanup log
_last_cleanup_log: dict[str, Any] = {}


def _get_portal_service(request: Request):
    return request.app.state.customer_portal


# ── Dashboard page ────────────────────────────────────────────────

@router.get("/super-admin", response_class=HTMLResponse, include_in_schema=False)
async def superadmin_page(
    request: Request,
    role: str = Depends(require_superadmin),
) -> HTMLResponse:
    # #region agent log
    agent_log(
        hypothesis_id="D",
        location="superadmin_api.superadmin_page",
        message="render_superadmin",
        data={"role": role},
    )
    # #endregion
    return templates.TemplateResponse(
        request,
        "superadmin.html",
        {"role": role},
    )


# ── Tokens ───────────────────────────────────────────────────────

@router.get("/api/superadmin/tokens", summary="Get token count and monthly stats")
async def get_tokens(
    request: Request,
    _role: str = Depends(require_superadmin),
) -> dict:
    portal = _get_portal_service(request)
    remaining = await asyncio.to_thread(portal.get_tokens_remaining)

    # Monthly processed count
    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    with portal._connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM customer_links WHERE created_at LIKE ?",
            (f"{this_month}%",),
        ).fetchone()
        monthly_count = row["cnt"] if row else 0

        row2 = conn.execute("SELECT COUNT(*) as cnt FROM customer_links").fetchone()
        total_count = row2["cnt"] if row2 else 0

    return {
        "tokens_remaining": remaining,
        "monthly_processed": monthly_count,
        "total_processed": total_count,
        "month": this_month,
    }


@router.patch("/api/superadmin/tokens", summary="Set token count")
async def set_tokens(
    request: Request,
    _role: str = Depends(require_superadmin),
) -> dict:
    body = await request.json()
    count = body.get("tokens_remaining")
    if count is None or not isinstance(count, int) or count < 0:
        raise HTTPException(status_code=400, detail="tokens_remaining must be a non-negative integer")

    portal = _get_portal_service(request)
    await asyncio.to_thread(portal.set_tokens_remaining, count)
    return {"ok": True, "tokens_remaining": count}


# ── Events by day ──────────────────────────────────────────���──────

@router.get("/api/superadmin/events-by-day", summary="All events grouped by day")
async def events_by_day(
    request: Request,
    _role: str = Depends(require_superadmin),
) -> dict:
    portal = _get_portal_service(request)

    # Build event list from filesystem
    events_dir = settings.events_dir_abs
    event_dirs = sorted(
        [p for p in events_dir.iterdir() if p.is_dir() and not p.name.startswith(".tmp_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    # Fetch all customer_links for cross-reference
    with portal._connect() as conn:
        link_rows = conn.execute(
            "SELECT cl.event_id, cl.sms_status, cl.sent_at, cf.submitted_at AS feedback_at, "
            "cl.license_plate, cl.owner_name, cl.mechanic_name, cl.phone_number, cl.id, cl.public_url "
            "FROM customer_links cl "
            "LEFT JOIN customer_feedback cf ON cf.link_id = cl.id"
        ).fetchall()

    # Build lookup: event_id → link info
    links_by_event: dict[str, list[dict]] = {}
    for row in link_rows:
        ev_id = row["event_id"]
        links_by_event.setdefault(ev_id, []).append(dict(row))

    # Group events by date
    by_day: dict[str, list[dict]] = {}
    for path in event_dirs:
        mtime = path.stat().st_mtime
        day = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")

        # Read alpr.json if present
        alpr_json = path / "alpr.json"
        plate = "UNKNOWN"
        event_time = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        if alpr_json.exists():
            try:
                alpr_data = json.loads(alpr_json.read_text(encoding="utf-8"))
                plate = alpr_data.get("selected_plate") or "UNKNOWN"
                if alpr_data.get("timestamp"):
                    event_time = alpr_data["timestamp"]
            except Exception:
                pass

        ev_links = links_by_event.get(path.name, [])
        sms_status = ev_links[0]["sms_status"] if ev_links else None
        sms_sent = sms_status in ("sent", "mocked")
        feedback_done = any(lnk.get("feedback_at") for lnk in ev_links)

        item = {
            "event_id": path.name,
            "plate": plate,
            "time": event_time,
            "sms_status": sms_status,
            "sms_sent": sms_sent,
            "feedback_done": feedback_done,
            "has_link": bool(ev_links),
            "snapshot_url": f"/events/{path.name}/alpr_start.jpg" if (path / "alpr_start.jpg").exists() else None,
        }
        by_day.setdefault(day, []).append(item)

    # Sort days descending
    sorted_days = sorted(by_day.keys(), reverse=True)
    result = [{"day": day, "events": by_day[day]} for day in sorted_days]
    return {"days": result, "total_events": len(event_dirs)}


# ── Clear all ─────────────────────────────────────────────────────

@router.post("/api/superadmin/clear-all", summary="Delete ALL data")
async def clear_all(
    request: Request,
    _role: str = Depends(require_superadmin),
) -> JSONResponse:
    body = await request.json()
    if body.get("confirm") != "DELETE_ALL":
        raise HTTPException(
            status_code=400,
            detail='Confirmation required: set {"confirm": "DELETE_ALL"}',
        )

    portal = _get_portal_service(request)
    deleted = {"sqlite_rows": 0, "files": 0, "dirs": 0, "bytes": 0}

    # 1. Clear SQLite (keep tables, delete rows)
    with portal._connect() as conn:
        r1 = conn.execute("DELETE FROM customer_feedback")
        r2 = conn.execute("DELETE FROM customer_links")
        deleted["sqlite_rows"] = r1.rowcount + r2.rowcount
        conn.commit()

    # 2. Clear filesystem directories
    for dir_path in (settings.events_dir_abs, settings.snapshot_dir_abs, settings.recordings_dir_abs):
        if not dir_path.exists():
            continue
        for item in list(dir_path.iterdir()):
            try:
                if item.is_dir():
                    size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                    shutil.rmtree(item)
                    deleted["dirs"] += 1
                    deleted["bytes"] += size
                elif item.is_file():
                    size = item.stat().st_size
                    item.unlink()
                    deleted["files"] += 1
                    deleted["bytes"] += size
            except Exception as e:
                logger.warning("[CLEAR-ALL] Failed to delete %s: %s", item, e)

    logger.info("[CLEAR-ALL] Deleted %s", deleted)
    return JSONResponse({"ok": True, "deleted": deleted})


# ── Manual cleanup ────────────────────────────────────────────────

@router.post("/api/superadmin/cleanup-now", summary="Run cleanup manually")
async def cleanup_now(
    request: Request,
    _role: str = Depends(require_superadmin),
) -> dict:
    portal = _get_portal_service(request)
    cleanup_days = int(portal.get_config_value("cleanup_days", "30"))

    from services.cleanup_service import run_cleanup
    log = await run_cleanup(portal, cleanup_days)
    return {"ok": True, "log": log}


@router.get("/api/superadmin/cleanup-log", summary="Get last cleanup log")
async def cleanup_log(
    _role: str = Depends(require_superadmin),
) -> dict:
    return {"log": _last_cleanup_log}


# ── Cleanup config ────────────────────────────────────────────────

@router.get("/api/superadmin/cleanup-config-get", summary="Get cleanup settings")
async def get_cleanup_config(
    request: Request,
    _role: str = Depends(require_superadmin),
) -> dict:
    portal = _get_portal_service(request)
    return {
        "cleanup_days": int(portal.get_config_value("cleanup_days", "30")),
        "auto_cleanup_enabled": portal.get_config_value("auto_cleanup_enabled", "1") == "1",
    }


@router.patch("/api/superadmin/cleanup-config", summary="Update cleanup settings")
async def update_cleanup_config(
    request: Request,
    _role: str = Depends(require_superadmin),
) -> dict:
    body = await request.json()
    portal = _get_portal_service(request)

    if "cleanup_days" in body:
        days = int(body["cleanup_days"])
        if days < 1:
            raise HTTPException(status_code=400, detail="cleanup_days must be >= 1")
        await asyncio.to_thread(portal.set_config_value, "cleanup_days", str(days))

    if "auto_cleanup_enabled" in body:
        val = "1" if body["auto_cleanup_enabled"] else "0"
        await asyncio.to_thread(portal.set_config_value, "auto_cleanup_enabled", val)

    return {
        "ok": True,
        "cleanup_days": int(portal.get_config_value("cleanup_days", "30")),
        "auto_cleanup_enabled": portal.get_config_value("auto_cleanup_enabled", "1") == "1",
    }


# ── System health (for dashboard) ────────────────────────────────

@router.get("/api/superadmin/health", summary="Get system health + uptime")
async def superadmin_health(
    _role: str = Depends(require_superadmin),
) -> dict:
    health = startup_check.get_results()
    return {
        "health": health,
        "server_started_at": health.get("started_at"),
    }
