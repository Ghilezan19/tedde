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

from camera.recording import resolve_camera_file, workflow_output_status
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


class CustomerPortalOutOfTokens(CustomerPortalError):
    """Raised when attempting to send an SMS but no tokens remain on the account."""
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


class SimpleGatewaySmsSender:
    """SMS sender for the simple gateway: POST {apiKey, phone, message} to /send-sms."""

    async def send_sms(self, to: str, text: str) -> SendResult:
        base = (settings.sms_gateway_url or "").rstrip("/")
        api_key = settings.sms_gateway_api_key or ""
        if not base or not api_key:
            return SendResult(
                status="failed",
                error="SMS gateway not configured (SMS_GATEWAY_URL / SMS_GATEWAY_API_KEY missing).",
            )
        url = f"{base}/send-sms"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    url,
                    json={"apiKey": api_key, "phone": to, "message": text},
                )
        except Exception as exc:
            logger.warning("[SMS/gateway] request failed to=%s error=%s", _mask_phone(to), exc)
            return SendResult(status="failed", error=str(exc))

        if 200 <= response.status_code < 300:
            logger.info(
                "[SMS/gateway] sent to=%s status=%s",
                _mask_phone(to),
                response.status_code,
            )
            return SendResult(status="sent", http_status=response.status_code)

        body_excerpt = (response.text or "")[:200]
        logger.warning(
            "[SMS/gateway] failed to=%s status=%s body=%s",
            _mask_phone(to),
            response.status_code,
            body_excerpt,
        )
        return SendResult(
            status="failed",
            error=f"Provider returned HTTP {response.status_code}: {body_excerpt}",
            http_status=response.status_code,
        )


class CustomerPortalService:
    def __init__(self) -> None:
        self._db_path = settings.customer_portal_db_abs
        self._sms_sender = self._build_sms_sender()

    def _build_sms_sender(self):
        # If the simple gateway is configured, prefer it (the live production gateway).
        if settings.sms_gateway_url and settings.sms_gateway_api_key:
            logger.info("[SMS] Using SimpleGatewaySmsSender (%s)", settings.sms_gateway_url)
            return SimpleGatewaySmsSender()
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

                CREATE TABLE IF NOT EXISTS system_config (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS token_history (
                    id             INTEGER PRIMARY KEY,
                    kind           TEXT NOT NULL,           -- 'consume' | 'topup' | 'adjust'
                    delta          INTEGER NOT NULL,        -- negative for consume, positive otherwise
                    balance_after  INTEGER NOT NULL,        -- remaining tokens after the event
                    link_id        INTEGER NULL,            -- FK → customer_links.id (for 'consume')
                    license_plate  TEXT NULL,
                    phone_number   TEXT NULL,
                    owner_name     TEXT NULL,
                    mechanic_name  TEXT NULL,
                    note           TEXT NULL,
                    created_at     TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_token_history_created
                    ON token_history(created_at DESC);
                """
            )
            # Seed default values if not already present
            conn.execute(
                "INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)",
                ("tokens_remaining", "0"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)",
                ("cleanup_days", "30"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)",
                ("auto_cleanup_enabled", "1"),
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # system_config helpers
    # ------------------------------------------------------------------

    def get_config_value(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM system_config WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_config_value(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()

    def get_tokens_remaining(self) -> int:
        try:
            return int(self.get_config_value("tokens_remaining", "0"))
        except ValueError:
            return 0

    def set_tokens_remaining(self, count: int, *, note: str | None = None) -> int:
        """Set token balance to an exact value and log the delta as an 'adjust' entry."""
        new_val = max(0, int(count))
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM system_config WHERE key = 'tokens_remaining'"
            ).fetchone()
            current = int(row["value"]) if row else 0
            conn.execute(
                "INSERT OR REPLACE INTO system_config (key, value) VALUES ('tokens_remaining', ?)",
                (str(new_val),),
            )
            delta = new_val - current
            if delta != 0:
                kind = "topup" if delta > 0 else "adjust"
                self._insert_token_history_sync(
                    conn,
                    kind=kind,
                    delta=delta,
                    balance_after=new_val,
                    note=note or ("Manual set" if kind == "adjust" else "Manual top-up"),
                )
            conn.commit()
        return new_val

    def consume_token(
        self,
        *,
        link_id: int | None = None,
        license_plate: str | None = None,
        phone_number: str | None = None,
        owner_name: str | None = None,
        mechanic_name: str | None = None,
        note: str | None = None,
    ) -> int:
        """Atomically decrement tokens by 1 and append an audit entry.

        Returns the new balance. Raises CustomerPortalOutOfTokens if balance is
        already 0 — callers should pre-check with `get_tokens_remaining()` if
        they need to fail early.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM system_config WHERE key = 'tokens_remaining'"
            ).fetchone()
            current = int(row["value"]) if row else 0
            if current <= 0:
                raise CustomerPortalOutOfTokens("Nu mai aveți tokeni disponibili.")
            new_val = current - 1
            conn.execute(
                "INSERT OR REPLACE INTO system_config (key, value) VALUES ('tokens_remaining', ?)",
                (str(new_val),),
            )
            self._insert_token_history_sync(
                conn,
                kind="consume",
                delta=-1,
                balance_after=new_val,
                link_id=link_id,
                license_plate=license_plate,
                phone_number=phone_number,
                owner_name=owner_name,
                mechanic_name=mechanic_name,
                note=note,
            )
            conn.commit()
        if new_val == 0:
            logger.warning("[TOKENS] Token count reached 0 after consume.")
        return new_val

    def _insert_token_history_sync(
        self,
        conn: sqlite3.Connection,
        *,
        kind: str,
        delta: int,
        balance_after: int,
        link_id: int | None = None,
        license_plate: str | None = None,
        phone_number: str | None = None,
        owner_name: str | None = None,
        mechanic_name: str | None = None,
        note: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO token_history (
                kind, delta, balance_after, link_id,
                license_plate, phone_number, owner_name, mechanic_name,
                note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kind,
                int(delta),
                int(balance_after),
                link_id,
                license_plate,
                phone_number,
                owner_name,
                mechanic_name,
                note,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def list_token_history(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        """Return recent token_history rows (newest first) with totals."""
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, kind, delta, balance_after, link_id,
                       license_plate, phone_number, owner_name, mechanic_name,
                       note, created_at
                FROM token_history
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            total_row = conn.execute(
                "SELECT COUNT(*) AS n FROM token_history"
            ).fetchone()
            consumed_row = conn.execute(
                "SELECT COALESCE(SUM(-delta), 0) AS n FROM token_history WHERE kind='consume'"
            ).fetchone()
            topped_row = conn.execute(
                "SELECT COALESCE(SUM(delta), 0) AS n FROM token_history WHERE kind='topup'"
            ).fetchone()
        return {
            "total": int(total_row["n"] if total_row else 0),
            "total_consumed": int(consumed_row["n"] if consumed_row else 0),
            "total_topped_up": int(topped_row["n"] if topped_row else 0),
            "items": [dict(r) for r in rows],
        }  # type: ignore[return-value]

    def _event_dir(self, event_id: str) -> Path:
        safe_event_id = Path(event_id).name
        return settings.events_dir_abs / safe_event_id

    async def find_latest_event_by_plate(self, license_plate: str) -> str | None:
        """Find the most recent event folder whose ALPR plate matches the given one.

        Match strategy (case-insensitive, punctuation stripped):
        1. Folder name contains the normalised plate (e.g. EVENT_<ts>_TM14TZJ).
        2. alpr.json `selected_plate` equals the normalised plate.

        Returns the folder name (event_id) or None if no match found.
        """
        return await asyncio.to_thread(self._find_latest_event_by_plate_sync, license_plate)

    def _find_latest_event_by_plate_sync(self, license_plate: str) -> str | None:
        plate_norm = re.sub(r"[^A-Z0-9]", "", (license_plate or "").upper())
        if not plate_norm:
            return None

        events_root = settings.events_dir_abs
        if not events_root.exists():
            return None

        candidates: list[tuple[float, str]] = []
        for d in events_root.iterdir():
            if not d.is_dir() or d.name.startswith(".tmp_") or d.name.startswith("."):
                continue

            folder_norm = re.sub(r"[^A-Z0-9]", "", d.name.upper())
            if plate_norm in folder_norm:
                candidates.append((d.stat().st_mtime, d.name))
                continue

            alpr_json = d / "alpr.json"
            if not alpr_json.exists():
                continue
            try:
                data = json.loads(alpr_json.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            selected = str(data.get("selected_plate") or "")
            selected_norm = re.sub(r"[^A-Z0-9]", "", selected.upper())
            if selected_norm and selected_norm == plate_norm:
                candidates.append((d.stat().st_mtime, d.name))

        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]

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

        camera1 = resolve_camera_file(event_dir, 1)
        camera2 = resolve_camera_file(event_dir, 2)
        has_c1 = bool(outs.get("camera1")) and camera1 is not None
        has_c2 = bool(outs.get("camera2")) and camera2 is not None
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

        # ── Token enforcement: fail early BEFORE creating the link / calling the
        # SMS gateway. Billing model: 1 token = 1 SMS to 1 customer.
        if send_sms:
            tokens_left = await asyncio.to_thread(self.get_tokens_remaining)
            if tokens_left <= 0:
                logger.warning(
                    "[TOKENS] Refusing send_video_link for plate=%s phone=%s — balance=0",
                    clean_license_plate,
                    _mask_phone(clean_phone_number),
                )
                raise CustomerPortalOutOfTokens(
                    "Nu mai aveți tokeni disponibili. Contactați administratorul pentru a adăuga tokeni."
                )

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

            # Decrement tokens + audit log on successful send
            if result.status in {"sent", "mocked"}:
                try:
                    tokens_left = await asyncio.to_thread(
                        self.consume_token,
                        link_id=link_id,
                        license_plate=clean_license_plate,
                        phone_number=clean_phone_number,
                        owner_name=clean_owner_name,
                        mechanic_name=clean_mechanic_name,
                        note=f"SMS {result.status}",
                    )
                    logger.info("[TOKENS] Consumed after SMS send — remaining: %d", tokens_left)
                except CustomerPortalOutOfTokens:
                    # Race: balance hit 0 between pre-check and send. Log but
                    # don't fail the request — SMS already went out.
                    logger.warning(
                        "[TOKENS] Race: balance=0 at consume; SMS already sent to %s",
                        _mask_phone(clean_phone_number),
                    )

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
        # Security: the random token is the sole credential — quiz is a UX gate,
        # not a security gate. Serving video pre-quiz lets the browser preload
        # while the customer fills the feedback form (instant-play on submit).
        row = await self.get_portal_record(token)
        event_dir = self._event_dir(row["event_id"])
        target = resolve_camera_file(event_dir, camera_id)
        if target is None or not target.exists():
            raise CustomerPortalNotFound(f"Video for camera {camera_id} is missing")
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
