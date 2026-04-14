"""
Camera control endpoints — IR / day-night mode and audio speak.

Endpoints
---------
GET  /api/camera/ir              — Read current IR / light mode
POST /api/camera/ir              — Set mode: {"mode": "day"|"night"|"auto"}
POST /api/camera/ir/day          — Shortcut: force color (day) video
POST /api/camera/ir/auto         — Shortcut: restore auto day/night

POST /api/camera/speak           — Play a TTS message through the camera speaker
                                   Body: {"text": "..."} or uses default start/end messages
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from camera.ir import IRClient
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/camera", tags=["camera"])


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _get_ir(request: Request) -> IRClient:
    return request.app.state.ir_client


def _get_audio(request: Request):
    return request.app.state.audio_client


# ------------------------------------------------------------------ #
# Request models
# ------------------------------------------------------------------ #

class IRModeRequest(BaseModel):
    mode: Literal["day", "night", "auto"] = "day"


class SpeakRequest(BaseModel):
    text: Optional[str] = None


# ------------------------------------------------------------------ #
# IR / day-night routes
# ------------------------------------------------------------------ #

@router.get("/ir", summary="Read current IR / light mode")
async def ir_get(request: Request) -> dict:
    ir = _get_ir(request)
    try:
        return await ir.get_mode()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/ir", summary="Set IR mode: day | night | auto")
async def ir_set(body: IRModeRequest, request: Request) -> dict:
    ir = _get_ir(request)
    if body.mode == "day":
        ok = await ir.set_day_mode()
    elif body.mode == "night":
        ok = await ir.set_night_mode()
    else:
        ok = await ir.set_auto_mode()

    if not ok:
        raise HTTPException(status_code=502, detail=f"Camera rejected mode '{body.mode}'")
    return {"success": True, "mode": body.mode}


@router.post("/ir/day", summary="Force color (day) video — IR off")
async def ir_day(request: Request) -> dict:
    ok = await _get_ir(request).set_day_mode()
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to set day mode")
    return {"success": True, "mode": "day"}


@router.post("/ir/auto", summary="Restore automatic day/night switching")
async def ir_auto(request: Request) -> dict:
    ok = await _get_ir(request).set_auto_mode()
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to set auto mode")
    return {"success": True, "mode": "auto"}


# ------------------------------------------------------------------ #
# Audio / speak route
# ------------------------------------------------------------------ #

@router.post("/speak", summary="Play a TTS message through the camera speaker")
async def speak(body: SpeakRequest, request: Request) -> dict:
    """
    Plays text through the camera's built-in speaker via ISAPI TwoWayAudio.
    If `text` is omitted, uses TTS_START_MESSAGE from .env.
    """
    audio = _get_audio(request)
    text = body.text or settings.tts_start_message

    try:
        opened = await audio.open_session()
        if not opened:
            raise HTTPException(status_code=502, detail="Could not open audio session on camera")
        await audio.play_tts(text)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        try:
            await audio.close_session()
        except Exception:
            pass

    return {"success": True, "text": text}
