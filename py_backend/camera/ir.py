"""
IR / day-night mode control for Camera 2 (HiLook PTZ-N2C400I-W).

Uses ONVIF Imaging Service SOAP — the same transport as PTZ, because this
camera model's port 80 is a plain file server and does NOT support ISAPI.

ONVIF IrCutFilter values (tt:IrCutFilterModes):
  ON   — filter physically inserted → blocks IR → colour/day video
  OFF  — filter removed             → IR passes through → B&W/night video
  AUTO — camera decides automatically

Typical usage:
    ir = IRClient()
    await ir.set_day_mode()   # forces colour video at startup
"""

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

# ONVIF Imaging service — same naming convention as /onvif/PTZ_Service
_IMAGING_SVC  = "/onvif/Imaging_Service"
_IMAGING_WSDL = "http://www.onvif.org/ver20/imaging/wsdl"
_TT_NS        = "http://www.onvif.org/ver10/schema"

# VideoSource token as reported by this camera model (GetVideoSources → "VideoSource_1")
_VIDEO_SOURCE = "VideoSource_1"


# ------------------------------------------------------------------ #
# WS-Security — identical implementation to ptz.py
# ------------------------------------------------------------------ #

def _ws_security_header(username: str, password: str) -> str:
    """Build an ONVIF WS-Security PasswordDigest header."""
    nonce_bytes = secrets.token_bytes(16)
    created     = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    nonce_b64   = base64.b64encode(nonce_bytes).decode()

    digest = base64.b64encode(
        hashlib.sha1(
            nonce_bytes + created.encode() + password.encode()
        ).digest()
    ).decode()

    wsse_ns  = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
    wsu_ns   = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
    pw_type  = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
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
# IRClient
# ------------------------------------------------------------------ #

class IRClient:
    """
    Controls IR cut filter for Camera 2 via ONVIF Imaging Service.
    One instance is typically shared application-wide.
    """

    def __init__(self) -> None:
        self._url      = f"http://{settings.camera2_ip}:{settings.camera2_http_port}{_IMAGING_SVC}"
        self._username = settings.camera2_username
        self._password = settings.camera2_password

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def get_mode(self) -> dict:
        """
        Read current IrCutFilter from ONVIF GetImagingSettings.

        Returns:
            {"ir_cut_filter": "ON" | "OFF" | "AUTO" | "unknown", "raw_xml": str}
        """
        body = (
            f'<timg:GetImagingSettings xmlns:timg="{_IMAGING_WSDL}">'
            f'<timg:VideoSourceToken>{_VIDEO_SOURCE}</timg:VideoSourceToken>'
            f'</timg:GetImagingSettings>'
        )
        result = await self._soap(f"{_IMAGING_WSDL}/GetImagingSettings", body)
        ir_val = self._parse_ir_cut(result["data"])
        logger.info("[IR] GetImagingSettings → status=%d  IrCutFilter=%s", result["status"], ir_val)
        return {"ir_cut_filter": ir_val, "raw_xml": result["data"]}

    async def set_day_mode(self) -> bool:
        """
        Force colour (day) video: IrCutFilter = ON.

        Returns True on success (HTTP 200).
        """
        logger.info("[IR] Setting day mode via ONVIF (IrCutFilter=ON)")
        ok = await self._set_ir_cut("ON")
        if ok:
            logger.info("[IR] Day mode set — camera should show colour video")
        else:
            logger.warning("[IR] Day mode ONVIF call failed")
        return ok

    async def set_night_mode(self) -> bool:
        """Force night (IR) video: IrCutFilter = OFF."""
        logger.info("[IR] Setting night mode via ONVIF (IrCutFilter=OFF)")
        return await self._set_ir_cut("OFF")

    async def set_auto_mode(self) -> bool:
        """Return to automatic day/night switching: IrCutFilter = AUTO."""
        logger.info("[IR] Setting auto mode via ONVIF (IrCutFilter=AUTO)")
        return await self._set_ir_cut("AUTO")

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    async def _set_ir_cut(self, mode: str) -> bool:
        """
        Send ONVIF SetImagingSettings with IrCutFilter = mode (ON | OFF | AUTO).
        ForcePersistence=false means the setting applies immediately without saving.
        """
        body = (
            f'<timg:SetImagingSettings xmlns:timg="{_IMAGING_WSDL}"'
            f'  xmlns:tt="{_TT_NS}">'
            f'<timg:VideoSourceToken>{_VIDEO_SOURCE}</timg:VideoSourceToken>'
            f'<timg:ImagingSettings>'
            f'<tt:IrCutFilter>{mode}</tt:IrCutFilter>'
            f'</timg:ImagingSettings>'
            f'<timg:ForcePersistence>false</timg:ForcePersistence>'
            f'</timg:SetImagingSettings>'
        )
        result = await self._soap(f"{_IMAGING_WSDL}/SetImagingSettings", body)
        ok = result["status"] == 200
        if not ok:
            logger.warning("[IR] SetImagingSettings(%s) → %d: %s", mode, result["status"], result["data"][:300])
        return ok

    async def _soap(self, action: str, body: str) -> dict:
        header   = _ws_security_header(self._username, self._password)
        envelope = _soap_envelope(header, body)
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.post(
                    self._url,
                    content=envelope.encode("utf-8"),
                    headers={
                        "Content-Type": 'application/soap+xml; charset=utf-8',
                        "SOAPAction":   f'"{action}"',
                    },
                )
                return {"status": resp.status_code, "data": resp.text}
        except Exception as exc:
            logger.error("[IR] SOAP request failed: %s", exc)
            return {"status": 0, "data": str(exc)}

    @staticmethod
    def _parse_ir_cut(xml: str) -> str:
        """Extract IrCutFilter value from ONVIF GetImagingSettings response."""
        import re
        m = re.search(r"<[^:>]*:?IrCutFilter[^>]*>([^<]+)<", xml, re.IGNORECASE)
        return m.group(1).strip() if m else "unknown"
