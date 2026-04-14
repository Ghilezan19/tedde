"""
ESP sync — single source of truth in .env for countdown + recording length.

GET /api/esp/config
    Returns JSON the firmware can parse after WiFi connect so the LCD
    countdown matches the duration the server will use (when the ESP
    sends the same number in POST /counter-start as \"value\").

GET /api/esp/help
    JSON: server base URL(s) + optional ESP_DEVICE_IP from .env (quick lookup).

GET /help-esp1 (registered in main.py)
    HTML cheat sheet for the same (bookmarkable; easy to search \"help-esp1\").
"""

from __future__ import annotations

import logging
from html import escape
from typing import Any

from fastapi import APIRouter, Request

import event_log
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/esp", tags=["esp"])


def esp_help_payload(request: Request) -> dict[str, Any]:
    """Data for /api/esp/help and /help-esp1."""
    public = settings.public_base_url.rstrip("/")
    host = request.headers.get("host")
    scheme = request.headers.get("x-forwarded-proto") or (request.url.scheme or "http")
    current = f"{scheme}://{host}".rstrip("/") if host else public
    return {
        "server_base_public": public,
        "server_base_this_request": current,
        "esp_device_ip": settings.esp_device_ip,
        "esp_help_note": settings.esp_help_note or None,
        "paths": {
            "help_html": "/help-esp1",
            "help_json": "/api/esp/help",
            "esp_config": "/api/esp/config",
            "counter_start_post": "/counter-start",
        },
    }


def render_help_esp1_page(request: Request) -> str:
    """Minimal HTML for GET /help-esp1."""
    p = esp_help_payload(request)
    note = p.get("esp_help_note")
    esp_ip = p.get("esp_device_ip")
    pub = escape(str(p["server_base_public"]))
    req_base = escape(str(p["server_base_this_request"]))
    esp_ip_html = (
        f"<code>{escape(str(esp_ip))}</code>"
        if esp_ip
        else "<em>nu e setat</em> — pune <code>ESP_DEVICE_IP=...</code> în <code>.env</code>"
    )
    note_html = f"<p class=\"note\">{escape(str(note))}</p>" if note else ""

    return f"""<!DOCTYPE html>
<html lang="ro">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>ESP — help (tedde)</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 42rem; margin: 1.5rem auto; padding: 0 1rem; line-height: 1.45; }}
    h1 {{ font-size: 1.25rem; }}
    code {{ background: #f0f0f0; padding: 0.1em 0.35em; border-radius: 4px; }}
    .box {{ background: #fafafa; border: 1px solid #ddd; border-radius: 8px; padding: 0.75rem 1rem; margin: 0.75rem 0; }}
    .note {{ color: #444; font-size: 0.95rem; }}
    ul {{ padding-left: 1.2rem; }}
  </style>
</head>
<body>
  <h1>ESP32 — adresă server &amp; IP</h1>
  <p>Pagină scurtă pentru firmware <code>codesp.c</code> (<code>SERVER_BASE</code>) și căutare rapidă după nume (ex. <code>help-esp1</code>).</p>
  {note_html}
  <div class="box">
    <p><strong>URL server (din <code>PUBLIC_BASE_URL</code> / .env):</strong><br/><code>{pub}</code></p>
    <p><strong>URL după cum accesezi acum (Host din browser):</strong><br/><code>{req_base}</code></p>
  </div>
  <p><strong>IP ESP (opțional, din .env):</strong> {esp_ip_html}</p>
  <div class="box">
    <p><strong>Endpoint-uri utile</strong></p>
    <ul>
      <li><code>GET {escape(str(p["paths"]["esp_config"]))}</code> — timer pentru LCD</li>
      <li><code>POST {escape(str(p["paths"]["counter_start_post"]))}</code> — trigger workflow</li>
      <li><code>GET {escape(str(p["paths"]["help_json"]))}</code> — același conținut ca JSON</li>
    </ul>
  </div>
  <p><strong>Dacă nu știi IP-ul ESP:</strong> Serial Monitor (115200) după WiFi, sau listă DHCP pe router.</p>
</body>
</html>
"""


@router.get("/help", summary="ESP help: server URL + optional ESP_DEVICE_IP from .env")
def esp_help(request: Request) -> dict:
    return esp_help_payload(request)


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
