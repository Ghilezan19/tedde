"""
Central configuration — reads every parameter from .env via Pydantic Settings.
No hard-coded values anywhere else in the codebase; import `settings` instead.
"""

from pathlib import Path
from typing import Optional

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Allow running the backend from either the repo root or the py_backend/ folder.
_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # Server
    # ------------------------------------------------------------------ #
    py_server_port: int = Field(default=8000, description="Port FastAPI")

    # ------------------------------------------------------------------ #
    # Paths
    # ------------------------------------------------------------------ #
    recordings_dir: Path = Field(default=Path("./recordings"))
    snapshot_dir: Path = Field(default=Path("./snapshots"))
    events_dir: Path = Field(default=Path("./events"))

    # ffmpeg binary
    ffmpeg_path: str = Field(default="/opt/homebrew/bin/ffmpeg")

    # ------------------------------------------------------------------ #
    # Camera 1  (fixed, HiLook)
    # ------------------------------------------------------------------ #
    camera_ip: str = Field(default="192.168.100.105")
    camera_username: str = Field(default="admin")
    camera_password: str = Field(default="")
    camera_rtsp_port: int = Field(default=554)
    rtsp_main_path: str = Field(default="/Streaming/channels/101")
    rtsp_sub_path: str = Field(default="/Streaming/channels/102")

    # ------------------------------------------------------------------ #
    # Camera 2  (PTZ, HiLook PTZ-N2C400I-W)
    # ------------------------------------------------------------------ #
    camera2_ip: str = Field(default="10.112.50.88")
    camera2_username: str = Field(default="admin")
    camera2_password: str = Field(default="")
    camera2_rtsp_port: int = Field(default=554)
    camera2_http_port: int = Field(default=80)
    camera2_sdk_port: int = Field(default=8000)
    rtsp2_main_path: str = Field(default="/Streaming/channels/101")
    rtsp2_sub_path: str = Field(default="/Streaming/channels/102")
    camera2_onvif_profile: str = Field(default="Profile_1")

    # ------------------------------------------------------------------ #
    # Recording
    # ------------------------------------------------------------------ #
    recording_duration_seconds: int = Field(
        default=10,
        description="Default duration (seconds) for a triggered recording.",
    )
    # If set, GET /api/esp/config returns this for countdown_seconds (LCD on ESP).
    # If None, countdown_seconds == recording_duration_seconds (one knob in .env).
    esp_countdown_seconds: Optional[int] = Field(
        default=None,
        description="Optional LCD countdown; defaults to recording_duration_seconds when unset.",
    )

    workflow_record_stream: str = Field(
        default="main",
        description="Stream quality used for the parallel workflow recordings.",
    )

    # ------------------------------------------------------------------ #
    # Audio TTS
    # ------------------------------------------------------------------ #
    # Camera implicita pentru inregistrarea declanșata de ESP
    default_recording_camera: int = Field(
        default=2,
        description="Camera folosita la trigger ESP (1=fixa, 2=PTZ).",
    )

    tts_enabled: int = Field(
        default=0,
        description="1 = audio TTS prin camera activat, 0 = dezactivat.",
    )

    auto_day_mode_on_start: int = Field(
        default=1,
        description="1 = forteaza color (zi, IR off) la pornirea serverului.",
    )
    tts_language: str = Field(default="ro")
    tts_start_message: str = Field(default="Inregistrarea a inceput")
    tts_end_message: str = Field(default="Inregistrarea s-a finalizat cu succes")
    tts_volume: int = Field(default=100, ge=0, le=100)

    # ------------------------------------------------------------------ #
    # ALPR / events
    # ------------------------------------------------------------------ #
    alpr_enabled: int = Field(
        default=1,
        description="1 = ALPR runs on the workflow start snapshot, 0 = disabled.",
    )
    alpr_camera: int = Field(
        default=1,
        description="Camera used to capture the workflow ALPR snapshot.",
    )
    alpr_detector_conf_thresh: float = Field(
        default=0.1,
        ge=0.05,
        le=0.95,
        description="fast-alpr YOLO confidence (default lib=0.4). Lower helps small/distant plates.",
    )
    alpr_detector_cpu_only: int = Field(
        default=1,
        ge=0,
        le=1,
        description="1 = plate detector ONNX on CPUExecutionProvider only (avoids empty CoreML outputs on some Macs).",
    )
    alpr_upscale_retry: int = Field(
        default=1,
        ge=0,
        le=1,
        description="1 = dacă prima detectare e goală, reîncearcă pe imagine scalată (mai multe px pentru plăcuță).",
    )
    alpr_predict_upscale: float = Field(
        default=1.5,
        ge=1.05,
        le=2.5,
        description="Factor mărire pentru retry-ul ALPR (doar în RAM, nu schimbă fișierul snapshot).",
    )

    # ------------------------------------------------------------------ #
    # PTZ workflow  (for future multi-location recording)
    # ------------------------------------------------------------------ #
    ptz_preset_home: str = Field(default="1", description="ONVIF preset token — home position")
    ptz_preset_secondary: str = Field(default="2", description="ONVIF preset token — secondary position")
    ptz_settle_seconds: int = Field(
        default=3,
        description="Seconds to wait after PTZ move before starting recording.",
    )
    ptz_secondary_recording_seconds: int = Field(
        default=120,
        description="Recording duration at secondary PTZ position.",
    )
    ptz_home_recording_seconds: int = Field(
        default=10,
        description="Recording duration at home PTZ position.",
    )

    # ------------------------------------------------------------------ #
    # Computed helpers
    # ------------------------------------------------------------------ #
    @computed_field  # type: ignore[prop-decorator]
    @property
    def recordings_dir_abs(self) -> Path:
        """Absolute path to the recordings folder, resolved relative to repo root."""
        base = Path(__file__).parent.parent
        return (base / self.recordings_dir).resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def snapshot_dir_abs(self) -> Path:
        base = Path(__file__).parent.parent
        return (base / self.snapshot_dir).resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def events_dir_abs(self) -> Path:
        base = Path(__file__).parent.parent
        return (base / self.events_dir).resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def public_dir_abs(self) -> Path:
        return (Path(__file__).parent.parent / "public").resolve()


# Singleton — import this everywhere
settings = Settings()

# Ensure output directories exist at import time
settings.recordings_dir_abs.mkdir(parents=True, exist_ok=True)
settings.snapshot_dir_abs.mkdir(parents=True, exist_ok=True)
settings.events_dir_abs.mkdir(parents=True, exist_ok=True)
