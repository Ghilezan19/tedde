"""
Auto-cleanup service.

Deletes events, snapshots, recordings, and SQLite rows older than `cleanup_days`.
Runs as a background asyncio task every hour while the server is running.
Can also be triggered manually via the super-admin API.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import settings

if TYPE_CHECKING:
    from services.customer_portal import CustomerPortalService

logger = logging.getLogger(__name__)

_CLEANUP_INTERVAL_SECONDS = 3600  # 1 hour


async def run_cleanup(portal: "CustomerPortalService", cleanup_days: int) -> dict[str, Any]:
    """
    Delete files and DB rows older than `cleanup_days`.
    Returns a log dict with statistics.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=cleanup_days)
    cutoff_ts = cutoff.timestamp()
    cutoff_iso = cutoff.isoformat()

    log: dict[str, Any] = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "cleanup_days": cleanup_days,
        "cutoff": cutoff_iso,
        "files_deleted": 0,
        "dirs_deleted": 0,
        "bytes_freed": 0,
        "db_rows_deleted": 0,
        "errors": [],
    }

    # 1. Filesystem cleanup
    for dir_path in (settings.events_dir_abs, settings.snapshot_dir_abs, settings.recordings_dir_abs):
        if not dir_path.exists():
            continue
        for item in list(dir_path.iterdir()):
            try:
                mtime = item.stat().st_mtime
                if mtime >= cutoff_ts:
                    continue  # Recent, keep it
                if item.is_dir():
                    size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                    shutil.rmtree(item)
                    log["dirs_deleted"] += 1
                    log["bytes_freed"] += size
                    logger.info("[CLEANUP] Deleted dir: %s (%.1f KB)", item.name, size / 1024)
                elif item.is_file():
                    size = item.stat().st_size
                    item.unlink()
                    log["files_deleted"] += 1
                    log["bytes_freed"] += size
                    logger.info("[CLEANUP] Deleted file: %s (%.1f KB)", item.name, size / 1024)
            except Exception as exc:
                err = f"Failed to delete {item}: {exc}"
                log["errors"].append(err)
                logger.warning("[CLEANUP] %s", err)

    # 2. SQLite cleanup (customer_feedback cascades via FK)
    try:
        def _db_cleanup() -> int:
            with portal._connect() as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                result = conn.execute(
                    "DELETE FROM customer_links WHERE created_at < ?",
                    (cutoff_iso,),
                )
                deleted = result.rowcount
                conn.commit()
            return deleted

        db_deleted = await asyncio.to_thread(_db_cleanup)
        log["db_rows_deleted"] = db_deleted
        if db_deleted:
            logger.info("[CLEANUP] Deleted %d DB rows older than %d days", db_deleted, cleanup_days)
    except Exception as exc:
        err = f"DB cleanup failed: {exc}"
        log["errors"].append(err)
        logger.warning("[CLEANUP] %s", err)

    mb_freed = log["bytes_freed"] / 1024 / 1024
    logger.info(
        "[CLEANUP] Done: %d dirs, %d files deleted, %.1f MB freed, %d DB rows",
        log["dirs_deleted"],
        log["files_deleted"],
        mb_freed,
        log["db_rows_deleted"],
    )
    return log


async def cleanup_loop(portal: "CustomerPortalService") -> None:
    """
    Background task: run cleanup every hour if auto_cleanup_enabled=1.
    """
    logger.info("[CLEANUP] Background loop started (interval=%ds)", _CLEANUP_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        try:
            enabled = portal.get_config_value("auto_cleanup_enabled", "1") == "1"
            if not enabled:
                logger.debug("[CLEANUP] Auto-cleanup disabled, skipping")
                continue
            cleanup_days = int(portal.get_config_value("cleanup_days", "30"))
            await run_cleanup(portal, cleanup_days)
        except asyncio.CancelledError:
            logger.info("[CLEANUP] Background loop cancelled")
            raise
        except Exception as exc:
            logger.error("[CLEANUP] Unexpected error in loop: %s", exc)
