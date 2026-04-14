"""
Session-oriented recording manager using ffmpeg subprocesses.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
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


def workflow_output_status(
    event_dir: Path, *, expected_cameras: tuple[int, ...] = (1, 2)
) -> tuple[dict[str, bool], list[str]]:
    """Which camera files are usable; Romanian warnings for operator/portal."""
    out: dict[str, bool] = {}
    warnings: list[str] = []
    for cam in expected_cameras:
        key = f"camera{cam}"
        path = event_dir / f"{key}.mp4"
        if path.is_file():
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
            logger.info("[RECORD] Workflow started: %s", session_id)
            return self._workflow

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
            "-rtsp_transport", "tcp",
            "-timeout", "5000000",
            "-i", rtsp_url,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-r", "25",
            "-c:a", "aac",
            "-ar", "16000",
            "-ac", "1",
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
        asyncio.create_task(self._log_stderr(process, camera))
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

        size_mb = rec.meta.filepath.stat().st_size / 1024 / 1024 if rec.meta.filepath.exists() else 0
        logger.info("[RECORD] Saved: %s (%.2f MB)", rec.meta.filename, size_mb)
        return rec.meta

    async def _auto_stop_manual(self, duration: int) -> None:
        await asyncio.sleep(duration)
        await self.stop_manual()

    @staticmethod
    async def _log_stderr(process: asyncio.subprocess.Process, camera: int) -> None:
        if process.stderr is None:
            return
        async for line in process.stderr:
            text = line.decode(errors="replace").strip()
            if any(token in text.lower() for token in ("error", "invalid", "failed")):
                logger.error("[ffmpeg cam%s] %s", camera, text)

    @staticmethod
    def _build_timestamped_name(camera: int) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3] + "Z"
        return f"cam{camera}_{timestamp}.mp4"
