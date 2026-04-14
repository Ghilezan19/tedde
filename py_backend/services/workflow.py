"""
Unified workflow orchestration for ESP and dashboard triggers.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import event_log
from camera.media import save_snapshot
from camera.recording import RecordingManager, workflow_output_status
from config import settings
from services.alpr_service import ALPRService, normalize_plate_text

logger = logging.getLogger(__name__)


class WorkflowMode(str, Enum):
    SIMPLE = "simple"


@dataclass
class WorkflowRun:
    session_id: str
    source: str
    started_at: datetime
    duration_seconds: int
    cameras: list[int] = field(default_factory=lambda: [1, 2])
    alpr_camera: int = field(default_factory=lambda: settings.alpr_camera)
    temp_dir: Path | None = None
    event_dir: Path | None = None
    selected_plate: str | None = None
    snapshot_relpath: str | None = None
    alpr_result: dict[str, Any] | None = None
    completed_at: datetime | None = None
    error: str | None = None
    recording_outputs: dict[str, bool] | None = None
    recording_warnings: list[str] = field(default_factory=list)
    # Target folder after ALPR; rename happens only after ffmpeg stops (see finally).
    final_dir_planned: Path | None = None

    def remaining_seconds(self) -> int:
        if self.completed_at is not None:
            return 0
        elapsed = int((datetime.now(timezone.utc) - self.started_at).total_seconds())
        return max(0, self.duration_seconds - elapsed)

    def public_status(self, busy: bool) -> dict[str, Any]:
        event_id = self.event_dir.name if self.event_dir else (self.temp_dir.name if self.temp_dir else None)
        rec = self.recording_outputs
        if rec is not None:
            rec_block: dict[str, Any] = {
                "recordings": {
                    "camera1": bool(rec.get("camera1")),
                    "camera2": bool(rec.get("camera2")),
                },
                "recording_partial": sum(1 for v in rec.values() if v) == 1,
            }
        else:
            rec_block = {"recordings": None, "recording_partial": False}
        return {
            "busy": busy,
            "session_id": self.session_id,
            "source": self.source,
            "started_at": self.started_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "remaining_seconds": self.remaining_seconds() if busy else 0,
            "active_cameras": self.cameras,
            "event_id": event_id,
            "event_folder": event_id,
            "selected_plate": self.selected_plate,
            "snapshot_url": f"/events/{self.snapshot_relpath}" if self.snapshot_relpath else None,
            "error": self.error,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            **rec_block,
            "recording_warnings": list(self.recording_warnings),
        }


class WorkflowService:
    def __init__(
        self,
        recording_manager: RecordingManager,
        alpr_service: ALPRService,
    ) -> None:
        self._recording = recording_manager
        self._alpr = alpr_service
        self._running_workflow: Optional[asyncio.Task] = None
        self._active_run: WorkflowRun | None = None
        self._last_run: WorkflowRun | None = None

    def is_busy(self) -> bool:
        return self._running_workflow is not None and not self._running_workflow.done()

    async def trigger(
        self,
        *,
        mode: WorkflowMode = WorkflowMode.SIMPLE,
        duration: int | None = None,
        source: str = "api",
    ) -> WorkflowRun:
        if mode != WorkflowMode.SIMPLE:
            raise ValueError(f"Unsupported workflow mode: {mode}")
        if self.is_busy():
            raise RuntimeError("A workflow is already running.")
        if self._recording.any_active():
            raise RuntimeError("A recording is already in progress.")

        duration_seconds = duration or settings.recording_duration_seconds
        started_at = datetime.now(timezone.utc)
        session_id = started_at.strftime("%Y%m%dT%H%M%S%f")[:-3]
        temp_dir = settings.events_dir_abs / f".tmp_{session_id}"
        run = WorkflowRun(
            session_id=session_id,
            source=source,
            started_at=started_at,
            duration_seconds=duration_seconds,
            temp_dir=temp_dir,
            event_dir=temp_dir,
        )
        self._active_run = run
        self._running_workflow = asyncio.create_task(self._run_workflow(run))
        self._running_workflow.add_done_callback(self._on_done)
        return run

    def status(self) -> dict[str, Any]:
        if self._active_run and self.is_busy():
            return {
                **self._active_run.public_status(busy=True),
                "last_event": self._last_run.public_status(busy=False) if self._last_run else None,
            }
        return {
            "busy": False,
            "session_id": None,
            "started_at": None,
            "duration_seconds": None,
            "remaining_seconds": 0,
            "active_cameras": [],
            "event_id": None,
            "event_folder": None,
            "selected_plate": None,
            "snapshot_url": None,
            "error": None,
            "completed_at": None,
            "recordings": None,
            "recording_warnings": [],
            "recording_partial": False,
            "last_event": self._last_run.public_status(busy=False) if self._last_run else None,
        }

    async def _run_workflow(self, run: WorkflowRun) -> None:
        event_log.banner("WORKFLOW: PORNIRE CAPTURA PARALELA")
        event_log.step(f"Sursa: {run.source} | durată: {run.duration_seconds}s | camere: {run.cameras}")

        run.temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            await self._recording.start_workflow(
                session_id=run.session_id,
                event_dir=run.temp_dir,
                cameras=run.cameras,
                stream=settings.workflow_record_stream,
                duration=run.duration_seconds,
            )
            event_log.step("Înregistrare workflow pornită (camere 1 și 2, tolerant la eșec pe o cameră).")

            snapshot_path = run.temp_dir / "alpr_start.jpg"
            await save_snapshot(run.alpr_camera, "main", snapshot_path)
            run.snapshot_relpath = f"{run.temp_dir.name}/{snapshot_path.name}"
            event_log.step(f"Snapshot ALPR capturat din camera {run.alpr_camera}.")

            alpr_result = await self._alpr.predict_image(snapshot_path)
            run.alpr_result = alpr_result
            selected_plate = normalize_plate_text(alpr_result["selected_plate"] or "UNKNOWN")
            run.selected_plate = selected_plate

            run.final_dir_planned = self._resolve_final_dir(selected_plate, run.started_at)
            event_log.step(
                f"Înregistrare în {run.temp_dir.name}; redenumire după oprire → {run.final_dir_planned.name}"
            )

            self._write_alpr_json(run)

            await asyncio.sleep(run.duration_seconds)
        except Exception as exc:
            run.error = str(exc)
            logger.exception("[WORKFLOW] Workflow failed: %s", exc)
            event_log.warn(f"Eroare workflow: {exc}")
        finally:
            stopped = None
            with contextlib.suppress(Exception):
                stopped = await self._recording.stop_workflow()
            run.completed_at = datetime.now(timezone.utc)
            # Rename only after muxers finish — ffmpeg keeps the spawn-time output path for +faststart trailer.
            if (
                run.final_dir_planned is not None
                and run.temp_dir is not None
                and run.temp_dir.exists()
                and run.temp_dir.resolve() != run.final_dir_planned.resolve()
            ):
                try:
                    run.temp_dir.rename(run.final_dir_planned)
                    run.event_dir = run.final_dir_planned
                    run.temp_dir = run.final_dir_planned
                    run.snapshot_relpath = f"{run.final_dir_planned.name}/alpr_start.jpg"
                except OSError:
                    logger.exception(
                        "[WORKFLOW] Could not rename %s → %s",
                        run.temp_dir,
                        run.final_dir_planned,
                    )
            if run.event_dir is not None:
                if stopped and stopped.spawn_failed_cameras:
                    run.recording_warnings.append(
                        "Camere fără pornire ffmpeg: "
                        + ", ".join(str(c) for c in sorted(stopped.spawn_failed_cameras))
                    )
                outs, warns = workflow_output_status(run.event_dir)
                run.recording_outputs = outs
                run.recording_warnings.extend(warns)
            if run.event_dir and not run.error and run.alpr_result is not None:
                self._write_alpr_json(run)
            event_log.banner("WORKFLOW: FINALIZAT")

    def _write_alpr_json(self, run: WorkflowRun) -> None:
        if run.event_dir is None:
            return
        payload = {
            "timestamp": run.started_at.isoformat(),
            "source_camera": run.alpr_camera,
            "selected_plate": run.selected_plate or "UNKNOWN",
            "plates": (run.alpr_result or {}).get("plates", []),
            "workflow_duration_seconds": run.duration_seconds,
            "session_id": run.session_id,
            "recordings": {
                "camera1": "camera1.mp4",
                "camera2": "camera2.mp4",
            },
            "snapshot": "alpr_start.jpg",
            "error": run.error,
        }
        (run.event_dir / "alpr.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    @staticmethod
    def _resolve_final_dir(selected_plate: str, started_at: datetime) -> Path:
        timestamp = started_at.strftime("%Y-%m-%dT%H-%M-%SZ")
        base_name = f"{selected_plate}_{timestamp}"
        final_dir = settings.events_dir_abs / base_name
        suffix = 1
        while final_dir.exists():
            final_dir = settings.events_dir_abs / f"{base_name}_{suffix}"
            suffix += 1
        return final_dir

    def _on_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            logger.info("[WORKFLOW] Workflow task cancelled.")
        elif task.exception():
            logger.exception("[WORKFLOW] Workflow raised an exception:", exc_info=task.exception())

        if self._active_run is not None:
            self._last_run = deepcopy(self._active_run)
        self._active_run = None
        self._running_workflow = None
