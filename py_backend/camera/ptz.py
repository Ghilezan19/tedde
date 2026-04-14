"""
Async ONVIF PTZ client for Camera 2 (HiLook PTZ-N2C400I-W).

Uses ONVIF SOAP over HTTP with WS-Security PasswordDigest authentication,
using SHA-1 digest authentication with a fresh nonce per request.

Supported operations:
- goto_preset()       — GotoPreset
- absolute_move()     — AbsoluteMove  (x/y in -1..1, zoom in 0..1)
- continuous_move()   — ContinuousMove (pan/tilt velocity -1..1)
- stop()              — Stop pan/tilt and zoom
- get_status()        — GetStatus (raw XML)
- list_presets()      — GetPresets → list of {token, name}
"""

import base64
import hashlib
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_PTZ_SVC = "/onvif/PTZ_Service"
_PTZ_NS  = "http://www.onvif.org/ver20/ptz/wsdl"
_TT_NS   = "http://www.onvif.org/ver10/schema"


# Direction name → (pan_x, tilt_y) unit vectors
PTZ_DIRECTION_VECTORS: dict[str, tuple[float, float]] = {
    "up":         ( 0.0,    1.0),
    "down":       ( 0.0,   -1.0),
    "left":       (-1.0,    0.0),
    "right":      ( 1.0,    0.0),
    "up-left":    (-0.707,  0.707),
    "up-right":   ( 0.707,  0.707),
    "down-left":  (-0.707, -0.707),
    "down-right": ( 0.707, -0.707),
}


# ------------------------------------------------------------------ #
# WS-Security header builder
# ------------------------------------------------------------------ #

def _ws_security_header(username: str, password: str) -> str:
    """Build an ONVIF WS-Security PasswordDigest header."""
    nonce_bytes = secrets.token_bytes(16)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    nonce_b64 = base64.b64encode(nonce_bytes).decode()

    digest = base64.b64encode(
        hashlib.sha1(
            nonce_bytes + created.encode() + password.encode()
        ).digest()
    ).decode()

    wsse_ns = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
    wsu_ns  = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
    pw_type = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
    enc_type = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"

    return (
        f'<s:Header>'
        f'<Security xmlns="{wsse_ns}">'
        f'<UsernameToken>'
        f'<Username>{username}</Username>'
        f'<Password Type="{pw_type}">{digest}</Password>'
        f'<Nonce EncodingType="{enc_type}">{nonce_b64}</Nonce>'
        f'<Created xmlns="{wsu_ns}">{created}</Created>'
        f'</UsernameToken>'
        f'</Security>'
        f'</s:Header>'
    )


def _soap_envelope(header: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
        f'{header}'
        f'<s:Body>{body}</s:Body>'
        '</s:Envelope>'
    )


# ------------------------------------------------------------------ #
# PTZClient
# ------------------------------------------------------------------ #

class PTZClient:
    """Async ONVIF PTZ client for Camera 2."""

    def __init__(self) -> None:
        self._base_url = (
            f"http://{settings.camera2_ip}:{settings.camera2_http_port}"
        )
        self._profile = settings.camera2_onvif_profile

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def goto_preset(self, token: str) -> bool:
        """Move camera to an ONVIF preset by its token string."""
        body = (
            f'<tptz:GotoPreset xmlns:tptz="{_PTZ_NS}">'
            f'<tptz:ProfileToken>{self._profile}</tptz:ProfileToken>'
            f'<tptz:PresetToken>{token}</tptz:PresetToken>'
            f'</tptz:GotoPreset>'
        )
        result = await self._soap(f"{_PTZ_NS}/GotoPreset", body)
        ok = result["status"] == 200
        logger.info("[PTZ] GotoPreset(%s) → %d", token, result["status"])
        return ok

    async def absolute_move(
        self, x: float = 0.0, y: float = 0.0, zoom: float = 0.0
    ) -> bool:
        """Move to an absolute pan/tilt/zoom position (values in -1..1, zoom 0..1)."""
        px = max(-1.0, min(1.0, x))
        py = max(-1.0, min(1.0, y))
        pz = max(0.0,  min(1.0, zoom))
        body = (
            f'<tptz:AbsoluteMove xmlns:tptz="{_PTZ_NS}">'
            f'<tptz:ProfileToken>{self._profile}</tptz:ProfileToken>'
            f'<tptz:Position>'
            f'<tt:PanTilt xmlns:tt="{_TT_NS}" x="{px:.3f}" y="{py:.3f}"/>'
            f'<tt:Zoom xmlns:tt="{_TT_NS}" x="{pz:.3f}"/>'
            f'</tptz:Position>'
            f'</tptz:AbsoluteMove>'
        )
        result = await self._soap(f"{_PTZ_NS}/AbsoluteMove", body)
        logger.info("[PTZ] AbsoluteMove(%.2f, %.2f, %.2f) → %d", px, py, pz, result["status"])
        return result["status"] == 200

    async def continuous_move(
        self,
        direction: str = "left",
        speed: int = 5,
    ) -> bool:
        """
        Start continuous pan/tilt movement.

        Args:
            direction: One of the keys in PTZ_DIRECTION_VECTORS.
            speed:     1–7 (mapped to -1..1 range).
        """
        speed_n = max(1, min(7, speed))
        v = PTZ_DIRECTION_VECTORS.get(direction)
        if v is None:
            raise ValueError(f"Unknown direction '{direction}'. Valid: {list(PTZ_DIRECTION_VECTORS)}")
        vx = v[0] * speed_n / 7
        vy = v[1] * speed_n / 7
        # Omit <Zoom> — PT-only cameras return 500 if Zoom element is included
        body = (
            f'<tptz:ContinuousMove xmlns:tptz="{_PTZ_NS}">'
            f'<tptz:ProfileToken>{self._profile}</tptz:ProfileToken>'
            f'<tptz:Velocity>'
            f'<tt:PanTilt xmlns:tt="{_TT_NS}" x="{vx:.3f}" y="{vy:.3f}"/>'
            f'</tptz:Velocity>'
            f'</tptz:ContinuousMove>'
        )
        result = await self._soap(f"{_PTZ_NS}/ContinuousMove", body)
        logger.info("[PTZ] ContinuousMove(%s, spd=%d) → %d", direction, speed_n, result["status"])
        return result["status"] == 200

    async def stop(self) -> bool:
        """Stop all pan/tilt and zoom movement."""
        body = (
            f'<tptz:Stop xmlns:tptz="{_PTZ_NS}">'
            f'<tptz:ProfileToken>{self._profile}</tptz:ProfileToken>'
            f'<tptz:PanTilt>true</tptz:PanTilt>'
            f'<tptz:Zoom>true</tptz:Zoom>'
            f'</tptz:Stop>'
        )
        result = await self._soap(f"{_PTZ_NS}/Stop", body)
        logger.info("[PTZ] Stop → %d", result["status"])
        return result["status"] == 200

    async def get_status(self) -> dict:
        """Return PTZ status (raw XML + parsed position if available)."""
        body = (
            f'<tptz:GetStatus xmlns:tptz="{_PTZ_NS}">'
            f'<tptz:ProfileToken>{self._profile}</tptz:ProfileToken>'
            f'</tptz:GetStatus>'
        )
        result = await self._soap(f"{_PTZ_NS}/GetStatus", body)
        return {"status": result["status"], "raw": result["data"]}

    async def list_presets(self) -> list[dict]:
        """Return all ONVIF presets as [{"token": ..., "name": ...}]."""
        import re
        body = (
            f'<tptz:GetPresets xmlns:tptz="{_PTZ_NS}">'
            f'<tptz:ProfileToken>{self._profile}</tptz:ProfileToken>'
            f'</tptz:GetPresets>'
        )
        result = await self._soap(f"{_PTZ_NS}/GetPresets", body)
        presets = []
        pattern = re.compile(r'token="([^"]+)"[^>]*>[\s\S]*?<[^:]+:Name>([^<]+)<\/[^:]+:Name>')
        for m in pattern.finditer(result["data"]):
            presets.append({"token": m.group(1), "name": m.group(2).strip()})
        return presets

    async def set_preset(self, name: str, token: str | None = None) -> dict:
        safe_name = (
            name.replace("&", "")
            .replace("<", "")
            .replace(">", "")
            .replace('"', "")
            .replace("'", "")
        )
        body = (
            f'<tptz:SetPreset xmlns:tptz="{_PTZ_NS}">'
            f'<tptz:ProfileToken>{self._profile}</tptz:ProfileToken>'
            f"<tptz:PresetName>{safe_name}</tptz:PresetName>"
        )
        if token:
            body += f"<tptz:PresetToken>{token}</tptz:PresetToken>"
        body += "</tptz:SetPreset>"
        result = await self._soap(f"{_PTZ_NS}/SetPreset", body)
        import re

        token_match = re.search(r"<[^:>]+:PresetToken[^>]*>([^<]+)<", result["data"])
        return {
            "success": result["status"] == 200,
            "token": token_match.group(1).strip() if token_match else token,
            "name": safe_name,
            "status": result["status"],
        }

    async def remove_preset(self, token: str) -> bool:
        body = (
            f'<tptz:RemovePreset xmlns:tptz="{_PTZ_NS}">'
            f'<tptz:ProfileToken>{self._profile}</tptz:ProfileToken>'
            f"<tptz:PresetToken>{token}</tptz:PresetToken>"
            f"</tptz:RemovePreset>"
        )
        result = await self._soap(f"{_PTZ_NS}/RemovePreset", body)
        return result["status"] == 200

    async def zoom(self, direction: str = "in", speed: int = 5) -> bool:
        speed_n = max(1, min(7, speed))
        zoom_value = speed_n / 7 if direction == "in" else -(speed_n / 7)
        body = (
            f'<tptz:ContinuousMove xmlns:tptz="{_PTZ_NS}">'
            f'<tptz:ProfileToken>{self._profile}</tptz:ProfileToken>'
            f"<tptz:Velocity>"
            f'<tt:PanTilt xmlns:tt="{_TT_NS}" x="0" y="0"/>'
            f'<tt:Zoom xmlns:tt="{_TT_NS}" x="{zoom_value:.3f}"/>'
            f"</tptz:Velocity>"
            f"</tptz:ContinuousMove>"
        )
        result = await self._soap(f"{_PTZ_NS}/ContinuousMove", body)
        return result["status"] == 200

    # ------------------------------------------------------------------ #
    # SOAP transport
    # ------------------------------------------------------------------ #

    async def _soap(self, action: str, body_xml: str) -> dict:
        """Send a SOAP request to the PTZ service and return status + response body."""
        header = _ws_security_header(
            settings.camera2_username,
            settings.camera2_password,
        )
        envelope = _soap_envelope(header, body_xml)
        payload = envelope.encode("utf-8")

        async with httpx.AsyncClient(timeout=8.0) as client:
            try:
                resp = await client.post(
                    f"{self._base_url}{_PTZ_SVC}",
                    content=payload,
                    headers={
                        "Content-Type": (
                            f'application/soap+xml; charset=utf-8; action="{action}"'
                        ),
                    },
                )
                return {"status": resp.status_code, "data": resp.text}
            except httpx.TimeoutException:
                raise TimeoutError(f"ONVIF request timed out: {action}")
            except httpx.RequestError as exc:
                raise ConnectionError(f"ONVIF connection error: {exc}") from exc
