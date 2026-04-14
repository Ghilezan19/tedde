"""
Async ISAPI audio client for HiLook / Hikvision cameras.

Audio pipeline for TTS:
    gTTS  →  MP3 bytes  →  ffmpeg (MP3 → G.711 μ-law @ 8 kHz mono)
          →  persistent raw TCP socket  →  camera speaker

Key implementation detail (from Hikvision ISAPI research):
  - The /audioData PUT request must be a SINGLE streaming HTTP request
    kept open for the entire duration — NOT one PUT per chunk.
  - Audio must be sent at the exact hardware rate: 128 bytes every 16 ms
    (= 8000 samples/s).  Sending faster causes distorted/sped-up audio.
  - We use urllib.request + SocketGrabber (a well-known technique) to
    keep the underlying TCP socket alive while streaming.

References:
  - https://stackoverflow.com/a/73884001
  - https://github.com/bkbilly/hikvision-audio
"""

import asyncio
import io
import logging
import socket
import time
import urllib.request
from typing import Optional

from gtts import gTTS

from camera.isapi_client import ISAPIClient
from config import settings

logger = logging.getLogger(__name__)

_AUDIO_OPEN  = "/ISAPI/System/TwoWayAudio/channels/1/open"
_AUDIO_CLOSE = "/ISAPI/System/TwoWayAudio/channels/1/close"
_AUDIO_DATA  = "/ISAPI/System/TwoWayAudio/channels/1/audioData"

_CHUNK_BYTES = 128          # bytes per packet
_CHUNK_SECS  = _CHUNK_BYTES / 8000.0   # 16 ms per packet


# ------------------------------------------------------------------ #
# SocketGrabber — recovers the raw socket from urllib before it closes
# ------------------------------------------------------------------ #

class _SocketGrabber:
    """
    Context manager that monkey-patches socket.close so urllib's
    internal cleanup doesn't actually close the socket we need.
    """

    def __init__(self) -> None:
        self.sock: Optional[socket.socket] = None
        self._original_close = socket.socket.close

    def __enter__(self) -> "_SocketGrabber":
        original = self._original_close

        def patched_close(s: socket.socket) -> None:
            if s._closed:                   # type: ignore[attr-defined]
                return
            if self.sock is s:              # our socket — don't close yet
                return
            if self.sock is not None:
                original(self.sock)         # close the previous one first
            self.sock = s

        socket.socket.close = patched_close  # type: ignore[method-assign]
        return self

    def __exit__(self, *_) -> None:
        socket.socket.close = self._original_close  # type: ignore[method-assign]


# ------------------------------------------------------------------ #
# G.711 μ-law encoder
# ------------------------------------------------------------------ #

_MULAW_BIAS = 33
_MULAW_CLIP = 32635


def _encode_mulaw(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    if sign:
        sample = -sample
    if sample > _MULAW_CLIP:
        sample = _MULAW_CLIP
    sample += _MULAW_BIAS
    exp = 7
    mask = 0x4000
    while (sample & mask) == 0 and exp > 0:
        exp -= 1
        mask >>= 1
    mantissa = (sample >> (exp + 3)) & 0x0F
    return (~(sign | (exp << 4) | mantissa)) & 0xFF


def _pcm_to_mulaw(pcm_bytes: bytes) -> bytes:
    """Convert raw s16le PCM bytes to G.711 μ-law."""
    out = bytearray(len(pcm_bytes) // 2)
    for i in range(len(out)):
        lo = pcm_bytes[2 * i]
        hi = pcm_bytes[2 * i + 1]
        sample = (hi << 8) | lo
        if sample >= 0x8000:
            sample -= 0x10000
        out[i] = _encode_mulaw(sample)
    return bytes(out)


# ------------------------------------------------------------------ #
# AudioClient
# ------------------------------------------------------------------ #

class AudioClient:
    """
    Streams TTS audio to the camera speaker via ISAPI TwoWayAudio.

    Lifecycle:
        await client.open_session()
        await client.play_tts("Inregistrarea a inceput")
        await client.close_session()
    """

    def __init__(self) -> None:
        self._isapi = ISAPIClient(
            ip=settings.camera2_ip,
            port=settings.camera2_http_port,
            username=settings.camera2_username,
            password=settings.camera2_password,
        )
        self._session_open = False
        self._audio_sock: Optional[socket.socket] = None
        # urllib opener — built once, carries Digest Auth cookies/nonce
        self._opener: Optional[urllib.request.OpenerDirector] = None
        self._session_id = "1"
        self._write_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Session management
    # ------------------------------------------------------------------ #

    async def open_session(self) -> bool:
        """
        Open a TwoWayAudio session on the camera.
        Builds a urllib opener with Digest Auth and opens the audio stream socket.
        Returns True on success.
        """
        if self._session_open:
            return True

        base_url = self._isapi.base_url
        username = self._isapi.username
        password = self._isapi.password

        # Build urllib opener with Digest Auth
        mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        mgr.add_password(None, [base_url], username, password)
        auth_handler = urllib.request.HTTPDigestAuthHandler(mgr)
        self._opener = urllib.request.build_opener(auth_handler)

        # 1. Open the TwoWayAudio session (blocking, run in executor)
        open_url = f"{base_url}{_AUDIO_OPEN}"
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._opener.open(
                    urllib.request.Request(open_url, method="PUT"),
                    timeout=8,
                ),
            )
        except Exception as exc:
            logger.error("[AUDIO] open_session failed: %s", exc)
            return False

        # 2. Open the streaming audioData PUT — grab the raw socket
        data_url = f"{base_url}{_AUDIO_DATA}"
        grabber = _SocketGrabber()
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._open_audio_stream(data_url, grabber),
            )
        except Exception as exc:
            logger.error("[AUDIO] audioData stream open failed: %s", exc)
            return False

        self._audio_sock = grabber.sock
        if self._audio_sock is None:
            logger.error("[AUDIO] SocketGrabber did not capture the socket")
            return False

        self._session_open = True
        logger.info("[AUDIO] Session opened — streaming socket ready")
        return True

    def _open_audio_stream(self, url: str, grabber: _SocketGrabber) -> None:
        """Blocking: opens the audioData PUT and captures the raw socket."""
        with grabber:
            req = urllib.request.Request(url, method="PUT")
            self._opener.open(req, timeout=30)  # type: ignore[union-attr]

    async def close_session(self) -> None:
        """Gracefully close the TwoWayAudio session."""
        if self._audio_sock:
            try:
                self._audio_sock.close()
            except Exception:
                pass
            self._audio_sock = None

        if self._opener and self._session_open:
            close_url = f"{self._isapi.base_url}{_AUDIO_CLOSE}"
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._opener.open(  # type: ignore[union-attr]
                        urllib.request.Request(close_url, method="PUT"),
                        timeout=5,
                    ),
                )
            except Exception as exc:
                logger.debug("[AUDIO] close error (ignored): %s", exc)

        self._session_open = False
        self._opener = None
        logger.info("[AUDIO] Session closed")

    def status(self) -> dict:
        return {"open": self._session_open, "sessionId": self._session_id if self._session_open else None}

    # ------------------------------------------------------------------ #
    # TTS playback
    # ------------------------------------------------------------------ #

    async def play_tts(self, text: str) -> None:
        """
        Generate speech from `text` and stream it through the camera speaker.
        The session must be open before calling this.
        """
        if not self._session_open or self._audio_sock is None:
            raise RuntimeError("Audio session not open. Call open_session() first.")

        logger.info("[AUDIO] TTS: %r", text)

        # 1. Generate MP3 bytes (gTTS is blocking/network-bound)
        mp3_bytes = await asyncio.get_event_loop().run_in_executor(
            None, self._generate_mp3, text
        )

        # 2. Convert MP3 → G.711 μ-law @ 8 kHz mono via ffmpeg
        mulaw_bytes = await self._mp3_to_mulaw(mp3_bytes)

        # 3. Stream on the persistent socket at hardware rate (8000 samples/s)
        async with self._write_lock:
            await asyncio.get_event_loop().run_in_executor(
                None, self._stream_mulaw, mulaw_bytes
            )

        logger.info("[AUDIO] TTS complete (%d bytes sent)", len(mulaw_bytes))

    async def send_pcm16_chunk(self, pcm16le_bytes: bytes) -> None:
        """
        Send one live-talk PCM chunk received from the browser.

        Browser pacing already approximates the real-time audio clock, so we
        convert and write the chunk directly without adding extra sleeps.
        """
        if not self._session_open or self._audio_sock is None:
            raise RuntimeError("Audio session not open. Call open_session() first.")

        mulaw_bytes = _pcm_to_mulaw(pcm16le_bytes)
        async with self._write_lock:
            await asyncio.get_event_loop().run_in_executor(
                None, self._send_mulaw_chunk, mulaw_bytes
            )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _generate_mp3(self, text: str) -> bytes:
        buf = io.BytesIO()
        gTTS(text=text, lang=settings.tts_language, slow=False).write_to_fp(buf)
        return buf.getvalue()

    async def _mp3_to_mulaw(self, mp3_bytes: bytes) -> bytes:
        """ffmpeg: MP3 → s16le PCM @ 8 kHz mono → μ-law encode."""
        proc = await asyncio.create_subprocess_exec(
            settings.ffmpeg_path,
            "-f", "mp3", "-i", "pipe:0",
            "-ar", "8000", "-ac", "1",
            "-f", "s16le", "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        pcm, _ = await proc.communicate(input=mp3_bytes)
        return _pcm_to_mulaw(pcm)

    def _stream_mulaw(self, mulaw_bytes: bytes) -> None:
        """
        Blocking: send μ-law data on the raw socket at 8000 samples/second.
        128 bytes every 16 ms → correct playback speed on camera.
        """
        sock = self._audio_sock
        if sock is None:
            return
        total = len(mulaw_bytes)
        offset = 0
        while offset < total:
            chunk = mulaw_bytes[offset : offset + _CHUNK_BYTES]
            # Pad last chunk to full size with silence (0xFF = μ-law silence)
            if len(chunk) < _CHUNK_BYTES:
                chunk = chunk + b"\xff" * (_CHUNK_BYTES - len(chunk))
            try:
                sock.send(chunk)
            except OSError as exc:
                logger.error("[AUDIO] Socket send error: %s", exc)
                break
            offset += _CHUNK_BYTES
            time.sleep(_CHUNK_SECS)

    def _send_mulaw_chunk(self, mulaw_bytes: bytes) -> None:
        sock = self._audio_sock
        if sock is None:
            return
        try:
            sock.sendall(mulaw_bytes)
        except OSError as exc:
            logger.error("[AUDIO] Socket send error: %s", exc)
