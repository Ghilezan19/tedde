"""
Session-oriented recording manager using ffmpeg subprocesses.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from camera.rtsp import build_rtsp_url
from config import settings

logger = logging.getLogger(__name__)

# After sending "q" to ffmpeg stdin, muxing moov (+faststart) can take longer than a few seconds.
_FFMPEG_Q_WAIT_SEC = 90.0
_FFMPEG_TERM_WAIT_SEC = 15.0

# MP4 smaller than this after stop is treated as failed capture (truncated header / empty).
MIN_WORKFLOW_MP4_BYTES = 8192

# How many recent ffmpeg stderr lines to keep per recording (for journal on exit / early death).
_STDERR_TAIL_MAX = 40

# Redact user:password@ in URLs before writing to logs.
_RTSP_CREDS_RE = re.compile(r"([a-zA-Z0-9_.-]+):([^@/\s]+)@")


def _sanitize_log_line(text: str) -> str:
    """Strip RTSP credentials from a log line so journalctl does not leak passwords."""
    return _RTSP_CREDS_RE.sub(r"\1:***@", text)


def _append_stderr_tail(meta: "RecordingMeta", line: str) -> None:
    meta.stderr_tail.append(_sanitize_log_line(line))
    if len(meta.stderr_tail) > _STDERR_TAIL_MAX:
        meta.stderr_tail[:] = meta.stderr_tail[-_STDERR_TAIL_MAX:]


def resolve_camera_file(event_dir: Path, cam: int) -> Path | None:
    """Return the mp4 path for this camera, supporting legacy and plate-prefixed naming.

    Legacy: camera{N}.mp4  (pre-ALPR-finalize)
    New:    <plate>_cam{N}.mp4 (after workflow finalize renames)
    """
    legacy = event_dir / f"camera{cam}.mp4"
    if legacy.is_file():
        return legacy
    matches = sorted(
        event_dir.glob(f"*_cam{cam}.mp4"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def workflow_output_status(
    event_dir: Path, *, expected_cameras: tuple[int, ...] = (1, 2)
) -> tuple[dict[str, bool], list[str]]:
    """Which camera files are usable; Romanian warnings for operator/portal."""
    out: dict[str, bool] = {}
    warnings: list[str] = []
    for cam in expected_cameras:
        key = f"camera{cam}"
        path = resolve_camera_file(event_dir, cam)
        if path is not None and path.is_file():
            sz = path.stat().st_size
            ok = sz >= MIN_WORKFLOW_MP4_BYTES
            out[key] = ok
            if not ok:
                warnings.append(f"Camera {cam}: fișier prea mic sau gol ({sz} B).")
        else:
            out[key] = False
            warnings.append(f"Camera {cam}: fișier lipsă sau înregistrare eșuată.")
    return out, warnings


@dataclass
class RecordingMeta:
    filename: str
    filepath: Path
    camera: int
    stream: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    #: Last `_STDERR_TAIL_MAX` stderr lines from this ffmpeg process (sanitized).
    stderr_tail: list[str] = field(default_factory=list)


@dataclass
class _RecordingProcess:
    meta: RecordingMeta
    process: asyncio.subprocess.Process


@dataclass
class WorkflowSession:
    session_id: str
    started_at: datetime
    duration_seconds: int
    event_dir: Path
    recordings: dict[int, _RecordingProcess]
    planned_cameras: list[int] = field(default_factory=list)
    spawn_failed_cameras: list[int] = field(default_factory=list)
    # Cameras whose ffmpeg process exited before the planned duration. Filled
    # by the watchdog task and surfaced in workflow_status / admin payloads.
    died_cameras: list[int] = field(default_factory=list)


class RecordingManager:
    def __init__(self) -> None:
        self._manual: Optional[_RecordingProcess] = None
        self._manual_stop_task: Optional[asyncio.Task] = None
        self._workflow: Optional[WorkflowSession] = None
        self._lock = asyncio.Lock()

    async def start_manual(
        self,
        camera: int = 1,
        stream: str = "main",
        duration: Optional[int] = None,
    ) -> RecordingMeta:
        async with self._lock:
            if self._workflow is not None:
                raise RuntimeError("Workflow active. Manual recording is unavailable.")
            if self._manual is not None:
                raise RuntimeError("A recording is already in progress.")

            filename = self._build_timestamped_name(camera)
            filepath = settings.recordings_dir_abs / filename
            rec = await self._spawn_recording(filepath=filepath, camera=camera, stream=stream)
            self._manual = rec

            if duration:
                self._manual_stop_task = asyncio.create_task(self._auto_stop_manual(duration))

            logger.info("[RECORD] Manual started: %s", filename)
            return rec.meta

    async def stop_manual(self) -> Optional[RecordingMeta]:
        async with self._lock:
            if self._manual is None:
                return None

            if self._manual_stop_task and not self._manual_stop_task.done():
                self._manual_stop_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._manual_stop_task
            self._manual_stop_task = None

            rec = self._manual
            self._manual = None
            return await self._stop_recording(rec)

    def manual_status(self) -> dict:
        if self._manual is None:
            return {"recording": False}
        meta = self._manual.meta
        elapsed = int((datetime.now(timezone.utc) - meta.started_at).total_seconds())
        return {
            "recording": True,
            "filename": meta.filename,
            "camera": meta.camera,
            "stream": meta.stream,
            "startedAt": meta.started_at.isoformat(),
            "duration": elapsed,
        }

    async def start_workflow(
        self,
        *,
        session_id: str,
        event_dir: Path,
        cameras: list[int],
        stream: str,
        duration: int,
    ) -> WorkflowSession:
        async with self._lock:
            if self._manual is not None:
                raise RuntimeError("Manual recording active. Workflow cannot start.")
            if self._workflow is not None:
                raise RuntimeError("A workflow is already running.")

            event_dir.mkdir(parents=True, exist_ok=True)
            recordings: dict[int, _RecordingProcess] = {}
            spawn_failed: list[int] = []
            for camera in cameras:
                filepath = event_dir / f"camera{camera}.mp4"
                try:
                    recordings[camera] = await self._spawn_recording(
                        filepath=filepath,
                        camera=camera,
                        stream=stream,
                    )
                except Exception:
                    logger.exception("[RECORD] Failed to start ffmpeg for camera %s", camera)
                    spawn_failed.append(camera)
                    with contextlib.suppress(Exception):
                        if filepath.exists():
                            filepath.unlink()

            if not recordings:
                raise RuntimeError("No camera recording could be started (all cameras failed).")

            self._workflow = WorkflowSession(
                session_id=session_id,
                started_at=datetime.now(timezone.utc),
                duration_seconds=duration,
                event_dir=event_dir,
                recordings=recordings,
                planned_cameras=list(cameras),
                spawn_failed_cameras=spawn_failed,
            )
            for camera, rec in recordings.items():
                asyncio.create_task(self._watchdog_recording(rec, duration))
            logger.info("[RECORD] Workflow started: %s", session_id)
            return self._workflow

    async def add_camera_to_workflow(self, camera: int, stream: str) -> None:
        """Add a camera to an already-running workflow session (e.g. cam1 joins at Masina phase)."""
        async with self._lock:
            if self._workflow is None:
                raise RuntimeError("No active workflow to add camera to.")
            if camera in self._workflow.recordings:
                logger.warning("[RECORD] Camera %d already recording in workflow", camera)
                return
            filepath = self._workflow.event_dir / f"camera{camera}.mp4"
            try:
                rec = await self._spawn_recording(
                    filepath=filepath,
                    camera=camera,
                    stream=stream,
                )
                self._workflow.recordings[camera] = rec
                # Remaining duration for this camera = full duration minus elapsed.
                elapsed = int((datetime.now(timezone.utc) - self._workflow.started_at).total_seconds())
                remaining = max(0, self._workflow.duration_seconds - elapsed)
                asyncio.create_task(self._watchdog_recording(rec, remaining))
                logger.info("[RECORD] Camera %d added to workflow %s", camera, self._workflow.session_id)
            except Exception:
                logger.exception("[RECORD] Failed to add camera %d to workflow", camera)
                raise

    async def stop_workflow(self) -> Optional[WorkflowSession]:
        async with self._lock:
            if self._workflow is None:
                return None

            workflow = self._workflow
            self._workflow = None
            for camera in sorted(workflow.recordings):
                await self._stop_recording(workflow.recordings[camera])
            logger.info("[RECORD] Workflow stopped: %s", workflow.session_id)
            return workflow

    def workflow_status(self) -> dict:
        if self._workflow is None:
            return {"recording": False}
        elapsed = int((datetime.now(timezone.utc) - self._workflow.started_at).total_seconds())
        wf = self._workflow
        return {
            "recording": True,
            "sessionId": wf.session_id,
            "startedAt": wf.started_at.isoformat(),
            "durationSeconds": wf.duration_seconds,
            "elapsedSeconds": elapsed,
            "eventDir": str(wf.event_dir),
            "cameras": sorted(wf.recordings.keys()),
            "plannedCameras": list(wf.planned_cameras),
            "spawnFailedCameras": list(wf.spawn_failed_cameras),
            "diedCameras": list(wf.died_cameras),
        }

    def update_workflow_event_dir(self, event_dir: Path) -> None:
        """Keep per-camera paths in sync after temp dir rename (otherwise stat/stop order breaks)."""
        if self._workflow is not None:
            self._workflow.event_dir = event_dir
            for rec in self._workflow.recordings.values():
                rec.meta.filepath = event_dir / rec.meta.filename

    def workflow_active(self) -> bool:
        return self._workflow is not None

    def any_active(self) -> bool:
        return self._manual is not None or self._workflow is not None

    async def stop_all(self) -> None:
        await self.stop_manual()
        await self.stop_workflow()

    async def _spawn_recording(self, filepath: Path, camera: int, stream: str) -> _RecordingProcess:
        rtsp_url = build_rtsp_url(camera=camera, stream=stream)
        meta = RecordingMeta(
            filename=filepath.name,
            filepath=filepath,
            camera=camera,
            stream=stream,
        )
        args = [
            settings.ffmpeg_path,
            # ── Input flags: regenerate timestamps from the wallclock instead of
            #    trusting the RTSP stream's PTS (fixes the 30h "ghost" duration
            #    produced by some Hikvision/HiLook substreams / PTZ with bad PTS).
            "-fflags", "+genpts+discardcorrupt",
            "-use_wallclock_as_timestamps", "1",
            "-rtsp_transport", "tcp",
            # Socket I/O timeout (µs): 60s. In ffmpeg 6.x the older `-stimeout`
            # CLI flag was removed; `-timeout` is now the canonical generic timeout
            # and works for RTSP over TCP.
            # NOTE: -reconnect* flags are HTTP-only in ffmpeg; not valid for RTSP.
            "-timeout", "60000000",
            "-i", rtsp_url,
            # ── Video encoding: ultrafast preset for realtime, CRF 23 keeps good
            #    quality while producing files ~3x smaller than CRF 18.
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-r", "25",
            "-g", "50",          # keyframe every 2s → fast seek / progressive load
            "-keyint_min", "50",
            "-sc_threshold", "0",
            # Container: fragmented MP4 mode is NOT used so we can keep faststart.
            "-movflags", "+faststart",
            # ── Audio: stripped (portal recordings are muted by design)
            "-an",
            # Drop any skew between audio/video introduced by wallclock retiming.
            "-vsync", "cfr",
            "-f", "mp4",
            "-y",
            str(filepath),
        ]

        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        asyncio.create_task(self._log_stderr(process, camera, meta))
        return _RecordingProcess(meta=meta, process=process)

    async def _stop_recording(self, rec: _RecordingProcess) -> RecordingMeta:
        try:
            if rec.process.stdin:
                rec.process.stdin.write(b"q")
                await rec.process.stdin.drain()
        except Exception:
            pass

        try:
            await asyncio.wait_for(rec.process.wait(), timeout=_FFMPEG_Q_WAIT_SEC)
        except asyncio.TimeoutError:
            rec.process.terminate()
            try:
                await asyncio.wait_for(rec.process.wait(), timeout=_FFMPEG_TERM_WAIT_SEC)
            except asyncio.TimeoutError:
                rec.process.kill()
                with contextlib.suppress(Exception):
                    await rec.process.wait()

        rc = rec.process.returncode
        elapsed = int((datetime.now(timezone.utc) - rec.meta.started_at).total_seconds())
        size_mb = rec.meta.filepath.stat().st_size / 1024 / 1024 if rec.meta.filepath.exists() else 0
        logger.info(
            "[RECORD] ffmpeg cam%d exit rc=%s elapsed=%ds file=%s size=%.2f MB",
            rec.meta.camera,
            rc,
            elapsed,
            rec.meta.filename,
            size_mb,
        )
        logger.info("[RECORD] Saved: %s (%.2f MB)", rec.meta.filename, size_mb)
        # Unexpected exit codes: log sanitized stderr tail for root-cause analysis.
        if rc not in (0, None):
            tail = "\n".join(rec.meta.stderr_tail[-15:])
            logger.warning(
                "[RECORD] ffmpeg cam%d non-zero exit (rc=%s), stderr tail:\n%s",
                rec.meta.camera,
                rc,
                tail or "(no stderr captured)",
            )
        return rec.meta

    async def _auto_stop_manual(self, duration: int) -> None:
        await asyncio.sleep(duration)
        await self.stop_manual()

    async def _watchdog_recording(self, rec: _RecordingProcess, expected_duration: int) -> None:
        """Detect when an ffmpeg recording process exits before its expected duration.

        We only mark the camera as "died" — we do NOT auto-restart, because a dying
        ffmpeg usually means the RTSP source itself is unstable and a restart loop
        would just hammer the camera. The marker is surfaced via workflow_status() so
        the admin UI can flag the recording as incomplete.
        """
        try:
            await rec.process.wait()
        except asyncio.CancelledError:
            return

        elapsed = int((datetime.now(timezone.utc) - rec.meta.started_at).total_seconds())
        wf = self._workflow
        # If the workflow has already been stopped (or replaced), the exit is expected.
        if wf is None or rec.meta.camera not in wf.recordings:
            return
        # Tolerance: ffmpeg may exit a couple of seconds early on graceful stop.
        if elapsed + 5 < expected_duration:
            rc = rec.process.returncode
            tail = "\n".join(rec.meta.stderr_tail[-20:])
            logger.error(
                "[RECORD] cam%d died at t=%ds (expected %ds) rc=%s — file likely truncated\n"
                "stderr tail:\n%s",
                rec.meta.camera,
                elapsed,
                expected_duration,
                rc,
                tail or "(no stderr captured)",
            )
            if rec.meta.camera not in wf.died_cameras:
                wf.died_cameras.append(rec.meta.camera)

    @staticmethod
    async def _log_stderr(
        process: asyncio.subprocess.Process,
        camera: int,
        meta: RecordingMeta,
    ) -> None:
        """Forward ffmpeg stderr lines to our logger.

        Only obvious fatal patterns are surfaced as ERROR; everything else stays at
        DEBUG to avoid drowning the log when ffmpeg emits warnings such as
        "non-existing PPS 0 referenced" which are benign for IP-camera streams.
        """
        if process.stderr is None:
            return
        fatal_tokens = (
            "error opening input",
            "connection refused",
            "connection timed out",
            "server returned 5",
            "server returned 4",
            "no route to host",
            "could not write header",
            "broken pipe",
            "end of file",
            "invalid data",
        )
        async for line in process.stderr:
            text = line.decode(errors="replace").strip()
            if text:
                _append_stderr_tail(meta, text)
            low = text.lower()
            safe = _sanitize_log_line(text)
            if any(tok in low for tok in fatal_tokens):
                logger.error("[ffmpeg cam%s] %s", camera, safe)
            else:
                logger.debug("[ffmpeg cam%s] %s", camera, safe)

    @staticmethod
    def _build_timestamped_name(camera: int) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3] + "Z"
        return f"cam{camera}_{timestamp}.mp4"
