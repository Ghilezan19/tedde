"""
Manual recording control routes compatible with the existing dashboard.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from camera.recording import RecordingManager
from config import settings

router = APIRouter(prefix="/api")


def _get_manager(request: Request) -> RecordingManager:
    return request.app.state.recording_manager


@router.post("/record/start", summary="Start manual recording")
async def record_start(
    request: Request,
    camera: int = Query(default=1),
    quality: str = Query(default="main"),
    duration: Optional[int] = Query(default=None),
) -> dict:
    manager = _get_manager(request)
    try:
        meta = await manager.start_manual(camera=camera, stream=quality, duration=duration)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return {
        "success": True,
        "message": "Înregistrarea a pornit",
        "filename": meta.filename,
        "quality": quality,
        "startedAt": meta.started_at.isoformat(),
    }


@router.post("/record/stop", summary="Stop manual recording")
async def record_stop(request: Request) -> dict:
    manager = _get_manager(request)
    before = manager.manual_status()
    meta = await manager.stop_manual()
    if meta is None:
        raise HTTPException(status_code=400, detail="Nu există nicio înregistrare activă")

    duration = before.get("duration", 0)
    return {
        "success": True,
        "message": "Înregistrarea s-a oprit",
        "filename": meta.filename,
        "duration": f"{duration}s",
        "url": f"/recordings/{meta.filename}",
        "downloadUrl": f"/api/recordings/{meta.filename}",
    }


@router.get("/record/status", summary="Manual recording status")
async def record_status(request: Request) -> dict:
    return _get_manager(request).manual_status()


@router.get("/recordings", summary="List recordings")
async def list_recordings() -> dict:
    files = []
    for path in sorted(settings.recordings_dir_abs.glob("*.mp4"), reverse=True):
        stat = path.stat()
        files.append(
            {
                "filename": path.name,
                "url": f"/recordings/{path.name}",
                "downloadUrl": f"/api/recordings/{path.name}",
                "size": stat.st_size,
                "sizeMB": f"{stat.st_size / 1024 / 1024:.2f}",
                "created": int(stat.st_ctime * 1000),
                "created_at": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
            }
        )
    return {"count": len(files), "files": files}


@router.get("/recordings/{filename}", summary="Download recording")
async def get_recording(filename: str) -> FileResponse:
    safe_name = Path(filename).name
    target = settings.recordings_dir_abs / safe_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="Fișierul nu există")
    return FileResponse(
        path=target,
        media_type="video/mp4",
        filename=safe_name,
    )


async def _delete_recording(filename: str) -> dict:
    safe_name = Path(filename).name
    target = settings.recordings_dir_abs / safe_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="Fișierul nu există")
    target.unlink()
    return {"success": True, "message": f"{safe_name} șters"}


@router.post("/recordings/{filename}/delete", summary="Delete recording")
async def delete_recording_post(filename: str) -> dict:
    return await _delete_recording(filename)


@router.delete("/recordings/{filename}", summary="Delete recording")
async def delete_recording_delete(filename: str) -> dict:
    return await _delete_recording(filename)
