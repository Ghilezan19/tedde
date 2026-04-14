"""
Probe ISAPI TwoWayAudio `open` on the camera selected by AUDIO_ISAPI_CAMERA.

Does not start FastAPI. Use the same host/port/credentials as the backend.

Usage (from repo root):
  PYTHONPATH=py_backend python -m tools.probe_twoway_audio

Optional override (ignores AUDIO_ISAPI_CAMERA for this run only):
  PYTHONPATH=py_backend python -m tools.probe_twoway_audio --camera 1
  PYTHONPATH=py_backend python -m tools.probe_twoway_audio --camera 2

Also enable two-way / intercom in the camera web UI if the device supports it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

_AUDIO_OPEN = "/ISAPI/System/TwoWayAudio/channels/1/open"


async def _run(camera: int | None) -> int:
    from camera.isapi_client import ISAPIClient
    from config import settings

    if camera == 1:
        client = ISAPIClient(
            ip=settings.camera_ip,
            port=settings.camera1_http_port,
            username=settings.camera_username,
            password=settings.camera_password,
        )
        label = f"camera1 {settings.camera_ip}:{settings.camera1_http_port}"
    elif camera == 2:
        client = ISAPIClient(
            ip=settings.camera2_ip,
            port=settings.camera2_http_port,
            username=settings.camera2_username,
            password=settings.camera2_password,
        )
        label = f"camera2 {settings.camera2_ip}:{settings.camera2_http_port}"
    else:
        from camera.audio import build_isapi_client_for_audio

        client, idx = build_isapi_client_for_audio()
        label = f"camera{idx} {client.base_url.removeprefix('http://')}"

    print(f"PUT {_AUDIO_OPEN} on {label} …")
    resp = await client.request("PUT", _AUDIO_OPEN, body=None)
    status = resp["status"]
    snippet = (resp.get("data") or "")[:300].replace("\n", " ")
    print(f"HTTP {status}")
    if snippet:
        print(f"body: {snippet!r}")
    if status in (200, 201):
        print("OK — TwoWayAudio open accepted (check camera firmware for speaker support).")
        return 0
    print("FAIL — see HTTP status and body; 404 often means endpoint unsupported on this model/port.")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe ISAPI TwoWayAudio open.")
    parser.add_argument(
        "--camera",
        type=int,
        choices=(1, 2),
        default=None,
        help="Force camera 1 or 2 (default: use AUDIO_ISAPI_CAMERA from .env).",
    )
    args = parser.parse_args()
    code = asyncio.run(_run(args.camera))
    sys.exit(code)


if __name__ == "__main__":
    main()
