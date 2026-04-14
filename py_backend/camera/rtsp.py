"""
RTSP URL builder for Camera 1 (fixed) and Camera 2 (PTZ).

Usage:
    from camera.rtsp import build_rtsp_url
    url = build_rtsp_url(camera=1, stream="main")
"""

from urllib.parse import quote

from config import settings


def _encode(password: str) -> str:
    """URL-encode special chars in the password (same as encodeURIComponent in JS)."""
    return quote(password, safe="")


def build_rtsp_url(camera: int = 1, stream: str = "main") -> str:
    """
    Return the full RTSP URL for the requested camera and stream quality.

    Args:
        camera: 1 = fixed camera, 2 = PTZ camera.
        stream: "main" (high quality) or "sub" (low quality / sub-stream).

    Returns:
        Full RTSP URL string with credentials embedded.
    """
    if camera == 2:
        user = settings.camera2_username
        pwd = _encode(settings.camera2_password)
        ip = settings.camera2_ip
        port = settings.camera2_rtsp_port
        path = settings.rtsp2_main_path if stream == "main" else settings.rtsp2_sub_path
    else:
        user = settings.camera_username
        pwd = _encode(settings.camera_password)
        ip = settings.camera_ip
        port = settings.camera_rtsp_port
        path = settings.rtsp_main_path if stream == "main" else settings.rtsp_sub_path

    return f"rtsp://{user}:{pwd}@{ip}:{port}{path}"
