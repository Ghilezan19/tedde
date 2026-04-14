"""
Camera 2 image, light and device-info helpers.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
from datetime import datetime, timezone

import httpx

from camera.isapi_client import ISAPIClient
from config import settings

logger = logging.getLogger(__name__)


def xml_get(xml: str, tag: str) -> str | None:
    match = re.search(rf"<(?:[^:>]+:)?{tag}[^>]*>([^<]*)<", xml, re.IGNORECASE)
    return match.group(1).strip() if match else None


def xml_set(xml: str, tag: str, value: str | int) -> str:
    replacement = str(value)
    pattern = re.compile(rf"(<(?:[^:>]+:)?{tag}[^>]*>)([^<]*)(</(?:[^:>]+:)?{tag}>)", re.IGNORECASE)
    if pattern.search(xml):
        return pattern.sub(rf"\1{replacement}\3", xml, count=1)
    return xml


def onvif_get(xml: str, tag: str) -> str | None:
    match = re.search(rf"<[^:>]+:{tag}[^>]*>([^<]*)<", xml)
    return match.group(1).strip() if match else None


def _ws_security_header(username: str, password: str) -> str:
    nonce_bytes = secrets.token_bytes(16)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    nonce_b64 = base64.b64encode(nonce_bytes).decode()
    digest = base64.b64encode(hashlib.sha1(nonce_bytes + created.encode() + password.encode()).digest()).decode()
    wsse_ns = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
    wsu_ns = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
    pw_type = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
    enc_type = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"
    return (
        f'<s:Header><Security xmlns="{wsse_ns}"><UsernameToken>'
        f"<Username>{username}</Username>"
        f'<Password Type="{pw_type}">{digest}</Password>'
        f'<Nonce EncodingType="{enc_type}">{nonce_b64}</Nonce>'
        f'<Created xmlns="{wsu_ns}">{created}</Created>'
        f"</UsernameToken></Security></s:Header>"
    )


class Camera2ControlClient:
    def __init__(self) -> None:
        self._isapi = ISAPIClient(
            ip=settings.camera2_ip,
            port=settings.camera2_http_port,
            username=settings.camera2_username,
            password=settings.camera2_password,
        )
        self._base_url = f"http://{settings.camera2_ip}:{settings.camera2_http_port}"

    async def get_light(self) -> dict:
        result = await self._isapi.get("/ISAPI/Image/channels/1/supplementLight")
        mode = xml_get(result["data"], "supplementLightMode") or "unknown"
        brightness = int(xml_get(result["data"], "whiteLightBrightness") or "50")
        ir_brightness = int(xml_get(result["data"], "IRLightBrightness") or "50")
        return {
            "mode": mode,
            "brightness": brightness,
            "irBrightness": ir_brightness,
            "raw": result["data"],
            "status": result["status"],
        }

    async def set_light(self, mode: str, brightness: int) -> dict:
        mode_map = {
            "ir": "IRLight",
            "white": "colorVuWhiteLight",
            "off": "close",
            "auto": "brightnessDay",
        }
        light_mode = mode_map.get(mode, "close")
        brightness_n = max(0, min(100, brightness))
        xml = (
            "<SupplementLight>"
            f"<supplementLightMode>{light_mode}</supplementLightMode>"
            f"<whiteLightBrightness>{brightness_n}</whiteLightBrightness>"
            f"<IRLightBrightness>{brightness_n}</IRLightBrightness>"
            "<mixedLightBrightnessRegulatMode>manual</mixedLightBrightnessRegulatMode>"
            "</SupplementLight>"
        )
        result = await self._isapi.request(
            "PUT",
            "/ISAPI/Image/channels/1/supplementLight",
            body=xml.encode(),
            content_type="application/xml",
        )
        return {"status": result["status"], "data": result["data"], "mode": mode, "brightness": brightness_n}

    async def get_image_settings(self) -> dict:
        result = await self._isapi.get("/ISAPI/Image/channels/1")
        data = result["data"]
        return {
            "status": result["status"],
            "raw": data,
            "brightness": int(xml_get(data, "Brightness") or xml_get(data, "brightness") or "50"),
            "contrast": int(xml_get(data, "Contrast") or xml_get(data, "contrast") or "50"),
            "saturation": int(xml_get(data, "Saturation") or xml_get(data, "saturation") or "50"),
            "hue": int(xml_get(data, "Hue") or xml_get(data, "hue") or "50"),
            "sharpness": int(xml_get(data, "Sharpness") or xml_get(data, "sharpness") or "50"),
            "irCutFilter": xml_get(data, "IRCutFilter") or xml_get(data, "irCutFilter") or "AUTO",
            "wdr": xml_get(data, "WDREnabled") or xml_get(data, "WDR") or "false",
        }

    async def set_image_settings(
        self,
        *,
        brightness: int | None = None,
        contrast: int | None = None,
        saturation: int | None = None,
        hue: int | None = None,
        sharpness: int | None = None,
    ) -> dict:
        current = await self._isapi.get("/ISAPI/Image/channels/1")
        xml = current["data"]
        if brightness is not None:
            xml = xml_set(xml, "Brightness", brightness)
        if contrast is not None:
            xml = xml_set(xml, "Contrast", contrast)
        if saturation is not None:
            xml = xml_set(xml, "Saturation", saturation)
        if hue is not None:
            xml = xml_set(xml, "Hue", hue)
        if sharpness is not None:
            xml = xml_set(xml, "Sharpness", sharpness)

        result = await self._isapi.request(
            "PUT",
            "/ISAPI/Image/channels/1",
            body=xml.encode(),
            content_type="application/xml",
        )
        return {"status": result["status"], "data": result["data"]}

    async def get_device_info(self) -> dict:
        action = "http://www.onvif.org/ver10/device/wsdl/GetDeviceInformation"
        body = '<tds:GetDeviceInformation xmlns:tds="http://www.onvif.org/ver10/device/wsdl"/>'
        envelope = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
            f"{_ws_security_header(settings.camera2_username, settings.camera2_password)}"
            f"<s:Body>{body}</s:Body></s:Envelope>"
        )
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                f"{self._base_url}/onvif/device_service",
                content=envelope.encode("utf-8"),
                headers={
                    "Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"',
                },
            )
        data = response.text
        return {
            "status": response.status_code,
            "manufacturer": onvif_get(data, "Manufacturer") or "—",
            "model": onvif_get(data, "Model") or "—",
            "firmwareVersion": onvif_get(data, "FirmwareVersion") or "—",
            "serialNumber": onvif_get(data, "SerialNumber") or "—",
            "hardwareId": onvif_get(data, "HardwareId") or "—",
            "ip": settings.camera2_ip,
            "raw": data,
        }
