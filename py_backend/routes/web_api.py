"""
Browser-facing routes served directly by FastAPI.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from camera.audio import AudioClient
from camera.camera2_control import Camera2ControlClient
from camera.ir import IRClient
from camera.media import (
    audio_listen_stream,
    capture_snapshot_bytes,
    list_snapshots,
    mjpeg_stream,
    probe_camera_status,
    sanitize_stem,
    save_snapshot,
)
from camera.ptz import PTZClient
from config import settings
from debug_agent_log import agent_log
from services.workflow import WorkflowMode, WorkflowService

logger = logging.getLogger(__name__)

router = APIRouter()


def _ptz(request: Request) -> PTZClient:
    return request.app.state.ptz_client


def _audio(request: Request) -> AudioClient:
    return request.app.state.audio_client


def _ir(request: Request) -> IRClient:
    return request.app.state.ir_client


def _workflow(request: Request) -> WorkflowService:
    return request.app.state.workflow


def _camera2(request: Request) -> Camera2ControlClient:
    return request.app.state.camera2_control


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3] + "Z"


@router.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(settings.public_dir_abs / "index.html")


@router.get("/api/stream")
async def api_stream(
    request: Request,
    camera: int = 1,
    quality: str = "sub",
    fps: int = 5,
    width: int | None = None,
) -> StreamingResponse:
    media = mjpeg_stream(
        request=request,
        camera=camera,
        quality="main" if quality == "main" else "sub",
        fps=max(1, fps),
        width=width,
    )
    return StreamingResponse(media, media_type="multipart/x-mixed-replace; boundary=ffmpeg")


@router.get("/api/snapshot")
async def api_snapshot(
    camera: int = 1,
    quality: str = "main",
    save: str = "false",
    filename: str | None = None,
) -> Response:
    try:
        image = await capture_snapshot_bytes(camera=camera, quality="sub" if quality == "sub" else "main")
    except TimeoutError:
        return JSONResponse(status_code=504, content={"error": "Timeout la snapshot"})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": "Nu s-a putut captura snapshot-ul", "details": str(exc)})

    if save == "true":
        stem = sanitize_stem(filename or f"snapshot_{_timestamp_slug()}")
        filepath = settings.snapshot_dir_abs / f"{stem}.jpg"
        filepath.write_bytes(image)

    headers = {"Content-Disposition": "inline"}
    return Response(content=image, media_type="image/jpeg", headers=headers)


@router.get("/api/snapshot/save")
async def api_snapshot_save(
    camera: int = 1,
    quality: str = "main",
    filename: str | None = None,
) -> dict:
    stem = sanitize_stem(filename or f"snapshot_{_timestamp_slug()}")
    filepath = settings.snapshot_dir_abs / f"{stem}.jpg"
    try:
        image = await save_snapshot(camera=camera, quality="sub" if quality == "sub" else "main", filepath=filepath)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": "Nu s-a putut salva snapshot-ul", "details": str(exc)})
    return {
        "success": True,
        "filename": filepath.name,
        "path": str(filepath),
        "size": len(image),
        "url": f"/snapshots/{filepath.name}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/snapshots")
async def api_snapshots() -> dict:
    files = list_snapshots()
    return {"count": len(files), "files": files}


class AlprTestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    quality: Literal["main", "sub"] = "main"


@router.post("/api/alpr/test", summary="Capture snapshot and run ALPR (manual test)")
async def api_alpr_test(
    request: Request,
    body: AlprTestBody = Body(default_factory=AlprTestBody),
) -> dict:
    payload = body
    cam = int(settings.alpr_camera)
    filepath = settings.snapshot_dir_abs / "alpr_test_last.jpg"
    qual = "sub" if payload.quality == "sub" else "main"
    try:
        await save_snapshot(camera=cam, quality=qual, filepath=filepath)
    except TimeoutError:
        return JSONResponse(
            status_code=504,
            content={"error": "Timeout la snapshot", "details": "ffmpeg nu a returnat cadru la timp"},
        )
    except Exception as exc:
        logger.exception("ALPR test snapshot failed")
        return JSONResponse(
            status_code=500,
            content={"error": "Nu s-a putut salva snapshot-ul", "details": str(exc)},
        )

    alpr_service = request.app.state.alpr_service
    retried_main = False
    try:
        result = await alpr_service.predict_image(filepath)
        # Sub stream: plate bbox often below detector threshold; retry once on main.
        if (
            qual == "sub"
            and result.get("enabled")
            and not result.get("plates")
        ):
            logger.info(
                "[ALPR/test] Zero plates on sub snapshot cam=%s — retrying capture on main",
                cam,
            )
            await save_snapshot(camera=cam, quality="main", filepath=filepath)
            result = await alpr_service.predict_image(filepath)
            qual = "main"
            retried_main = True
    except Exception as exc:
        logger.exception("ALPR test inference failed")
        return JSONResponse(
            status_code=500,
            content={"error": "ALPR a eșuat", "details": str(exc)},
        )

    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    out = dict(result)
    out["snapshot_url"] = f"/snapshots/{filepath.name}?t={ts_ms}"
    out["camera"] = cam
    out["quality"] = qual
    out["alpr_retried_with_main"] = retried_main
    return out


@router.get("/api/status")
async def api_status() -> dict:
    started = datetime.now(timezone.utc)
    try:
        status = await probe_camera_status()
        elapsed = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        status["camera"]["responseTime"] = f"{elapsed}ms"
        return status
    except Exception as exc:
        logger.exception("[api/status] probe failed: %s", exc)
        return {
            "camera": {
                "ip": settings.camera_ip,
                "online": False,
                "mainStream": settings.rtsp_main_path,
                "subStream": settings.rtsp_sub_path,
                "responseTime": "error",
                "error": str(exc),
            },
            "stream": {"video": None, "audio": None},
        }


@router.get("/api/info")
async def api_info() -> dict:
    return {
        "server": {"port": settings.py_server_port, "version": "3.0.0-python"},
        "camera1": {
            "ip": settings.camera_ip,
            "rtspPort": settings.camera_rtsp_port,
            "mainStream": settings.rtsp_main_path,
            "subStream": settings.rtsp_sub_path,
        },
        "camera2": {
            "ip": settings.camera2_ip,
            "httpPort": settings.camera2_http_port,
            "rtspPort": settings.camera2_rtsp_port,
            "mainStream": settings.rtsp2_main_path,
            "subStream": settings.rtsp2_sub_path,
        },
    }


@router.post("/api/ptz/move")
async def api_ptz_move(request: Request) -> dict:
    body = await request.json()
    direction = body.get("direction", "up")
    speed = int(body.get("speed", 5))
    try:
        success = await _ptz(request).continuous_move(direction=direction, speed=speed)
        if not success:
            return JSONResponse(status_code=502, content={"success": False, "error": "Camera returned 502"})
        return {"success": True, "direction": direction, "speed": max(1, min(7, speed))}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": "PTZ connection failed", "details": str(exc)})


@router.post("/api/ptz/stop")
async def api_ptz_stop(request: Request) -> dict:
    try:
        await _ptz(request).stop()
        return {"success": True}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": "PTZ stop failed", "details": str(exc)})


@router.post("/api/ptz/goto")
async def api_ptz_goto(request: Request) -> dict:
    body = await request.json()
    token = body.get("token") or str(body.get("preset", "1"))
    try:
        success = await _ptz(request).goto_preset(str(token))
        return {"success": success, "token": str(token)}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": "GotoPreset failed", "details": str(exc)})


@router.post("/api/ptz/position")
async def api_ptz_position(request: Request) -> dict:
    body = await request.json()
    try:
        success = await _ptz(request).absolute_move(
            x=float(body.get("x", 0)),
            y=float(body.get("y", 0)),
            zoom=float(body.get("zoom", 0)),
        )
        return {"success": success}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": "AbsoluteMove failed", "details": str(exc)})


@router.post("/api/ptz/zoom")
async def api_ptz_zoom(request: Request) -> dict:
    body = await request.json()
    direction = body.get("direction", "in")
    speed = int(body.get("speed", 5))
    try:
        success = await _ptz(request).zoom(direction=direction, speed=speed)
        return {"success": success, "direction": direction}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": "PTZ zoom failed", "details": str(exc)})


@router.post("/api/ptz/focus")
async def api_ptz_focus() -> dict:
    return {"success": False, "message": "Focus control not available on this camera (fixed lens)"}


@router.get("/api/ptz/status")
async def api_ptz_status(request: Request) -> dict:
    try:
        result = await _ptz(request).get_status()
        return {"success": result["status"] == 200, "raw": result["raw"]}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": "PTZ status failed", "details": str(exc)})


@router.get("/api/ptz/presets")
async def api_ptz_presets(request: Request) -> dict:
    try:
        presets = await _ptz(request).list_presets()
        return {"count": len(presets), "presets": presets}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": "Failed to list presets", "details": str(exc)})


@router.post("/api/ptz/presets")
async def api_ptz_set_preset(request: Request) -> dict:
    body = await request.json()
    try:
        result = await _ptz(request).set_preset(name=str(body.get("name", "Preset")), token=body.get("token"))
        status = 200 if result["success"] else 502
        return JSONResponse(status_code=status, content=result)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": "SetPreset failed", "details": str(exc)})


@router.delete("/api/ptz/presets/{token}")
async def api_ptz_delete_preset(token: str, request: Request) -> dict:
    try:
        success = await _ptz(request).remove_preset(token)
        return {"success": success}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": "RemovePreset failed", "details": str(exc)})


@router.post("/api/audio/open")
async def api_audio_open(
    request: Request,
    camera: Optional[int] = Query(default=None, description="1=fixed IPC, 2=PTZ; default from AUDIO_ISAPI_CAMERA"),
) -> dict:
    audio = _audio(request)
    if audio.status()["open"]:
        return {"success": True, "sessionId": audio.status()["sessionId"], "message": "Already open"}
    cam_arg = camera if camera in (1, 2) else None
    opened = await audio.open_session(camera=cam_arg)
    # #region agent log
    st = audio.status()
    agent_log(
        hypothesis_id="A",
        location="web_api.api_audio_open",
        message="open_result",
        data={
            "opened": opened,
            "detail": (audio.last_open_error or "")[:240],
            "isapiCamera": st.get("isapiCamera"),
            "isapiTarget": st.get("isapiTarget"),
            "queryCamera": cam_arg,
        },
    )
    # #endregion
    if not opened:
        payload: dict = {"error": "Failed to open audio session"}
        detail = audio.last_open_error
        if detail:
            payload["detail"] = detail
            if "404" in detail:
                payload["hint"] = (
                    "TwoWayAudio lipsește pe această cameră/port HTTP (des întâlnit la PTZ HiLook). "
                    "Încearcă AUDIO_ISAPI_CAMERA=1 dacă IPC-ul fix suportă difuzorul, alt port HTTP, "
                    "firmware sau difuzor extern."
                )
        return JSONResponse(status_code=502, content=payload)
    return {"success": True, "sessionId": audio.status()["sessionId"]}


@router.post("/api/audio/close")
async def api_audio_close(request: Request) -> dict:
    await _audio(request).close_session()
    return {"success": True}


@router.get("/api/audio/status")
async def api_audio_status(request: Request) -> dict:
    return _audio(request).status()


@router.get("/api/audio/listen")
async def api_audio_listen(request: Request, camera: int = 2) -> StreamingResponse:
    media = audio_listen_stream(request, camera=camera)
    return StreamingResponse(media, media_type="audio/mpeg")


@router.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket) -> None:
    await websocket.accept()
    audio: AudioClient = websocket.app.state.audio_client
    _rx_dbg = 0
    try:
        while True:
            data = await websocket.receive_bytes()
            _rx_dbg += 1
            if _rx_dbg <= 10:
                # #region agent log
                st = audio.status()
                agent_log(
                    hypothesis_id="B",
                    location="web_api.ws_audio",
                    message="ws_receive",
                    data={
                        "seq": _rx_dbg,
                        "byteLen": len(data),
                        "sessionOpen": st.get("open"),
                    },
                )
                # #endregion
            if not audio.status()["open"]:
                continue
            await audio.send_pcm16_chunk(data)
    except WebSocketDisconnect:
        logger.info("[AUDIO-WS] Browser disconnected")
    except Exception as exc:
        logger.error("[AUDIO-WS] Error: %s", exc)
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()


@router.get("/api/light")
async def api_light_get(request: Request):
    try:
        result = await _camera2(request).get_light()
        return {
            "mode": result["mode"],
            "brightness": result["brightness"],
            "irBrightness": result["irBrightness"],
            "raw": result["raw"],
        }
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": "Failed to get light settings", "details": str(exc)})


@router.post("/api/light")
async def api_light_set(request: Request):
    body = await request.json()
    try:
        result = await _camera2(request).set_light(
            mode=str(body.get("mode", "ir")),
            brightness=int(body.get("brightness", 50)),
        )
        if result["status"] not in (200, 201):
            return JSONResponse(status_code=result["status"], content={"error": "Failed to set light", "details": result["data"]})
        return {"success": True, "mode": result["mode"], "brightness": result["brightness"]}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": "Failed to set light", "details": str(exc)})


def _normalize_ir_mode(raw: str | None) -> str:
    mode = (raw or "AUTO").upper()
    mapping = {"ON": "DAY", "OFF": "NIGHT", "AUTO": "AUTO", "DAY": "DAY", "NIGHT": "NIGHT"}
    return mapping.get(mode, "AUTO")


@router.get("/api/image/settings")
async def api_image_settings_get(request: Request):
    try:
        result = await _camera2(request).get_image_settings()
        ir_status = await _ir(request).get_mode()
        return {
            "brightness": result["brightness"],
            "contrast": result["contrast"],
            "saturation": result["saturation"],
            "hue": result["hue"],
            "sharpness": result["sharpness"],
            "irCutFilter": _normalize_ir_mode(ir_status.get("ir_cut_filter")),
            "wdr": result["wdr"],
            "raw": result["raw"],
        }
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": "Failed to get image settings", "details": str(exc)})


@router.put("/api/image/settings")
async def api_image_settings_put(request: Request):
    body = await request.json()
    try:
        result = await _camera2(request).set_image_settings(
            brightness=body.get("brightness"),
            contrast=body.get("contrast"),
            saturation=body.get("saturation"),
            hue=body.get("hue"),
            sharpness=body.get("sharpness"),
        )
        if result["status"] not in (200, 201):
            return JSONResponse(status_code=result["status"], content={"error": "Failed to save settings", "details": result["data"]})

        ir_cut = str(body.get("irCutFilter", "AUTO")).upper()
        if ir_cut == "DAY":
            await _ir(request).set_day_mode()
        elif ir_cut == "NIGHT":
            await _ir(request).set_night_mode()
        else:
            await _ir(request).set_auto_mode()

        return {"success": True}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": "Failed to save settings", "details": str(exc)})


@router.get("/api/device/info")
async def api_device_info(request: Request):
    try:
        result = await _camera2(request).get_device_info()
        if result["status"] != 200:
            return JSONResponse(status_code=result["status"], content={"error": "Failed to get device info", "details": result["raw"]})
        return {
            "manufacturer": result["manufacturer"],
            "model": result["model"],
            "firmwareVersion": result["firmwareVersion"],
            "serialNumber": result["serialNumber"],
            "hardwareId": result["hardwareId"],
            "ip": result["ip"],
        }
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": "Failed to get device info", "details": str(exc)})


async def _probe_http(host: str, port: int, path: str) -> dict:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3.0)
        request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode()
        writer.write(request)
        await writer.drain()
        data = await asyncio.wait_for(reader.read(256), timeout=3.0)
        writer.close()
        return {"success": True, "status": data.decode(errors="ignore").split(" ")[1] if data else "unknown"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@router.get("/api/diagnostic/camera2")
async def api_diagnostic_camera2() -> dict:
    http80, sdk8000, ptz = await asyncio.gather(
        _probe_http(settings.camera2_ip, settings.camera2_http_port, "/"),
        _probe_http(settings.camera2_ip, settings.camera2_sdk_port, "/"),
        _probe_http(settings.camera2_ip, settings.camera2_http_port, "/ISAPI/PTZCtrl/channels/1/status"),
    )
    return {
        "camera": 2,
        "config": {
            "ip": settings.camera2_ip,
            "username": settings.camera2_username,
            "password": "***",
            "rtspPort": settings.camera2_rtsp_port,
            "httpPort": settings.camera2_http_port,
            "sdkPort": settings.camera2_sdk_port,
        },
        "tests": {
            f"HTTP Port {settings.camera2_http_port}": http80,
            f"SDK Port {settings.camera2_sdk_port}": sdk8000,
            "PTZ ISAPI": ptz,
        },
    }


@router.post("/api/workflow/trigger")
async def api_workflow_trigger(request: Request) -> dict:
    workflow = _workflow(request)
    if workflow.is_busy():
        return JSONResponse(status_code=409, content={"success": False, "error": "Workflow already active"})
    duration_override: int | None = None
    try:
        body = await request.json()
        if isinstance(body, dict) and body.get("duration_seconds") is not None:
            duration_override = max(5, min(600, int(body["duration_seconds"])))
    except Exception:
        pass
    try:
        run = await workflow.trigger(
            mode=WorkflowMode.SIMPLE,
            source="web",
            duration=duration_override,
        )
    except RuntimeError as exc:
        return JSONResponse(status_code=409, content={"success": False, "error": str(exc)})
    return {"success": True, "session_id": run.session_id}


@router.get("/api/workflow/status")
async def api_workflow_status(request: Request) -> dict:
    return _workflow(request).status()


def _find_camera_video(event_dir: Path, cam: int) -> Optional[str]:
    """Look up camera video, supporting both new (<plate>_cam1.mp4) and legacy (camera1.mp4) names."""
    legacy = event_dir / f"camera{cam}.mp4"
    if legacy.exists():
        return legacy.name
    # New naming: any *_cam{N}.mp4 (ordered: most recently modified wins if multiple)
    matches = sorted(
        event_dir.glob(f"*_cam{cam}.mp4"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if matches:
        return matches[0].name
    return None


def _read_event_payload(path: Path) -> dict:
    alpr_json = path / "alpr.json"
    payload = {}
    stat = path.stat()
    if alpr_json.exists():
        try:
            payload = json.loads(alpr_json.read_text())
        except Exception:
            payload = {}

    cam1_name = _find_camera_video(path, 1)
    cam2_name = _find_camera_video(path, 2)

    return {
        "event_id": path.name,
        "folder": path.name,
        "created": int(stat.st_ctime * 1000),
        "created_at": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
        "selected_plate": payload.get("selected_plate") or "UNKNOWN",
        "snapshot_url": f"/events/{path.name}/alpr_start.jpg" if (path / "alpr_start.jpg").exists() else None,
        "alpr": payload,
        "videos": {
            "camera1": f"/events/{path.name}/{cam1_name}" if cam1_name else None,
            "camera2": f"/events/{path.name}/{cam2_name}" if cam2_name else None,
        },
    }


@router.get("/api/events")
async def api_events() -> dict:
    events = []
    paths = [
        path
        for path in settings.events_dir_abs.iterdir()
        if path.is_dir() and not path.name.startswith(".tmp_")
    ]
    for path in sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_dir() or path.name.startswith(".tmp_"):
            continue
        events.append(_read_event_payload(path))
    return {"count": len(events), "events": events}


@router.get("/api/events/{event_id}")
async def api_event_detail(event_id: str) -> dict:
    safe = Path(event_id).name
    target = settings.events_dir_abs / safe
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Event not found")
    return _read_event_payload(target)


# ── ESP Heartbeat ─────────────────────────────────────────────────
# The ESP32 firmware can POST its status here periodically.
# The Configure dashboard reads the last heartbeat via GET.

_esp_heartbeat_cache: dict = {}


class EspHeartbeatPayload(BaseModel):
    temp_c: Optional[float] = Field(default=None)
    fan_on: Optional[bool] = Field(default=None)
    wifi_ssid: Optional[str] = Field(default=None)
    countdown_seconds: Optional[int] = Field(default=None)
    state: Optional[str] = Field(default=None)
    fw: Optional[str] = Field(default=None)
    uptime_s: Optional[int] = Field(default=None)
    rssi: Optional[int] = Field(default=None)


@router.post("/api/esp/heartbeat", summary="ESP posts its current status")
async def esp_heartbeat_post(payload: EspHeartbeatPayload, request: Request) -> dict:
    """Receive a status heartbeat from the ESP32 device.

    Also captures the source IP so the dashboard can auto-discover ESP without
    requiring the ESP to run an HTTP server (port-80 scans would never find it).
    """
    source_ip = request.client.host if request.client else None
    _esp_heartbeat_cache.update({
        **payload.model_dump(exclude_none=True),
        "source_ip": source_ip,
        "received_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True}


@router.get("/api/esp/heartbeat", summary="Get latest ESP heartbeat")
async def esp_heartbeat_get() -> dict:
    """Return the last ESP heartbeat, or 404 if none received yet."""
    if not _esp_heartbeat_cache:
        raise HTTPException(status_code=404, detail="No ESP heartbeat received yet")

    received_at_str = _esp_heartbeat_cache.get("received_at")
    age_seconds: Optional[int] = None
    if received_at_str:
        try:
            received_dt = datetime.fromisoformat(received_at_str)
            diff = datetime.now(timezone.utc) - received_dt
            age_seconds = int(diff.total_seconds())
        except Exception:
            pass

    return {**_esp_heartbeat_cache, "age_seconds": age_seconds}
