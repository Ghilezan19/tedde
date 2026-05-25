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
from camera.ptz import PTZClient
from camera.recording import RecordingManager, WorkflowSession
from config import settings
from services.alpr_service import ALPRService
from services.customer_portal import CustomerPortalService

logger = logging.getLogger(__name__)


class WorkflowMode(str, Enum):
    SIMPLE = "simple"


@dataclass
class WorkflowRun:
    session_id: str
    started_at: datetime


def _select_winning_plate(
    samples: list[dict],
) -> tuple[Optional[str], Optional[float], str]:
    """Pick winning plate by frequency first, then by sum_confidence as tiebreaker.

    Only samples with confidence >= alpr_min_confidence are considered.
    Returns (plate, avg_confidence, method).
    """
    counts: dict[str, list[float]] = {}
    for s in samples:
        plate = s.get("plate")
        conf = float(s.get("confidence", 0.0))
        if plate and conf >= float(settings.alpr_min_confidence):
            counts.setdefault(plate, []).append(conf)
    if not counts:
        return None, None, "none"
    ranked = sorted(
        counts.items(),
        key=lambda kv: (len(kv[1]), sum(kv[1])),
        reverse=True,
    )
    winner_plate, confidences = ranked[0]
    method = "frequency" if len(confidences) > 1 else "confidence"
    return winner_plate, round(sum(confidences) / len(confidences), 1), method


class WorkflowService:
    def __init__(
        self,
        recording_manager: RecordingManager,
        alpr_service: ALPRService,
        ptz_client: Optional[PTZClient] = None,
        customer_portal: Optional[CustomerPortalService] = None,
    ) -> None:
        self._recording_manager = recording_manager
        self._alpr_service = alpr_service
        self._ptz = ptz_client
        self._portal = customer_portal
        self._lock = asyncio.Lock()
        self._current_session: Optional[WorkflowSession] = None
        self._ptz_running: bool = False
        self._alpr_stop_event: Optional[asyncio.Event] = None
        self._alpr_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    def is_busy(self) -> bool:
        return self._current_session is not None or self._ptz_running

    async def trigger(
        self,
        mode: WorkflowMode,
        duration: Optional[int] = None,
        source: str = "unknown",
    ) -> WorkflowRun:
        """
        Unified workflow trigger:
        - Both cameras start recording for `recording_duration_seconds` (default 600s).
        - PTZ runs in parallel: starts at "Piese" preset; after `ptz_home_recording_seconds`
          (default 60s) moves to "Masina". Cameras are NOT touched by PTZ motion.
        - ALPR loop runs in parallel using sub-stream snapshots (no main-stream conflict).
        """
        async with self._lock:
            if self._current_session is not None:
                raise RuntimeError("Workflow already active")

            session_id = uuid.uuid4().hex
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
            event_dir = Path(settings.events_dir) / f"EVENT_{timestamp}"
            event_dir.mkdir(parents=True, exist_ok=True)

            effective_duration = duration if duration is not None else settings.recording_duration_seconds
            event_log.banner(f"WORKFLOW START - source={source} duration={effective_duration}s")
            stream = settings.workflow_record_stream or "main"

            try:
                self._current_session = await self._recording_manager.start_workflow(
                    session_id=session_id,
                    event_dir=event_dir,
                    cameras=[1, 2],
                    stream=stream,
                    duration=effective_duration,
                )
            except Exception as exc:
                logger.error("[WORKFLOW] Failed to start recording: %s", exc)
                raise

            if self._ptz is not None:
                asyncio.create_task(self._run_ptz_motion())

            if settings.alpr_enabled:
                self._alpr_stop_event = asyncio.Event()
                self._alpr_task = asyncio.create_task(
                    self._alpr_loop(event_dir, self._alpr_stop_event)
                )

            asyncio.create_task(self._auto_stop(effective_duration))

            return WorkflowRun(
                session_id=session_id,
                started_at=datetime.now(timezone.utc),
            )

    async def _run_ptz_motion(self) -> None:
        """Move PTZ in parallel with recording. Does NOT touch the recording session.

        Sequence:
          t=0:  goto "Piese" preset
          t=ptz_home_recording_seconds: goto "Masina" preset
        The cameras keep recording continuously throughout.
        """
        if not self._ptz:
            return
        try:
            if settings.ptz_preset_home:
                logger.info("[WORKFLOW/PTZ] goto Piese (token=%s)", settings.ptz_preset_home)
                try:
                    await self._ptz.goto_preset(settings.ptz_preset_home)
                except Exception as exc:
                    logger.warning("[WORKFLOW/PTZ] goto Piese failed: %s", exc)

            home_dur = max(0, int(settings.ptz_home_recording_seconds))
            if home_dur > 0:
                await asyncio.sleep(home_dur)

            if settings.ptz_preset_secondary:
                logger.info("[WORKFLOW/PTZ] goto Masina (token=%s)", settings.ptz_preset_secondary)
                try:
                    await self._ptz.goto_preset(settings.ptz_preset_secondary)
                except Exception as exc:
                    logger.warning("[WORKFLOW/PTZ] goto Masina failed: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[WORKFLOW/PTZ] motion task error: %s", exc)

    async def _alpr_loop(self, event_dir: Path, stop_event: asyncio.Event) -> None:
        """Background task: take ALPR snapshots every alpr_interval_seconds until stopped.

        Runs in parallel with recording. On each tick:
        - Captures a JPEG snapshot from the ALPR camera.
        - Runs plate detection. If a plate is found (confidence >= alpr_min_confidence),
          saves the image as alpr_NNN.jpg and appends the sample.
        - Blank snapshots are counted but not saved to disk.
        At the end (when stop_event fires), aggregates all samples, picks the winner
        by frequency + confidence, and writes alpr.json.
        """
        from camera.media import capture_snapshot_bytes

        interval = settings.alpr_interval_seconds
        camera_idx = settings.alpr_camera
        snapshot_stream = "sub" if settings.alpr_snapshot_stream == "sub" else "main"
        start_delay = max(0, int(settings.alpr_start_delay_seconds))
        samples: list[dict] = []
        sample_index = 0
        samples_total = 0

        logger.info(
            "[WORKFLOW/ALPR-LOOP] started — interval=%ds delay=%ds camera=%d stream=%s event=%s",
            interval,
            start_delay,
            camera_idx,
            snapshot_stream,
            event_dir.name,
        )

        # Initial delay (e.g. wait for PTZ to reach the "Masina" preset before
        # taking snapshots). After that, fires every `interval` seconds.
        first_wait = start_delay if start_delay > 0 else interval
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=first_wait)
        except asyncio.TimeoutError:
            pass

        while not stop_event.is_set():
            sample_index += 1
            samples_total += 1
            captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            try:
                img_bytes = await capture_snapshot_bytes(camera=camera_idx, quality=snapshot_stream)
            except Exception as exc:
                logger.warning("[WORKFLOW/ALPR-LOOP] snapshot #%d failed: %s", sample_index, exc)
            else:
                try:
                    # Predict on in-memory bytes via a temp file to avoid disk clutter for blanks.
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                        tmp.write(img_bytes)
                        tmp_path = Path(tmp.name)
                    try:
                        result = await self._alpr_service.predict_image(tmp_path)
                    finally:
                        tmp_path.unlink(missing_ok=True)

                    plate = result.get("selected_plate")
                    confidence = float(result.get("selected_confidence") or 0.0)
                    all_plates = result.get("plates", [])

                    if plate and confidence >= float(settings.alpr_min_confidence):
                        filename = f"alpr_{sample_index:03d}.jpg"
                        snap_path = event_dir / filename
                        try:
                            snap_path.write_bytes(img_bytes)
                        except Exception as exc:
                            logger.warning("[WORKFLOW/ALPR-LOOP] save snapshot failed: %s", exc)
                            filename = None  # type: ignore[assignment]

                        samples.append({
                            "index": sample_index,
                            "filename": filename,
                            "captured_at": captured_at,
                            "plate": plate,
                            "confidence": confidence,
                            "all_plates": all_plates,
                        })
                        logger.info(
                            "[WORKFLOW/ALPR-LOOP] #%d plate=%s conf=%.1f",
                            sample_index,
                            plate,
                            confidence,
                        )
                    else:
                        logger.debug(
                            "[WORKFLOW/ALPR-LOOP] #%d no plate (conf=%.1f)",
                            sample_index,
                            confidence,
                        )

                except Exception as exc:
                    logger.warning("[WORKFLOW/ALPR-LOOP] predict #%d failed: %s", sample_index, exc)

            # Wait for next tick or until stopped.
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

        # --- Aggregation ---
        winner_plate, winner_conf, method = _select_winning_plate(samples)
        alpr_json_data = {
            "enabled": True,
            "selected_plate": winner_plate,
            "selected_confidence": winner_conf,
            "selected_method": method,
            "samples": samples,
            "samples_total": samples_total,
            "samples_with_plate": len(samples),
        }

        alpr_json = event_dir / "alpr.json"
        try:
            alpr_json.write_text(
                json.dumps(alpr_json_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(
                "[WORKFLOW/ALPR-LOOP] done — plate=%s method=%s samples=%d/%d",
                winner_plate,
                method,
                len(samples),
                samples_total,
            )
        except Exception as exc:
            logger.warning("[WORKFLOW/ALPR-LOOP] cannot write alpr.json: %s", exc)

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
                # Stop the ALPR loop and wait for aggregation before rename.
                if self._alpr_stop_event is not None:
                    self._alpr_stop_event.set()
                if self._alpr_task is not None:
                    try:
                        await asyncio.wait_for(self._alpr_task, timeout=30)
                    except asyncio.TimeoutError:
                        logger.warning("[WORKFLOW] ALPR loop did not finish in 30s — continuing")
                    except Exception as exc:
                        logger.warning("[WORKFLOW] ALPR loop raised: %s", exc)
                    self._alpr_task = None
                self._alpr_stop_event = None

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

        # Ample headroom: a 600s HD recording can take several minutes to re-encode
        # even with ultrafast presets. 900s (15 min) is enough for 10-min sources at
        # ≈1.5x realtime worst case while still avoiding indefinite hangs.
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=900,
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
