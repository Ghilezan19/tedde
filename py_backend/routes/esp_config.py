"""
ESP sync — single source of truth in .env for countdown + recording length.

GET /api/esp/config
    Returns JSON the firmware can parse after WiFi connect so the LCD
    countdown matches the duration the server will use (when the ESP
    sends the same number in POST /counter-start as \"value\").
"""

import logging

from fastapi import APIRouter

import event_log
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/esp", tags=["esp"])


@router.get("/config", summary="Timer/countdown values for ESP32")
def esp_config() -> dict:
    """
    Fields:
    - **countdown_seconds**: what to show on the ESP countdown (and send as JSON \"value\").
    - **recording_duration_seconds**: default recording length on the server if POST omits \"value\".
    """
    countdown = (
        settings.esp_countdown_seconds
        if settings.esp_countdown_seconds is not None
        else settings.recording_duration_seconds
    )
    logger.debug("GET /api/esp/config → countdown=%s", countdown)
    event_log.step(
        f"ESP: citit timer din server → countdown={countdown}s, "
        f"recording_default={settings.recording_duration_seconds}s"
    )
    return {
        "countdown_seconds": countdown,
        "recording_duration_seconds": settings.recording_duration_seconds,
    }
