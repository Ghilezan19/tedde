"""
Shared ISAPI HTTP helper — Digest Auth for HiLook / Hikvision cameras.

Used by:
  - camera/audio.py  (TwoWayAudio)
  - camera/ir.py     (Image / IR control)

Mirrors the cam2Request() logic from server.js:
  1. Try cached nonce
  2. First attempt without auth → parse 401 WWW-Authenticate
  3. Probe /ISAPI/System/Time if camera returns non-401 challenge
  4. Retry with Digest Auth header

All methods are async and use httpx under the hood.
"""

import hashlib
import logging
import secrets
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Digest Auth helpers
# ------------------------------------------------------------------ #

def md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def build_digest_header(
    method: str,
    req_path: str,
    realm: str,
    nonce: str,
    qop: str,
    opaque: str,
    username: str,
    password: str,
) -> str:
    nc = "00000001"
    cnonce = secrets.token_hex(4)
    ha1 = md5(f"{username}:{realm}:{password}")
    ha2 = md5(f"{method}:{req_path}")
    if qop:
        response = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    else:
        response = md5(f"{ha1}:{nonce}:{ha2}")
    header = (
        f'Digest username="{username}", realm="{realm}", '
        f'nonce="{nonce}", uri="{req_path}", response="{response}"'
    )
    if qop:
        header += f', qop={qop}, nc={nc}, cnonce="{cnonce}"'
    if opaque:
        header += f', opaque="{opaque}"'
    return header


def parse_www_auth(header_value: str) -> Optional[dict]:
    """Parse 'WWW-Authenticate: Digest ...' into a dict."""
    if not header_value.lower().startswith("digest"):
        return None
    import re
    get = lambda k: (re.search(rf'{k}="([^"]+)"', header_value) or [None, ""])[1]
    return {
        "realm":  get("realm"),
        "nonce":  get("nonce"),
        "qop":    (re.search(r'qop="([^"]+)"', header_value) or [None, ""])[1].split(",")[0].strip(),
        "opaque": get("opaque"),
    }


# ------------------------------------------------------------------ #
# ISAPIClient
# ------------------------------------------------------------------ #

class ISAPIClient:
    """
    Async HTTP client for ISAPI endpoints with automatic Digest Auth.

    One instance per camera — maintains the nonce cache and session cookie
    so subsequent requests don't need an extra round-trip.
    """

    def __init__(self, ip: str, port: int, username: str, password: str) -> None:
        self._base_url = f"http://{ip}:{port}"
        self._username = username
        self._password = password
        self._nonce_cache: Optional[dict] = None
        self._cookie: Optional[str] = None

    async def request(
        self,
        method: str,
        path: str,
        body: Optional[bytes] = None,
        content_type: str = "application/xml",
    ) -> dict:
        """
        Perform an ISAPI request with automatic Digest Auth retry.

        Returns:
            {"status": int, "headers": dict, "data": str}
        """
        headers: dict = {}
        if self._cookie:
            headers["Cookie"] = self._cookie
        if body is not None:
            headers["Content-Type"] = content_type

        async with httpx.AsyncClient(timeout=8.0) as client:
            # 1. Try cached nonce
            if self._nonce_cache:
                auth = build_digest_header(
                    method, path, username=self._username,
                    password=self._password, **self._nonce_cache,
                )
                resp = await self._do(client, method, path, body, {**headers, "Authorization": auth})
                if resp["status"] != 401:
                    self._save_cookie(resp)
                    return resp
                self._nonce_cache = None

            # 2. First attempt — no auth
            resp = await self._do(client, method, path, body, headers)
            self._save_cookie(resp)

            if resp["status"] == 401:
                digest = parse_www_auth(resp["headers"].get("www-authenticate", ""))
            elif resp["status"] in (200, 201):
                return resp
            else:
                # Camera returned non-401 without challenge (common on HiLook)
                # — probe a known GET endpoint to get the nonce
                logger.debug("[ISAPI] %s %s → %d, probing nonce…", method, path, resp["status"])
                probe = await self._do(client, "GET", "/ISAPI/System/Time", None, headers)
                if probe["status"] == 401:
                    digest = parse_www_auth(probe["headers"].get("www-authenticate", ""))
                else:
                    return resp  # give up

            if not digest or not digest.get("nonce"):
                logger.warning("[ISAPI] Could not parse WWW-Authenticate on %s %s", method, path)
                return resp

            # 3. Retry with Digest
            self._nonce_cache = digest
            auth = build_digest_header(
                method, path, username=self._username,
                password=self._password, **digest,
            )
            final = await self._do(client, method, path, body, {**headers, "Authorization": auth})
            self._save_cookie(final)
            return final

    async def get(self, path: str) -> dict:
        return await self.request("GET", path)

    async def put(self, path: str, xml: str) -> dict:
        return await self.request("PUT", path, body=xml.encode(), content_type="application/xml")

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    async def _do(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        body: Optional[bytes],
        headers: dict,
    ) -> dict:
        resp = await client.request(
            method,
            f"{self._base_url}{path}",
            content=body,
            headers=headers,
        )
        return {
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "data": resp.text,
        }

    def _save_cookie(self, resp: dict) -> None:
        sc = resp["headers"].get("set-cookie")
        if sc:
            self._cookie = sc.split(";")[0]

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def username(self) -> str:
        return self._username

    @property
    def password(self) -> str:
        return self._password
