"""
Central configuration — reads every parameter from .env via Pydantic Settings.
No hard-coded values anywhere else in the codebase; import `settings` instead.
"""

from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Allow running the backend from either the repo root or the py_backend/ folder.
_ENV_FILE = Path(__file__).parent.parent / ".env"

# Hub `open-image-models` — must match PlateDetectorModel in that package.
AlprPlateDetectorModel = Literal[
    "yolo-v9-s-608-license-plate-end2end",
    "yolo-v9-t-640-license-plate-end2end",
    "yolo-v9-t-512-license-plate-end2end",
    "yolo-v9-t-416-license-plate-end2end",
    "yolo-v9-t-384-license-plate-end2end",
    "yolo-v9-t-256-license-plate-end2end",
]

# Hub `fast-plate-ocr` ONNX names (subset used with fast_alpr).
AlprOcrModel = Literal[
    "cct-s-v2-global-model",
    "cct-xs-v2-global-model",
    "cct-s-v1-global-model",
    "cct-xs-v1-global-model",
    "cct-s-relu-v1-global-model",
    "cct-xs-relu-v1-global-model",
    "argentinian-plates-cnn-model",
    "argentinian-plates-cnn-synth-model",
    "european-plates-mobile-vit-v2-model",
    "global-plates-mobile-vit-v2-model",
]


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
    customer_portal_db_path: Path = Field(default=Path("./data/customer_portal.sqlite3"))

    # ffmpeg binary
    ffmpeg_path: str = Field(default="/opt/homebrew/bin/ffmpeg")

    # ------------------------------------------------------------------ #
    # Camera 1  (fixed, HiLook)
    # ------------------------------------------------------------------ #
    camera_ip: str = Field(default="192.168.100.105")
    camera_username: str = Field(default="admin")
    camera_password: str = Field(default="")
    camera_rtsp_port: int = Field(default=554)
    camera1_http_port: int = Field(
        default=80,
        description="HTTP port for Camera 1 ISAPI (TwoWayAudio when AUDIO_ISAPI_CAMERA=1).",
    )
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
    esp_device_ip: Optional[str] = Field(
        default=None,
        description="Optional: last known ESP32 LAN IP (manual); shown on /help-esp1.",
    )
    esp_help_note: str = Field(
        default="",
        description="Optional label/note for /help-esp1 (e.g. location).",
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

    audio_isapi_camera: int = Field(
        default=2,
        ge=1,
        le=2,
        description="Which camera receives ISAPI TwoWayAudio / live talk / TTS (1=fixed, 2=PTZ).",
    )

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
    alpr_detector_model: AlprPlateDetectorModel = Field(
        default="yolo-v9-t-384-license-plate-end2end",
        description="ONNX plate detector from open-image-models hub (see fast_alpr detector_model).",
    )
    alpr_ocr_model: AlprOcrModel = Field(
        default="cct-xs-v2-global-model",
        description="OCR model name from fast-plate-ocr hub (see fast_alpr ocr_model).",
    )

    # ------------------------------------------------------------------ #
    # Customer portal / SMS
    # ------------------------------------------------------------------ #
    public_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL used when generating customer-facing share links.",
    )
    portal_path_prefix: str = Field(
        default="/verificare",
        description="Path prefix for the public customer portal.",
    )
    customer_link_ttl_days: int = Field(
        default=30,
        ge=1,
        description="Number of days before a customer link expires.",
    )
    sms_backend: Literal["mock", "custom_http"] = Field(
        default="mock",
        description="SMS backend used when sending customer share links.",
    )
    sms_http_url: str = Field(default="")
    sms_http_method: str = Field(default="POST")
    sms_http_headers_json: str = Field(default="{}")
    sms_http_body_template: str = Field(default="")
    portal_brand_name: str = Field(default="TEDDE AUTO")
    portal_footer_phone: str = Field(default="0744 658 650")
    portal_footer_email: str = Field(default="office@tedde-auto.ro")
    portal_footer_address: str = Field(default="Satchinez, str. Daliei, nr. 27, jud. Timis")
    portal_footer_hours: str = Field(
        default="Luni - Vineri: 08:30 - 17:00 / Sambata: 08:30 - 13:00 / Duminica: Inchis"
    )
    portal_theme_accent: str = Field(default="#59c7e8")
    portal_theme_dark: str = Field(default="#2f2f2f")
    portal_logo_url: str = Field(
        default="/public/logo.png",
        description="URL path (under app mount) for customer portal header logo.",
    )
    portal_bumper_video_url: str = Field(
        default="/public/intro-outro.mp4",
        description="Intro/outro clip URL; played before and after each camera recording in the portal.",
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
    def customer_portal_db_abs(self) -> Path:
        base = Path(__file__).parent.parent
        return (base / self.customer_portal_db_path).resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def public_dir_abs(self) -> Path:
        return (Path(__file__).parent.parent / "public").resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def templates_dir_abs(self) -> Path:
        return (Path(__file__).parent.parent / "py_backend" / "templates").resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def portal_path_prefix_normalized(self) -> str:
        prefix = (self.portal_path_prefix or "/verificare").strip()
        if not prefix:
            return "/verificare"
        if not prefix.startswith("/"):
            prefix = f"/{prefix}"
        if prefix != "/":
            prefix = prefix.rstrip("/")
        return prefix


# Singleton — import this everywhere
settings = Settings()

# Ensure output directories exist at import time
settings.recordings_dir_abs.mkdir(parents=True, exist_ok=True)
settings.snapshot_dir_abs.mkdir(parents=True, exist_ok=True)
settings.events_dir_abs.mkdir(parents=True, exist_ok=True)
settings.customer_portal_db_abs.parent.mkdir(parents=True, exist_ok=True)
