"""
FastAPI entry point for the unified Python-only camera service.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import startup_check
from camera.audio import AudioClient
from camera.camera2_control import Camera2ControlClient
from camera.ir import IRClient
from camera.ptz import PTZClient
from camera.recording import RecordingManager
from config import settings
from routes.admin_api import router as admin_api_router
from routes.auth import router as auth_router
from routes.camera_control import router as camera_control_router
from routes.config_api import router as config_api_router
from routes.customer_portal import router as customer_portal_router
from routes.esp_config import render_help_esp1_page, router as esp_config_router
from routes.recordings import router as recordings_router
from routes.superadmin_api import router as superadmin_api_router
from routes.trigger import router as trigger_router
from routes.web_api import router as web_api_router
from services.alpr_service import ALPRService
from services.cleanup_service import cleanup_loop
from services.customer_portal import CustomerPortalService
from services.workflow import WorkflowService


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("tedde").setLevel(logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_check.run_all()

    recording_manager = RecordingManager()
    audio_client = AudioClient()
    ptz_client = PTZClient()
    ir_client = IRClient()
    camera2_control = Camera2ControlClient()
    alpr_service = ALPRService()
    customer_portal = CustomerPortalService()
    await customer_portal.initialize()
    workflow = WorkflowService(
        recording_manager=recording_manager,
        alpr_service=alpr_service,
    )

    app.state.recording_manager = recording_manager
    app.state.audio_client = audio_client
    app.state.ptz_client = ptz_client
    app.state.ir_client = ir_client
    app.state.camera2_control = camera2_control
    app.state.alpr_service = alpr_service
    app.state.customer_portal = customer_portal
    # Keep legacy alias so existing routes still work
    app.state.customer_portal_service = customer_portal
    app.state.workflow = workflow

    if settings.auto_day_mode_on_start:
        logger.info("[STARTUP] AUTO_DAY_MODE_ON_START=1 - forcing day mode on Camera 2")
        try:
            ok = await ir_client.set_day_mode()
            if ok:
                logger.info("[STARTUP] Camera 2 set to day mode")
            else:
                logger.warning("[STARTUP] Camera 2 rejected day mode change")
        except Exception as exc:
            logger.warning("[STARTUP] Could not set day mode: %s", exc)

    # Start auto-cleanup background task
    cleanup_task = asyncio.create_task(cleanup_loop(customer_portal))
    logger.info("[STARTUP] Auto-cleanup background task started")

    yield

    logger.info("[SHUTDOWN] Stopping active sessions")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    await recording_manager.stop_all()
    await audio_client.close_session()
    logger.info("[SHUTDOWN] Done")


app = FastAPI(
    title="Tedde Unified Camera Service",
    description="FastAPI-only dashboard, ESP workflow, camera control, and ALPR runtime.",
    version="3.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/public", StaticFiles(directory=settings.public_dir_abs), name="public")
app.mount("/snapshots", StaticFiles(directory=settings.snapshot_dir_abs), name="snapshots")
app.mount("/recordings", StaticFiles(directory=settings.recordings_dir_abs), name="recordings")
app.mount("/events", StaticFiles(directory=settings.events_dir_abs), name="events")

# Auth (login/logout)
app.include_router(auth_router)

# Admin dashboards
app.include_router(config_api_router)
app.include_router(admin_api_router)
app.include_router(superadmin_api_router)

# Core routes
app.include_router(trigger_router)
app.include_router(esp_config_router)
app.include_router(recordings_router)
app.include_router(camera_control_router)
app.include_router(web_api_router)
app.include_router(customer_portal_router)


# ── Exception handler for auth redirects ─────────────────────────
# HTTPException(303) from auth dependencies gets converted to a proper redirect
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == status.HTTP_303_SEE_OTHER and "Location" in (exc.headers or {}):
        return RedirectResponse(
            url=exc.headers["Location"],
            status_code=status.HTTP_303_SEE_OTHER,
        )
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.get("/help-esp1", include_in_schema=False)
async def help_esp1(request: Request) -> HTMLResponse:
    """Bookmark: server base URL + optional ESP IP from .env (search "help-esp1")."""
    return HTMLResponse(content=render_help_esp1_page(request))


@app.get("/health", summary="Health check")
async def health() -> dict:
    return {"status": startup_check.get_results().get("overall", "unknown")}


@app.get("/api/health", summary="Detailed health check")
async def health_detailed() -> dict:
    return await startup_check.run_all()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.py_server_port,
        reload=True,
        log_level="info",
    )
