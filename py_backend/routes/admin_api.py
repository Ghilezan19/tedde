"""
Admin API routes.

All endpoints require admin or superadmin role cookie.

GET  /admin                            — Admin dashboard page
GET  /api/admin/stats                  — Daily summary stats
GET  /api/admin/vehicles               — Vehicle list with filters
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import settings
from services.auth_service import require_admin

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(settings.templates_dir_abs))


def _get_portal_service(request: Request):
    return request.app.state.customer_portal


# ── Dashboard page ────────────────────────────────────────────────

@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_page(
    request: Request,
    role: str = Depends(require_admin),
) -> HTMLResponse:
    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "role": role},
    )


# ── Stats ─────────────────────────────────────────────────────────

@router.get("/api/admin/stats", summary="Daily stats summary")
async def admin_stats(
    request: Request,
    _role: str = Depends(require_admin),
) -> dict:
    portal = _get_portal_service(request)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tokens = await asyncio.to_thread(portal.get_tokens_remaining)

    with portal._connect() as conn:
        # Today's vehicles (events with links)
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM customer_links WHERE created_at LIKE ?",
            (f"{today}%",),
        ).fetchone()
        today_count = row["cnt"] if row else 0

        # SMS sent today
        row2 = conn.execute(
            "SELECT COUNT(*) AS cnt FROM customer_links "
            "WHERE created_at LIKE ? AND sms_status IN ('sent','mocked')",
            (f"{today}%",),
        ).fetchone()
        sms_today = row2["cnt"] if row2 else 0

        # Feedback today
        row3 = conn.execute(
            "SELECT COUNT(*) AS cnt FROM customer_feedback cf "
            "JOIN customer_links cl ON cf.link_id = cl.id "
            "WHERE cl.created_at LIKE ?",
            (f"{today}%",),
        ).fetchone()
        feedback_today = row3["cnt"] if row3 else 0

        # Average rating (all time)
        row4 = conn.execute(
            "SELECT AVG(rating_overall) AS avg_rating FROM customer_feedback"
        ).fetchone()
        avg_rating = round(row4["avg_rating"], 1) if row4 and row4["avg_rating"] else None

    # Count today's filesystem events (may not all have links yet)
    events_dir = settings.events_dir_abs
    today_events = 0
    if events_dir.exists():
        start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        for p in events_dir.iterdir():
            if p.is_dir() and not p.name.startswith(".tmp_"):
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                if mtime >= start_of_day:
                    today_events += 1

    return {
        "today": today,
        "today_events": today_events,
        "today_links": today_count,
        "sms_sent_today": sms_today,
        "feedback_today": feedback_today,
        "avg_rating": avg_rating,
        "tokens_remaining": tokens,
    }


# ── Vehicle list ──────────────────────────────────────────────────

@router.get("/api/admin/vehicles", summary="Vehicle list with filters")
async def admin_vehicles(
    request: Request,
    _role: str = Depends(require_admin),
    filter: str = Query(default="all", description="all|sms_sent|sms_pending|feedback|no_feedback"),
    days: int = Query(default=7, ge=1, le=365),
    search: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=5, le=100),
) -> dict:
    portal = _get_portal_service(request)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with portal._connect() as conn:
        # Base query
        query = """
            SELECT
                cl.id, cl.event_id, cl.license_plate, cl.owner_name,
                cl.mechanic_name, cl.phone_number, cl.sms_status,
                cl.created_at, cl.sent_at, cl.expires_at, cl.public_url,
                cf.rating_overall, cf.rating_explanation, cf.free_text,
                cf.submitted_at AS feedback_submitted_at
            FROM customer_links cl
            LEFT JOIN customer_feedback cf ON cf.link_id = cl.id
            WHERE cl.created_at >= ?
        """
        params: list = [cutoff]

        if filter == "sms_sent":
            query += " AND cl.sms_status IN ('sent','mocked')"
        elif filter == "sms_pending":
            query += " AND cl.sms_status NOT IN ('sent','mocked')"
        elif filter == "feedback":
            query += " AND cf.id IS NOT NULL"
        elif filter == "no_feedback":
            query += " AND cf.id IS NULL"

        if search:
            query += " AND (cl.license_plate LIKE ? OR cl.owner_name LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])

        query += " ORDER BY cl.created_at DESC"

        # Total count
        count_query = f"SELECT COUNT(*) AS cnt FROM ({query})"
        total_row = conn.execute(count_query, params).fetchone()
        total = total_row["cnt"] if total_row else 0

        # Paginated results
        offset = (page - 1) * page_size
        query += f" LIMIT {page_size} OFFSET {offset}"
        rows = conn.execute(query, params).fetchall()

    vehicles = []
    for row in rows:
        vehicle = dict(row)
        # Mask phone number
        phone = vehicle.get("phone_number", "")
        if len(phone) > 4:
            vehicle["phone_number_masked"] = f"{phone[:4]}***{phone[-2:]}"
        else:
            vehicle["phone_number_masked"] = "****"

        # Load event snapshot url
        event_id = vehicle.get("event_id", "")
        snapshot_path = settings.events_dir_abs / event_id / "alpr_start.jpg"
        vehicle["snapshot_url"] = f"/events/{event_id}/alpr_start.jpg" if snapshot_path.exists() else None

        # Feedback
        vehicle["has_feedback"] = vehicle.get("rating_overall") is not None
        vehicle["sms_sent"] = vehicle.get("sms_status") in ("sent", "mocked")

        vehicles.append(vehicle)

    return {
        "vehicles": vehicles,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "filter": filter,
        "days": days,
        "search": search,
    }
