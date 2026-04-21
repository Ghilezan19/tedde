"""
Workflow service for camera recording + ALPR integration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import event_log
from camera.recording import RecordingManager, WorkflowSession
from config import settings
from services.alpr_service import ALPRService

logger = logging.getLogger(__name__)


class WorkflowMode(str, Enum):
    SIMPLE = "simple"


@dataclass
class WorkflowRun:
    session_id: str
    started_at: datetime


class WorkflowService:
    def __init__(
        self,
        recording_manager: RecordingManager,
        alpr_service: ALPRService,
    ) -> None:
        self._recording_manager = recording_manager
        self._alpr_service = alpr_service
        self._lock = asyncio.Lock()
        self._current_session: Optional[WorkflowSession] = None

    def is_busy(self) -> bool:
        return self._current_session is not None

    async def trigger(
        self,
        mode: WorkflowMode,
        duration: Optional[int] = None,
        source: str = "unknown",
    ) -> WorkflowRun:
        async with self._lock:
            if self._current_session is not None:
                raise RuntimeError("Workflow already active")

            session_id = uuid.uuid4().hex
            effective_duration = duration if duration is not None else settings.recording_duration_seconds

            event_log.banner(f"WORKFLOW START - source={source} duration={effective_duration}s")

            # Create event directory
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
            event_dir = Path(settings.events_dir) / f"EVENT_{timestamp}"
            event_dir.mkdir(parents=True, exist_ok=True)

            # Start recording on cameras
            cameras = [1, 2]  # Both cameras by default
            stream = settings.workflow_record_stream or "main"

            try:
                self._current_session = await self._recording_manager.start_workflow(
                    session_id=session_id,
                    event_dir=event_dir,
                    cameras=cameras,
                    stream=stream,
                    duration=effective_duration,
                )
            except Exception as exc:
                logger.error("[WORKFLOW] Failed to start recording: %s", exc)
                raise

            # ALPR snapshot if enabled
            if settings.alpr_enabled:
                try:
                    await self._run_alpr_snapshot(event_dir)
                except Exception as exc:
                    logger.warning("[WORKFLOW] ALPR snapshot failed: %s", exc)

            # Schedule automatic stop
            asyncio.create_task(self._auto_stop(effective_duration))

            return WorkflowRun(
                session_id=session_id,
                started_at=datetime.now(timezone.utc),
            )

    async def _run_alpr_snapshot(self, event_dir: Path) -> None:
        """Take snapshot from ALPR camera and run plate detection.

        Saves a structured JSON file (alpr.json) with `selected_plate`,
        `selected_confidence`, and all detected `plates` — the shape consumed by
        /api/events and the dashboard gallery.
        """
        from camera.media import save_snapshot

        camera_idx = settings.alpr_camera
        snapshot_path = event_dir / "alpr_start.jpg"
        try:
            await save_snapshot(camera=camera_idx, quality="main", filepath=snapshot_path)
        except Exception as exc:
            logger.warning("[WORKFLOW] ALPR snapshot capture failed: %s", exc)
            return

        if not snapshot_path.exists():
            return

        try:
            result = await self._alpr_service.predict_image(snapshot_path)
        except Exception as exc:
            logger.warning("[WORKFLOW] ALPR predict failed: %s", exc)
            result = {
                "enabled": True,
                "selected_plate": None,
                "selected_confidence": None,
                "plates": [],
                "error": str(exc)[:200],
            }

        alpr_json = event_dir / "alpr.json"
        try:
            alpr_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("[WORKFLOW] Cannot write alpr.json: %s", exc)

        plate = result.get("selected_plate")
        if plate:
            logger.info(
                "[WORKFLOW] ALPR detected plate=%s conf=%s",
                plate,
                result.get("selected_confidence"),
            )
        else:
            logger.info("[WORKFLOW] ALPR: no plate detected at start")

    async def _retry_alpr_at_end(self, event_dir: Path) -> None:
        """If start-ALPR found no plate, take an end-of-recording snapshot and retry.

        Overwrites alpr.json only on success (so we keep the best result).
        """
        from camera.media import save_snapshot

        alpr_json = event_dir / "alpr.json"
        existing_plate = None
        if alpr_json.exists():
            try:
                existing_plate = (json.loads(alpr_json.read_text(encoding="utf-8")) or {}).get("selected_plate")
            except Exception:
                pass
        if existing_plate:
            return

        end_snap = event_dir / "alpr_end.jpg"
        try:
            await save_snapshot(camera=settings.alpr_camera, quality="main", filepath=end_snap)
        except Exception as exc:
            logger.warning("[WORKFLOW] End snapshot failed: %s", exc)
            return
        if not end_snap.exists():
            return

        try:
            result = await self._alpr_service.predict_image(end_snap)
        except Exception as exc:
            logger.warning("[WORKFLOW] End ALPR predict failed: %s", exc)
            return

        if result.get("selected_plate"):
            try:
                alpr_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info("[WORKFLOW] ALPR end-retry succeeded: plate=%s", result["selected_plate"])
            except Exception as exc:
                logger.warning("[WORKFLOW] Cannot write alpr.json (retry): %s", exc)
        else:
            logger.info("[WORKFLOW] ALPR end-retry: still no plate")

    async def _auto_stop(self, duration_seconds: int) -> None:
        """Wait for duration then stop workflow."""
        await asyncio.sleep(duration_seconds)
        await self.stop()

    async def stop(self) -> Optional[WorkflowSession]:
        async with self._lock:
            if self._current_session is None:
                return None

            session = self._current_session
            self._current_session = None

            event_log.banner("WORKFLOW STOP")
            result = await self._recording_manager.stop_workflow()

            if result is not None:
                # Files are now closed by ffmpeg — safe to do ALPR retry + rename.
                if settings.alpr_enabled:
                    try:
                        await self._retry_alpr_at_end(result.event_dir)
                    except Exception as exc:
                        logger.warning("[WORKFLOW] End ALPR retry raised: %s", exc)
                try:
                    await asyncio.to_thread(self._finalize_event_sync, result)
                except Exception as exc:
                    logger.warning("[WORKFLOW] Finalize event failed: %s", exc)

            return result

    # Folder naming: EVENT_<timestamp>  →  EVENT_<timestamp>_<plate_or_fallback>
    # and per-camera files:   camera1.mp4 → <plate>_cam1.mp4 (idem cam2) so the filenames
    # themselves are self-describing in any download/backup.
    _PLATE_SANITIZE_RX = re.compile(r"[^A-Z0-9_-]+")

    def _finalize_event_sync(self, session: WorkflowSession) -> None:
        """Rename + concat bumpers for each camera file.

        Produces one self-contained MP4 per camera: intro + recording + outro,
        at 1280×720, muted, faststart-ed. Raw file is kept as `<plate>_cam{N}_raw.mp4`
        for debugging / admin download only.
        """
        event_dir = session.event_dir
        if not event_dir.exists():
            return

        plate = self._read_plate(event_dir)
        if not plate:
            # No detection → short stable random so every event has a unique human-readable tag
            plate = f"NOPLATE-{secrets.token_hex(2).upper()}"  # e.g. NOPLATE-A3F1

        # Move raw recordings aside (camera1.mp4 → <plate>_cam1_raw.mp4), then build
        # the final concat MP4 at <plate>_cam1.mp4.
        for cam in (1, 2):
            raw_src = event_dir / f"camera{cam}.mp4"
            if not raw_src.exists():
                continue
            raw_dst = event_dir / f"{plate}_cam{cam}_raw.mp4"
            final_dst = event_dir / f"{plate}_cam{cam}.mp4"
            try:
                raw_src.rename(raw_dst)
            except OSError as exc:
                logger.warning("[WORKFLOW] Rename raw for cam%d failed: %s", cam, exc)
                continue

            ok = self._concat_with_bumpers(raw_dst, final_dst)
            if not ok:
                # Fallback: use raw as the final so the portal still has something to play.
                try:
                    raw_dst.rename(final_dst)
                    logger.warning("[WORKFLOW] Concat failed for cam%d; using raw as final.", cam)
                except OSError as exc:
                    logger.warning("[WORKFLOW] Fallback rename for cam%d failed: %s", cam, exc)

        # Rename the event dir itself (append plate for easy scanning on disk)
        old_name = event_dir.name
        if old_name.startswith("EVENT_") and f"_{plate}" not in old_name:
            new_name = f"{old_name}_{plate}"
            new_dir = event_dir.parent / new_name
            if not new_dir.exists():
                try:
                    event_dir.rename(new_dir)
                    session.event_dir = new_dir
                    logger.info("[WORKFLOW] Event finalized: %s", new_name)
                except OSError as exc:
                    logger.warning("[WORKFLOW] Dir rename failed: %s", exc)

    def _resolve_bumper_path(self) -> Optional[Path]:
        """Resolve the intro/outro bumper to a local filesystem path.

        Accepts either an absolute filesystem path, or a URL path rooted at the
        app mount (e.g. `/public/intro-outro.mp4`). Returns None if missing.
        """
        raw = (settings.portal_bumper_video_url or "").strip()
        if not raw:
            return None
        if raw.startswith(("http://", "https://")):
            # Remote bumpers not pre-fetched here — skip concat gracefully.
            return None
        # Strip leading slash to resolve relative to repo root.
        rel = raw.lstrip("/")
        candidate = (Path(__file__).resolve().parent.parent.parent / rel).resolve()
        if candidate.is_file():
            return candidate
        # Also try py_backend-relative in case of path quirks.
        alt = (Path(__file__).resolve().parent.parent / rel).resolve()
        return alt if alt.is_file() else None

    def _concat_with_bumpers(self, raw_path: Path, final_path: Path) -> bool:
        """Re-encode intro + raw + outro into a single 720p muted MP4.

        Returns True on success. Uses concat filter so inputs don't need to share
        codec params. Keeps re-encode fast with ultrafast preset.
        """
        import subprocess

        bumper = self._resolve_bumper_path()
        # Target: 1280x720, 25fps, yuv420p, muted, faststart
        scale = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25,format=yuv420p"

        if bumper is not None:
            inputs = ["-i", str(bumper), "-i", str(raw_path), "-i", str(bumper)]
            filter_complex = (
                f"[0:v]{scale}[v0];"
                f"[1:v]{scale}[v1];"
                f"[2:v]{scale}[v2];"
                f"[v0][v1][v2]concat=n=3:v=1:a=0[outv]"
            )
        else:
            # No bumper → just re-scale/re-encode the raw clip for portal-friendly size.
            inputs = ["-i", str(raw_path)]
            filter_complex = f"[0:v]{scale}[outv]"

        args = [
            settings.ffmpeg_path,
            "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "24",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-an",
            "-f", "mp4",
            str(final_path),
        ]

        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            logger.warning("[WORKFLOW] ffmpeg concat timed out for %s", raw_path.name)
            return False
        except Exception as exc:
            logger.warning("[WORKFLOW] ffmpeg concat launch failed for %s: %s", raw_path.name, exc)
            return False

        if proc.returncode != 0:
            tail = (proc.stderr or "").splitlines()[-6:]
            logger.warning(
                "[WORKFLOW] ffmpeg concat rc=%s for %s — stderr tail: %s",
                proc.returncode,
                raw_path.name,
                " | ".join(tail),
            )
            return False

        if not final_path.exists() or final_path.stat().st_size < 8192:
            logger.warning("[WORKFLOW] concat produced empty/missing file: %s", final_path)
            return False

        logger.info(
            "[WORKFLOW] Concat OK: %s (%d KB)",
            final_path.name,
            final_path.stat().st_size // 1024,
        )
        return True

    def _read_plate(self, event_dir: Path) -> Optional[str]:
        alpr_json = event_dir / "alpr.json"
        if not alpr_json.exists():
            return None
        try:
            data = json.loads(alpr_json.read_text(encoding="utf-8")) or {}
        except Exception:
            return None
        raw = data.get("selected_plate")
        if not raw or not isinstance(raw, str):
            return None
        sanitized = self._PLATE_SANITIZE_RX.sub("", raw.upper())
        return sanitized or None

    def status(self) -> dict:
        if self._current_session is None:
            return {
                "active": False,
                "last_event": None,
            }

        wf_status = self._recording_manager.workflow_status()
        return {
            "active": True,
            "last_event": wf_status,
        }
