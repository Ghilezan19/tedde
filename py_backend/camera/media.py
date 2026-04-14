"""
ffmpeg-backed media helpers used by the FastAPI routes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from fastapi import Request

from camera.rtsp import build_rtsp_url
from config import settings

logger = logging.getLogger(__name__)

JPEG_SOI = (0xFF, 0xD8)
JPEG_EOI = (0xFF, 0xD9)


def sanitize_stem(value: str, fallback: str = "snapshot") -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    safe = safe.strip("._")
    return safe or fallback


def find_marker(buffer: bytearray, marker: tuple[int, int], start_index: int = 0) -> int:
    for i in range(start_index, len(buffer) - 1):
        if buffer[i] == marker[0] and buffer[i + 1] == marker[1]:
            return i
    return -1


async def _terminate_process(proc: asyncio.subprocess.Process | None) -> None:
    if proc is None or proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=3.0)
    except asyncio.TimeoutError:
        proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()


async def _log_ffmpeg_stderr(proc: asyncio.subprocess.Process, prefix: str) -> None:
    if proc.stderr is None:
        return
    async for line in proc.stderr:
        text = line.decode(errors="replace").strip()
        if not text:
            continue
        lower = text.lower()
        if any(token in lower for token in ("error", "failed", "invalid", "refused")):
            logger.error("[%s] %s", prefix, text)


async def capture_snapshot_bytes(camera: int = 1, quality: str = "main") -> bytes:
    rtsp_url = build_rtsp_url(camera=camera, stream=quality)
    args = [
        settings.ffmpeg_path,
        "-rtsp_transport", "tcp",
        "-timeout", "10000000",
        "-i", rtsp_url,
        "-frames:v", "1",
        "-vcodec", "mjpeg",
        "-f", "image2",
        "-q:v", "2",
        "-update", "1",
        "-y",
        "pipe:1",
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
    except asyncio.TimeoutError as exc:
        await _terminate_process(proc)
        raise TimeoutError("Timeout la snapshot") from exc

    # Do not read stderr in a parallel task here: communicate() already drains
    # stderr; concurrent reads cause "read() called while another coroutine...".
    if stderr:
        for line in stderr.decode(errors="replace").splitlines():
            text = line.strip()
            if not text:
                continue
            lower = text.lower()
            if any(token in lower for token in ("error", "failed", "invalid", "refused")):
                logger.error("[SNAPSHOT-CAM%s] %s", camera, text)

    if proc.returncode != 0 or not stdout:
        raise RuntimeError("Nu s-a putut captura snapshot-ul")
    return stdout


async def save_snapshot(camera: int, quality: str, filepath: Path) -> bytes:
    image = await capture_snapshot_bytes(camera=camera, quality=quality)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(image)
    return image


def list_snapshots() -> list[dict]:
    files = []
    for path in sorted(settings.snapshot_dir_abs.glob("*"), reverse=True):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        stat = path.stat()
        files.append(
            {
                "filename": path.name,
                "url": f"/snapshots/{path.name}",
                "size": stat.st_size,
                "created": int(stat.st_ctime * 1000),
                "created_at": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
            }
        )
    return files


async def probe_camera_status() -> dict:
    rtsp_url = build_rtsp_url(camera=1, stream="main")
    args = [
        settings.ffmpeg_path,
        "-rtsp_transport", "tcp",
        "-timeout", "5000000",
        "-i", rtsp_url,
        "-frames:v", "1",
        "-f", "null",
        "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
    except asyncio.TimeoutError:
        await _terminate_process(proc)
        stderr = b""
    stderr_text = stderr.decode(errors="replace")
    video_match = re.search(r"Video:\s+([^\n]+)", stderr_text)
    audio_match = re.search(r"Audio:\s+([^\n]+)", stderr_text)
    is_online = proc.returncode == 0 or "Video:" in stderr_text
    return {
        "camera": {
            "ip": settings.camera_ip,
            "online": is_online,
            "mainStream": settings.rtsp_main_path,
            "subStream": settings.rtsp_sub_path,
        },
        "stream": {
            "video": video_match.group(1).strip() if video_match else None,
            "audio": audio_match.group(1).strip() if audio_match else None,
        },
    }


async def mjpeg_stream(
    request: Request,
    camera: int,
    quality: str,
    fps: int,
    width: int | None,
) -> AsyncIterator[bytes]:
    rtsp_url = build_rtsp_url(camera=camera, stream=quality)
    args = [
        settings.ffmpeg_path,
        "-rtsp_transport", "tcp",
        "-timeout", "5000000",
        "-i", rtsp_url,
        "-vcodec", "mjpeg",
        "-f", "mjpeg",
        "-q:v", "5",
        "-r", str(fps),
        "-an",
    ]
    if width:
        args.extend(["-vf", f"scale={width}:-2"])
    args.append("pipe:1")

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_task = asyncio.create_task(_log_ffmpeg_stderr(proc, f"STREAM-CAM{camera}"))
    buffer = bytearray()
    try:
        while True:
            if await request.is_disconnected():
                break
            chunk = await proc.stdout.read(65536)  # type: ignore[union-attr]
            if not chunk:
                break
            buffer.extend(chunk)
            while True:
                soi = find_marker(buffer, JPEG_SOI)
                if soi == -1:
                    break
                eoi = find_marker(buffer, JPEG_EOI, soi + 2)
                if eoi == -1:
                    break
                frame = bytes(buffer[soi : eoi + 2])
                del buffer[: eoi + 2]
                headers = (
                    b"--ffmpeg\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(frame)}\r\n\r\n".encode()
                )
                yield headers + frame + b"\r\n"
    finally:
        stderr_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stderr_task
        await _terminate_process(proc)


async def audio_listen_stream(request: Request, camera: int) -> AsyncIterator[bytes]:
    rtsp_url = build_rtsp_url(camera=camera, stream="sub")
    args = [
        settings.ffmpeg_path,
        "-rtsp_transport", "tcp",
        "-timeout", "5000000",
        "-i", rtsp_url,
        "-vn",
        "-acodec", "libmp3lame",
        "-ar", "16000",
        "-ac", "1",
        "-q:a", "5",
        "-f", "mp3",
        "pipe:1",
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_task = asyncio.create_task(_log_ffmpeg_stderr(proc, f"AUDIO-LISTEN-CAM{camera}"))
    try:
        while True:
            if await request.is_disconnected():
                break
            chunk = await proc.stdout.read(65536)  # type: ignore[union-attr]
            if not chunk:
                break
            yield chunk
    finally:
        stderr_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stderr_task
        await _terminate_process(proc)
