"""
Admin API routes.

All endpoints require admin or superadmin role cookie.

GET    /admin                            — Admin dashboard page
GET    /api/admin/stats                  — Daily summary stats
GET    /api/admin/vehicles               — Vehicle list with filters
DELETE /api/admin/events/{event_id}      — Delete an event folder + portal link
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import settings
from debug_agent_log import agent_log
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
    # #region agent log
    agent_log(
        hypothesis_id="D",
        location="admin_api.admin_page",
        message="render_admin",
        data={"role": role},
    )
    # #endregion
    return templates.TemplateResponse(
        request,
        "admin.html",
        {"role": role},
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


# ── Events list (filesystem events + customer_links merge) ────────

import re as _re

# Sufix opțional: plăcuță normală (TM99ABC) sau fallback workflow (NOPLATE-A3F1) — permite cratimă.
_EVENT_NAME_RE = _re.compile(r"^EVENT_(\d{4}-\d{2}-\d{2}T[\d-]+Z)(?:_([A-Za-z0-9-]+))?$")

# Threshold below which a recording is flagged as "incomplete" in the admin UI.
# Expressed as a fraction of `recording_duration_seconds`.
_INCOMPLETE_RECORDING_RATIO = 0.9


def _probe_video_duration(video_path: Path) -> float | None:
    """Return the duration (in seconds) of an MP4 file, or None on failure.

    Uses ffprobe directly. The result is cached in `<event_dir>/.durations.json`
    so we don't re-probe the same file on every admin page load.
    """
    if not video_path.is_file():
        return None
    cache = video_path.parent / ".durations.json"
    cached: dict = {}
    if cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8")) or {}
        except Exception:
            cached = {}
    key = video_path.name
    entry = cached.get(key)
    mtime = int(video_path.stat().st_mtime)
    if isinstance(entry, dict) and entry.get("mtime") == mtime:
        return float(entry.get("duration") or 0.0) or None

    import subprocess
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return None
        duration = float(proc.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None

    cached[key] = {"mtime": mtime, "duration": duration}
    try:
        cache.write_text(json.dumps(cached), encoding="utf-8")
    except Exception:
        pass
    return duration


def _load_events_page(
    events_dir: Path,
    portal,
    *,
    days: int,
    search: str,
    filter_: str,
    page: int,
    page_size: int,
) -> dict:
    """Scan filesystem events, merge with customer_links, return paginated dict."""
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)

    # Build event_id → customer_link map
    with portal._connect() as conn:
        rows = conn.execute(
            "SELECT cl.*, cf.rating_overall, cf.submitted_at AS feedback_submitted_at "
            "FROM customer_links cl "
            "LEFT JOIN customer_feedback cf ON cf.link_id = cl.id"
        ).fetchall()
    link_map: dict = {r["event_id"]: dict(r) for r in rows if r["event_id"]}

    # Collect events from filesystem
    events = []
    if events_dir.exists():
        for p in sorted(events_dir.iterdir(), reverse=True):
            if not p.is_dir() or p.name.startswith(".tmp_"):
                continue
            m = _EVENT_NAME_RE.match(p.name)
            if not m:
                continue
            ts_str = m.group(1)  # e.g. 2026-04-24T21-41-30Z
            try:
                # Parse timestamp: dashes used instead of colons
                ts = datetime.strptime(ts_str, "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if ts < cutoff_dt:
                continue

            plate_from_dir = m.group(2) or ""

            # Load ALPR data
            alpr_json = p / "alpr.json"
            plate = plate_from_dir
            confidence = None
            alpr_data: dict = {}
            if alpr_json.exists():
                try:
                    import json as _json
                    alpr_data = _json.loads(alpr_json.read_text(encoding="utf-8")) or {}
                    plate = alpr_data.get("selected_plate") or plate_from_dir
                    confidence = alpr_data.get("selected_confidence")
                except Exception:
                    pass

            event_id = p.name
            link = link_map.get(event_id, {})

            # Determine video files
            def _vid_path(cam: int) -> Path | None:
                for suffix in ("", "_raw"):
                    candidate = p / f"{plate}_cam{cam}{suffix}.mp4"
                    if candidate.exists():
                        return candidate
                plain = p / f"camera{cam}.mp4"
                if plain.exists():
                    return plain
                return None

            def _vid_url(cam: int) -> str | None:
                vp = _vid_path(cam)
                return f"/events/{event_id}/{vp.name}" if vp else None

            # Legacy single-shot snapshot for older events.
            snap = p / "alpr_start.jpg"
            snap_url = f"/events/{event_id}/alpr_start.jpg" if snap.exists() else None

            # Multi-shot samples — only those with a detected plate.
            alpr_samples = [
                {
                    "filename": s["filename"],
                    "url": f"/events/{event_id}/{s['filename']}",
                    "plate": s["plate"],
                    "confidence": s["confidence"],
                    "captured_at": s.get("captured_at"),
                }
                for s in alpr_data.get("samples", [])
                if s.get("plate") and s.get("filename")
            ]

            sms_status = link.get("sms_status", "pending")
            has_feedback = link.get("rating_overall") is not None

            # Per-camera durations (cached). Flag the event as incomplete if any
            # available video is shorter than 90% of the expected duration — that
            # usually means the ffmpeg process died mid-recording.
            expected_duration = settings.recording_duration_seconds
            min_acceptable = expected_duration * _INCOMPLETE_RECORDING_RATIO
            recording_warnings: list[str] = []
            durations: dict[int, float | None] = {}
            for cam in (1, 2):
                vp = _vid_path(cam)
                dur = _probe_video_duration(vp) if vp else None
                durations[cam] = dur
                if vp is None:
                    recording_warnings.append(f"Camera {cam}: fișier lipsă.")
                elif dur is not None and dur < min_acceptable:
                    recording_warnings.append(
                        f"Camera {cam}: înregistrare incompletă ({dur:.0f}s din ~{expected_duration}s)."
                    )

            entry = {
                "id": link.get("id", 0),
                "event_id": event_id,
                "license_plate": plate or "—",
                "owner_name": link.get("owner_name", ""),
                "phone_number_masked": "",
                "mechanic_name": link.get("mechanic_name"),
                "sms_status": sms_status,
                "has_feedback": has_feedback,
                "rating_overall": link.get("rating_overall"),
                "created_at": ts.isoformat(),
                "sent_at": link.get("sent_at"),
                "expires_at": link.get("expires_at"),
                "public_url": link.get("public_url"),
                "snapshot_url": snap_url,
                "video_cam1_url": _vid_url(1),
                "video_cam2_url": _vid_url(2),
                "video_cam1_duration_seconds": durations[1],
                "video_cam2_duration_seconds": durations[2],
                "expected_duration_seconds": expected_duration,
                "recording_warnings": recording_warnings,
                "alpr_confidence": confidence,
                "alpr_method": alpr_data.get("selected_method"),
                "alpr_samples": alpr_samples,
                "alpr_samples_total": alpr_data.get("samples_total", 0),
                "alpr_samples_with_plate": alpr_data.get("samples_with_plate", len(alpr_samples)),
                "has_link": bool(link),
            }
            phone = link.get("phone_number", "")
            if len(phone) > 4:
                entry["phone_number_masked"] = f"{phone[:4]}***{phone[-2:]}"
            events.append(entry)

    # Filter
    if search:
        s = search.lower()
        events = [e for e in events if s in (e["license_plate"] or "").lower()
                  or s in (e["owner_name"] or "").lower()]
    if filter_ == "sms_sent":
        events = [e for e in events if e["sms_status"] in ("sent", "mocked")]
    elif filter_ == "sms_pending":
        events = [e for e in events if e["sms_status"] not in ("sent", "mocked")]
    elif filter_ == "feedback":
        events = [e for e in events if e["has_feedback"]]
    elif filter_ == "no_feedback":
        events = [e for e in events if not e["has_feedback"]]

    total = len(events)
    offset = (page - 1) * page_size
    page_events = events[offset: offset + page_size]

    return {
        "vehicles": page_events,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "filter": filter_,
        "days": days,
        "search": search,
    }


@router.get("/api/admin/events-list", summary="All scanned events with ALPR + portal data")
async def admin_events_list(
    request: Request,
    _role: str = Depends(require_admin),
    filter: str = Query(default="all"),
    days: int = Query(default=7, ge=1, le=365),
    search: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=5, le=100),
) -> dict:
    portal = _get_portal_service(request)
    return await asyncio.to_thread(
        _load_events_page,
        settings.events_dir_abs,
        portal,
        days=days,
        search=search,
        filter_=filter,
        page=page,
        page_size=page_size,
    )


@router.delete("/api/admin/events/{event_id}", summary="Delete an event folder and associated portal link")
async def admin_delete_event(
    event_id: str,
    request: Request,
    _role: str = Depends(require_admin),
) -> dict:
    """
    Permanently deletes the event folder from disk and removes the associated
    customer_link row from the database (if one exists).
    """
    if not _EVENT_NAME_RE.match(event_id):
        raise HTTPException(status_code=400, detail="Invalid event_id format")

    event_dir = settings.events_dir_abs / event_id
    if not event_dir.exists():
        raise HTTPException(status_code=404, detail="Event not found")

    # Remove folder and all contents
    await asyncio.to_thread(shutil.rmtree, event_dir)
    logger.info("Deleted event folder: %s", event_dir)

    # Remove customer_link row if present
    portal = _get_portal_service(request)
    try:
        with portal._connect() as conn:
            conn.execute("DELETE FROM customer_links WHERE event_id = ?", (event_id,))
            conn.commit()
    except Exception as exc:
        logger.warning("Could not remove customer_link for %s: %s", event_id, exc)

    return {"deleted": event_id}


# ── Vehicle list (customer_links only — legacy) ────────────────────

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
