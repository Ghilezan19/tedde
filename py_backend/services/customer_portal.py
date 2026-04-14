from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from camera.recording import workflow_output_status
from config import settings

logger = logging.getLogger(__name__)


def _mask_phone(value: str) -> str:
    digits = value.strip()
    if len(digits) <= 4:
        return "*" * len(digits)
    return f"{digits[:4]}***{digits[-2:]}"


class CustomerPortalError(Exception):
    pass


class CustomerPortalNotFound(CustomerPortalError):
    pass


class CustomerPortalConflict(CustomerPortalError):
    pass


class CustomerPortalForbidden(CustomerPortalError):
    pass


class CustomerPortalExpired(CustomerPortalError):
    pass


@dataclass
class SendResult:
    status: str
    error: str | None = None
    http_status: int | None = None


class MockSmsSender:
    async def send_sms(self, to: str, text: str) -> SendResult:
        logger.info("[SMS/mock] to=%s message_len=%s", _mask_phone(to), len(text))
        return SendResult(status="mocked")


class CustomHttpSmsSender:
    async def send_sms(self, to: str, text: str) -> SendResult:
        if not settings.sms_http_url:
            return SendResult(status="failed", error="SMS_HTTP_URL is not configured")

        try:
            headers = json.loads(settings.sms_http_headers_json or "{}")
            if not isinstance(headers, dict):
                raise ValueError("SMS_HTTP_HEADERS_JSON must be an object")
        except Exception as exc:
            return SendResult(status="failed", error=f"Invalid SMS_HTTP_HEADERS_JSON: {exc}")

        body_template = settings.sms_http_body_template or ""
        if not body_template:
            return SendResult(status="failed", error="SMS_HTTP_BODY_TEMPLATE is not configured")

        body = body_template.replace("{{to}}", to).replace("{{message}}", text)
        method = (settings.sms_http_method or "POST").upper()

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.request(
                    method=method,
                    url=settings.sms_http_url,
                    headers=headers,
                    content=body.encode("utf-8"),
                )
        except Exception as exc:
            logger.warning("[SMS/custom_http] request failed to=%s error=%s", _mask_phone(to), exc)
            return SendResult(status="failed", error=str(exc))

        if 200 <= response.status_code < 300:
            logger.info("[SMS/custom_http] sent to=%s status=%s", _mask_phone(to), response.status_code)
            return SendResult(status="sent", http_status=response.status_code)

        logger.warning(
            "[SMS/custom_http] failed to=%s status=%s",
            _mask_phone(to),
            response.status_code,
        )
        return SendResult(
            status="failed",
            error=f"Provider returned HTTP {response.status_code}",
            http_status=response.status_code,
        )


class CustomerPortalService:
    def __init__(self) -> None:
        self._db_path = settings.customer_portal_db_abs
        self._sms_sender = self._build_sms_sender()

    def _build_sms_sender(self):
        backend = (settings.sms_backend or "mock").lower()
        if backend == "custom_http":
            return CustomHttpSmsSender()
        return MockSmsSender()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS customer_links (
                    id INTEGER PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    event_folder TEXT NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    license_plate TEXT NOT NULL,
                    owner_name TEXT NOT NULL,
                    mechanic_name TEXT NOT NULL,
                    phone_number TEXT NOT NULL,
                    public_url TEXT NOT NULL,
                    sms_status TEXT NOT NULL,
                    sms_error TEXT NULL,
                    created_at TEXT NOT NULL,
                    sent_at TEXT NULL,
                    expires_at TEXT NOT NULL,
                    quiz_completed_at TEXT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_customer_links_event_id
                    ON customer_links(event_id);

                CREATE INDEX IF NOT EXISTS idx_customer_links_token
                    ON customer_links(token);

                CREATE TABLE IF NOT EXISTS customer_feedback (
                    id INTEGER PRIMARY KEY,
                    link_id INTEGER NOT NULL UNIQUE,
                    rating_overall INTEGER NOT NULL,
                    rating_explanation INTEGER NOT NULL,
                    free_text TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    FOREIGN KEY(link_id) REFERENCES customer_links(id) ON DELETE CASCADE
                );
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _event_dir(self, event_id: str) -> Path:
        safe_event_id = Path(event_id).name
        return settings.events_dir_abs / safe_event_id

    def _load_event_info(self, event_id: str) -> dict[str, Any]:
        event_dir = self._event_dir(event_id)
        if not event_dir.exists() or not event_dir.is_dir():
            raise CustomerPortalNotFound(f"Event not found: {event_id}")

        outs, recording_warnings = workflow_output_status(event_dir)
        n_ok = sum(1 for v in outs.values() if v)
        if n_ok == 0:
            raise CustomerPortalConflict(
                "Event has no usable video (need at least one camera file with sufficient size)."
            )

        camera1 = event_dir / "camera1.mp4"
        camera2 = event_dir / "camera2.mp4"
        has_c1 = bool(outs.get("camera1"))
        has_c2 = bool(outs.get("camera2"))
        recording_partial = n_ok == 1

        alpr_payload: dict[str, Any] = {}
        alpr_json = event_dir / "alpr.json"
        if alpr_json.exists():
            try:
                alpr_payload = json.loads(alpr_json.read_text(encoding="utf-8"))
            except Exception:
                alpr_payload = {}

        recorded_at = self._derive_recorded_at(event_dir, alpr_payload)
        return {
            "event_id": event_dir.name,
            "event_folder": event_dir.name,
            "event_dir": event_dir,
            "camera1_path": camera1 if has_c1 else None,
            "camera2_path": camera2 if has_c2 else None,
            "has_camera1": has_c1,
            "has_camera2": has_c2,
            "recording_partial": recording_partial,
            "recording_warnings": list(recording_warnings),
            "recorded_at": recorded_at,
            "recorded_at_iso": recorded_at.isoformat(),
            "recorded_at_display": recorded_at.astimezone().strftime("%d.%m.%Y %H:%M"),
            "alpr": alpr_payload,
        }

    def _derive_recorded_at(self, event_dir: Path, alpr_payload: dict[str, Any]) -> datetime:
        ts = alpr_payload.get("timestamp")
        if isinstance(ts, str) and ts:
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                pass

        match = re.search(r"_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)(?:_\d+)?$", event_dir.name)
        if match:
            try:
                return datetime.strptime(match.group(1), "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        return datetime.fromtimestamp(event_dir.stat().st_ctime, tz=timezone.utc)

    def _build_public_url(self, token: str) -> str:
        base = settings.public_base_url.rstrip("/")
        prefix = settings.portal_path_prefix_normalized.rstrip("/")
        return f"{base}{prefix}/{token}"

    def _build_sms_text(self, row: dict[str, Any]) -> str:
        return (
            f"Tedde Auto: {row['owner_name']}, am pregatit constatarea video pentru masina "
            f"{row['license_plate']}. Acceseaza linkul securizat: {row['public_url']}"
        )

    async def create_link(
        self,
        *,
        event_id: str,
        license_plate: str,
        owner_name: str,
        mechanic_name: str,
        phone_number: str,
        send_sms: bool,
    ) -> dict[str, Any]:
        event_info = await asyncio.to_thread(self._load_event_info, event_id)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=settings.customer_link_ttl_days)
        token = secrets.token_urlsafe(24)
        public_url = self._build_public_url(token)
        sms_status = "pending" if send_sms else "skipped"
        clean_license_plate = license_plate.strip()
        clean_owner_name = owner_name.strip()
        clean_mechanic_name = mechanic_name.strip()
        clean_phone_number = phone_number.strip()

        if not clean_license_plate:
            raise CustomerPortalError("license_plate is required")
        if not clean_owner_name:
            raise CustomerPortalError("owner_name is required")
        if not clean_mechanic_name:
            raise CustomerPortalError("mechanic_name is required")
        if not clean_phone_number:
            raise CustomerPortalError("phone_number is required")

        payload = {
            "event_id": event_info["event_id"],
            "event_folder": event_info["event_folder"],
            "token": token,
            "license_plate": clean_license_plate,
            "owner_name": clean_owner_name,
            "mechanic_name": clean_mechanic_name,
            "phone_number": clean_phone_number,
            "public_url": public_url,
            "sms_status": sms_status,
            "sms_error": None,
            "created_at": now.isoformat(),
            "sent_at": None,
            "expires_at": expires_at.isoformat(),
            "quiz_completed_at": None,
        }

        link_id = await asyncio.to_thread(self._insert_link_sync, payload)
        payload["id"] = link_id

        sms_preview = self._build_sms_text(payload)
        if send_sms:
            result = await self._sms_sender.send_sms(clean_phone_number, sms_preview)
            sent_at = datetime.now(timezone.utc).isoformat() if result.status in {"sent", "mocked"} else None
            await asyncio.to_thread(
                self._update_sms_status_sync,
                link_id,
                result.status,
                result.error,
                sent_at,
            )
            payload["sms_status"] = result.status
            payload["sms_error"] = result.error
            payload["sent_at"] = sent_at

        out = self._serialize_link(payload)
        out["warnings"] = list(event_info.get("recording_warnings") or [])
        if event_info.get("recording_partial"):
            out["warnings"].insert(
                0,
                "Inregistrare pe o singura camera: clientul va vedea doar video-ul disponibil.",
            )
        out["recording_partial"] = bool(event_info.get("recording_partial"))
        out["sms_preview"] = sms_preview
        return out

    def _insert_link_sync(self, payload: dict[str, Any]) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO customer_links (
                    event_id, event_folder, token, license_plate, owner_name,
                    mechanic_name, phone_number, public_url, sms_status,
                    sms_error, created_at, sent_at, expires_at, quiz_completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["event_id"],
                    payload["event_folder"],
                    payload["token"],
                    payload["license_plate"],
                    payload["owner_name"],
                    payload["mechanic_name"],
                    payload["phone_number"],
                    payload["public_url"],
                    payload["sms_status"],
                    payload["sms_error"],
                    payload["created_at"],
                    payload["sent_at"],
                    payload["expires_at"],
                    payload["quiz_completed_at"],
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def _update_sms_status_sync(self, link_id: int, status: str, error: str | None, sent_at: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE customer_links SET sms_status = ?, sms_error = ?, sent_at = ? WHERE id = ?",
                (status, error, sent_at, link_id),
            )
            conn.commit()

    async def get_link(self, link_id: int) -> dict[str, Any]:
        row = await asyncio.to_thread(self._get_link_row_sync, link_id)
        if row is None:
            raise CustomerPortalNotFound(f"Link not found: {link_id}")
        return row

    def _get_link_row_sync(self, link_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            link = conn.execute("SELECT * FROM customer_links WHERE id = ?", (link_id,)).fetchone()
            if link is None:
                return None
            feedback = conn.execute(
                "SELECT rating_overall, rating_explanation, free_text, submitted_at FROM customer_feedback WHERE link_id = ?",
                (link_id,),
            ).fetchone()

        payload = self._serialize_link(dict(link))
        event_info = self._load_event_info(payload["event_id"])
        payload["quiz_completed"] = bool(payload["quiz_completed_at"])
        payload["is_expired"] = self._is_expired(payload["expires_at"])
        c1p = event_info.get("camera1_path")
        c2p = event_info.get("camera2_path")
        payload["event"] = {
            "event_id": event_info["event_id"],
            "recorded_at": event_info["recorded_at_iso"],
            "recorded_at_display": event_info["recorded_at_display"],
            "recording_partial": event_info.get("recording_partial", False),
            "videos": {
                "camera1": c1p.name if c1p is not None else None,
                "camera2": c2p.name if c2p is not None else None,
            },
        }
        payload["feedback"] = dict(feedback) if feedback is not None else None
        return payload

    async def resend(self, link_id: int) -> dict[str, Any]:
        link = await self.get_link(link_id)
        if self._is_expired(link["expires_at"]):
            raise CustomerPortalConflict("Cannot resend an expired link")

        sms_text = self._build_sms_text(link)
        result = await self._sms_sender.send_sms(link["phone_number"], sms_text)
        sent_at = datetime.now(timezone.utc).isoformat() if result.status in {"sent", "mocked"} else None
        await asyncio.to_thread(self._update_sms_status_sync, link_id, result.status, result.error, sent_at)
        return await self.get_link(link_id)

    async def get_portal_record(self, token: str) -> dict[str, Any]:
        row = await asyncio.to_thread(self._get_link_by_token_sync, token)
        if row is None:
            raise CustomerPortalNotFound("Token not found")
        if self._is_expired(row["expires_at"]):
            raise CustomerPortalExpired("Token expired")
        return row

    def _get_link_by_token_sync(self, token: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            link = conn.execute("SELECT * FROM customer_links WHERE token = ?", (token,)).fetchone()
            if link is None:
                return None
            feedback = conn.execute(
                "SELECT rating_overall, rating_explanation, free_text, submitted_at FROM customer_feedback WHERE link_id = ?",
                (int(link["id"]),),
            ).fetchone()

        payload = self._serialize_link(dict(link))
        event_info = self._load_event_info(payload["event_id"])
        prefix = settings.portal_path_prefix_normalized.rstrip("/")
        tok = payload["token"]
        cam1 = (
            f"{prefix}/{tok}/video/camera1"
            if event_info.get("has_camera1") and event_info.get("camera1_path")
            else None
        )
        cam2 = (
            f"{prefix}/{tok}/video/camera2"
            if event_info.get("has_camera2") and event_info.get("camera2_path")
            else None
        )
        payload["event"] = {
            "event_id": event_info["event_id"],
            "recorded_at": event_info["recorded_at_iso"],
            "recorded_at_display": event_info["recorded_at_display"],
            "recording_partial": event_info.get("recording_partial", False),
            "camera1_url": cam1,
            "camera2_url": cam2,
        }
        payload["feedback"] = dict(feedback) if feedback is not None else None
        payload["quiz_completed"] = bool(payload["quiz_completed_at"])
        payload["is_expired"] = self._is_expired(payload["expires_at"])
        payload["event_folder"] = event_info["event_folder"]
        payload["event_dir"] = str(event_info["event_dir"])
        return payload

    async def submit_feedback(
        self,
        token: str,
        *,
        rating_overall: int,
        rating_explanation: int,
        free_text: str,
    ) -> dict[str, Any]:
        row = await self.get_portal_record(token)
        if row["quiz_completed"]:
            raise CustomerPortalConflict("Feedback already submitted")
        if rating_overall not in {1, 2, 3, 4, 5}:
            raise CustomerPortalError("rating_overall must be between 1 and 5")
        if rating_explanation not in {1, 2, 3, 4, 5}:
            raise CustomerPortalError("rating_explanation must be between 1 and 5")
        if not free_text.strip():
            raise CustomerPortalError("free_text is required")

        submitted_at = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(
            self._insert_feedback_sync,
            int(row["link_id"]),
            rating_overall,
            rating_explanation,
            free_text.strip(),
            submitted_at,
        )
        return await self.get_portal_record(token)

    def _insert_feedback_sync(
        self,
        link_id: int,
        rating_overall: int,
        rating_explanation: int,
        free_text: str,
        submitted_at: str,
    ) -> None:
        with self._connect() as conn:
            already = conn.execute("SELECT 1 FROM customer_feedback WHERE link_id = ?", (link_id,)).fetchone()
            if already is not None:
                raise CustomerPortalConflict("Feedback already submitted")

            conn.execute(
                """
                INSERT INTO customer_feedback (link_id, rating_overall, rating_explanation, free_text, submitted_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (link_id, rating_overall, rating_explanation, free_text, submitted_at),
            )
            conn.execute(
                "UPDATE customer_links SET quiz_completed_at = ? WHERE id = ?",
                (submitted_at, link_id),
            )
            conn.commit()

    async def resolve_video_path(self, token: str, camera_id: int) -> Path:
        row = await self.get_portal_record(token)
        if not row["quiz_completed"]:
            raise CustomerPortalForbidden("Quiz must be completed before video access")
        event_dir = self._event_dir(row["event_id"])
        target = event_dir / f"camera{camera_id}.mp4"
        if not target.exists():
            raise CustomerPortalNotFound(f"camera{camera_id}.mp4 is missing")
        return target

    def _serialize_link(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "success": True,
            "link_id": int(row["id"]),
            "event_id": row["event_id"],
            "event_folder": row["event_folder"],
            "token": row["token"],
            "license_plate": row["license_plate"],
            "owner_name": row["owner_name"],
            "mechanic_name": row["mechanic_name"],
            "phone_number": row["phone_number"],
            "public_url": row["public_url"],
            "sms_status": row["sms_status"],
            "sms_error": row["sms_error"],
            "created_at": row["created_at"],
            "sent_at": row["sent_at"],
            "expires_at": row["expires_at"],
            "quiz_completed_at": row["quiz_completed_at"],
        }

    @staticmethod
    def _is_expired(expires_at: str) -> bool:
        try:
            dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        return dt <= datetime.now(timezone.utc)
