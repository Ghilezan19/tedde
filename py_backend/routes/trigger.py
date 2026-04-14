"""
ESP trigger endpoint.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

import event_log
from config import settings
from services.workflow import WorkflowMode, WorkflowService

logger = logging.getLogger(__name__)
router = APIRouter()


class TriggerPayload(BaseModel):
    event: Optional[str] = None
    value: Optional[Any] = None


def _get_workflow(request: Request) -> WorkflowService:
    return request.app.state.workflow


@router.post("/counter-start", summary="ESP trigger — start workflow")
async def counter_start(
    payload: TriggerPayload,
    workflow: WorkflowService = Depends(_get_workflow),
) -> dict:
    logger.info("[TRIGGER] event=%r value=%r busy=%s", payload.event, payload.value, workflow.is_busy())

    if workflow.is_busy():
        event_log.banner("ESP: BUTON apăsat — IGNORAT")
        event_log.warn("Workflow deja activ.")
        return {
            "status": "busy",
            "message": "A workflow is already running. Trigger ignored.",
        }

    duration_override = None
    if payload.value is not None:
        try:
            parsed = int(payload.value)
            if parsed > 0:
                duration_override = parsed
        except (TypeError, ValueError):
            duration_override = None

    effective = duration_override if duration_override is not None else settings.recording_duration_seconds
    event_log.banner("ESP: BUTON / counter-start — PORNESC WORKFLOW")
    event_log.step(f"Eveniment: {payload.event!r} | countdown: {payload.value!r}")
    event_log.step(f"Durată workflow: {effective}s")

    try:
        run = await workflow.trigger(
            mode=WorkflowMode.SIMPLE,
            duration=duration_override,
            source="esp",
        )
    except RuntimeError:
        return {
            "status": "busy",
            "message": "A workflow is already running. Trigger ignored.",
        }

    return {
        "status": "triggered",
        "message": "Workflow started.",
        "event": payload.event,
        "recording_seconds": effective,
        "session_id": run.session_id,
    }
