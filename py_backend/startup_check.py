"""
Startup health probes — run once at boot, logged to console.

Checks:
  1. ffmpeg binary exists and is executable
  2. Camera 1  — TCP connect on RTSP port
  3. Camera 2  — TCP connect on RTSP port + HTTP port
  4. Snapshot, recordings, events, and data folders are writable

Results are stored in a module-level dict so GET /api/health can return them
without re-running the probes on every request.
"""

import asyncio
import logging
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Module-level result cache (populated by run_all())
# ------------------------------------------------------------------ #

_results: dict[str, Any] = {}


def get_results() -> dict:
    """Return the last startup probe results (empty if not yet run)."""
    return dict(_results)


# ------------------------------------------------------------------ #
# Individual probes
# ------------------------------------------------------------------ #

def _probe_ffmpeg() -> dict:
    """Check ffmpeg binary exists and return its version string."""
    path = settings.ffmpeg_path
    if not shutil.which(path) and not Path(path).is_file():
        return {"ok": False, "detail": f"Not found: {path}"}
    try:
        result = subprocess.run(
            [path, "-version"],
            capture_output=True, text=True, timeout=5
        )
        first_line = (result.stdout or result.stderr or "").splitlines()[0]
        return {"ok": True, "detail": first_line.strip(), "path": path}
    except Exception as exc:
        return {"ok": False, "detail": str(exc), "path": path}


async def _probe_tcp(host: str, port: int, timeout: float = 3.0) -> dict:
    """Try opening a TCP socket to host:port.  Returns ok + latency_ms."""
    t0 = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        ms = round((time.monotonic() - t0) * 1000)
        return {"ok": True, "detail": f"reachable ({ms} ms)", "latency_ms": ms}
    except asyncio.TimeoutError:
        return {"ok": False, "detail": f"timeout after {timeout:.0f}s"}
    except OSError as exc:
        return {"ok": False, "detail": str(exc)}


def _probe_writable_dir(path: Path, pattern: str) -> dict:
    """Check that a directory exists and is writable, plus a quick file count."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        test = path / ".write_test"
        test.write_text("ok")
        test.unlink()
        existing = len(list(path.glob(pattern)))
        return {"ok": True, "detail": str(path), "count": existing}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


# ------------------------------------------------------------------ #
# Main probe runner
# ------------------------------------------------------------------ #

async def run_all() -> dict:
    """
    Run all probes, log a summary table, and cache the results.
    Returns the results dict.
    """
    global _results

    logger.info("=" * 60)
    logger.info("  STARTUP HEALTH CHECK")
    logger.info("=" * 60)

    results: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # --- ffmpeg ---
    ffmpeg = _probe_ffmpeg()
    results["ffmpeg"] = ffmpeg
    _log_probe("ffmpeg", ffmpeg)

    # --- Camera 1 RTSP ---
    cam1_rtsp = await _probe_tcp(settings.camera_ip, settings.camera_rtsp_port)
    results["camera1_rtsp"] = {
        "ip": settings.camera_ip, "port": settings.camera_rtsp_port, **cam1_rtsp
    }
    _log_probe(
        f"Camera 1 RTSP  {settings.camera_ip}:{settings.camera_rtsp_port}", cam1_rtsp
    )

    # --- Camera 2 RTSP ---
    cam2_rtsp = await _probe_tcp(settings.camera2_ip, settings.camera2_rtsp_port)
    results["camera2_rtsp"] = {
        "ip": settings.camera2_ip, "port": settings.camera2_rtsp_port, **cam2_rtsp
    }
    _log_probe(
        f"Camera 2 RTSP  {settings.camera2_ip}:{settings.camera2_rtsp_port}", cam2_rtsp
    )

    # --- Camera 2 HTTP (ONVIF / ISAPI) ---
    cam2_http = await _probe_tcp(settings.camera2_ip, settings.camera2_http_port)
    results["camera2_http"] = {
        "ip": settings.camera2_ip, "port": settings.camera2_http_port, **cam2_http
    }
    _log_probe(
        f"Camera 2 HTTP  {settings.camera2_ip}:{settings.camera2_http_port}", cam2_http
    )

    # --- Writable directories ---
    snapshots = _probe_writable_dir(settings.snapshot_dir_abs, "*")
    results["snapshots_dir"] = snapshots
    _log_probe("Snapshots dir", snapshots)

    rec = _probe_writable_dir(settings.recordings_dir_abs, "*.mp4")
    results["recordings_dir"] = rec
    _log_probe("Recordings dir", rec)

    events = _probe_writable_dir(settings.events_dir_abs, "*")
    results["events_dir"] = events
    _log_probe("Events dir", events)

    data_dir = _probe_writable_dir(settings.customer_portal_db_abs.parent, "*")
    results["data_dir"] = data_dir
    _log_probe("Data dir", data_dir)

    # --- Overall ---
    critical_ok = ffmpeg["ok"] and rec["ok"] and snapshots["ok"] and events["ok"] and data_dir["ok"]
    cameras_ok = cam1_rtsp["ok"] or cam2_rtsp["ok"]
    results["overall"] = "ok" if (critical_ok and cameras_ok) else (
        "degraded" if critical_ok else "error"
    )

    logger.info("-" * 60)
    _results = results

    if results["overall"] == "ok":
        logger.info("  ✓ All systems nominal")
    elif results["overall"] == "degraded":
        logger.warning("  ⚠ Cameras unreachable — start server anyway (they may connect later)")
    else:
        logger.error("  ✗ Critical failure (ffmpeg or writable output dirs)")

    logger.info("=" * 60)
    return results


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _log_probe(label: str, result: dict) -> None:
    icon = "✓" if result["ok"] else "✗"
    status = "OK" if result["ok"] else "FAIL"
    detail = result.get("detail", "")
    if result["ok"]:
        logger.info("  %s  %-40s %s  %s", icon, label, status, detail)
    else:
        logger.warning("  %s  %-40s %s  %s", icon, label, status, detail)
