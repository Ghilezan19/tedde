"""
Network & system diagnostics for the Configure dashboard.

Endpoints (all require superadmin auth):

- GET  /api/net/info              : local IP, subnet /24, gateway (best-effort)
- GET  /api/net/reach?host=...&port=80&timeout=1.5
                                  : TCP connect probe (reachable + latency_ms)
- GET  /api/net/http-probe?host=...&port=80
                                  : HTTP GET / and return status, server header, title
- GET  /api/net/scan?subnet=10.27.252&ports=80&timeout=0.4&exclude=...
                                  : Parallel scan of a /24 subnet for responding hosts,
                                    with lightweight HTTP fingerprinting (esp/camera/router).
- GET  /api/sys/info              : disk, memory, loadavg, uptime, service statuses
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import shutil
import socket
import subprocess
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from config import settings
from services.auth_service import require_superadmin

logger = logging.getLogger(__name__)
router = APIRouter(tags=["diagnostics"])

# ── Helpers ────────────────────────────────────────────────────────

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _PRIVATE_NETS)


def _local_ip() -> str | None:
    """Best-effort: figure out the primary outbound IP of this host."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def _default_gateway() -> str | None:
    """Parse /proc/net/route to find the default gateway (Linux only)."""
    try:
        with open("/proc/net/route", "r", encoding="utf-8") as f:
            for line in f.readlines()[1:]:
                parts = line.strip().split()
                if len(parts) < 3:
                    continue
                dest, gw, flags = parts[1], parts[2], parts[3]
                if dest == "00000000" and int(flags, 16) & 2:
                    # Little-endian hex IP
                    gw_bytes = bytes.fromhex(gw)
                    return ".".join(str(b) for b in reversed(gw_bytes))
    except (OSError, ValueError):
        pass
    return None


async def _tcp_probe(host: str, port: int, timeout: float) -> tuple[bool, float]:
    """Return (reachable, latency_ms)."""
    start = time.perf_counter()
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True, (time.perf_counter() - start) * 1000.0
    except (OSError, asyncio.TimeoutError):
        return False, (time.perf_counter() - start) * 1000.0


_TITLE_RE = re.compile(r"<title[^>]*>([^<]{0,120})</title>", re.IGNORECASE)


async def _http_fingerprint(host: str, port: int = 80, timeout: float = 1.5) -> dict[str, Any]:
    """GET http://host:port/ and extract identifying info."""
    url = f"http://{host}:{port}/"
    out: dict[str, Any] = {"url": url, "ok": False}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            r = await client.get(url)
        out["ok"] = True
        out["status"] = r.status_code
        out["server"] = r.headers.get("server") or r.headers.get("Server")
        out["content_length"] = int(r.headers.get("content-length", 0) or 0)
        m = _TITLE_RE.search(r.text[:4000]) if r.text else None
        out["title"] = (m.group(1).strip() if m else None)
        # Guess device kind
        blob = " ".join(
            [
                str(out.get("server") or ""),
                str(out.get("title") or ""),
                r.text[:600] if r.text else "",
            ]
        ).lower()
        server_hdr = (out.get("server") or "").lower()
        title = (out.get("title") or "").lower()
        kind = "unknown"
        # This project's dashboard/nginx-proxy (NOT a physical camera)
        if "hilook camera control" == title.strip() or "tedde" in blob or server_hdr.startswith("nginx"):
            kind = "server"
        # ESP firmware usually has a small page or specific signature
        elif "esp" in blob or "espressif" in blob or "esp32" in blob or "esp8266" in blob:
            kind = "esp"
        # Routers — check before camera to avoid misclassifying router landing pages
        elif any(w in blob for w in ("tp-link", "openwrt", "mikrotik", "asus rt", "huawei", "zte ", "ddwrt", "pfsense", "routeros")):
            kind = "router"
        # Hikvision/HiLook/Dahua cameras: generic "webserver" header + "Document Error"
        elif (
            any(w in blob for w in ("hikvision", "dahua", "onvif", "isapi", "ipcam"))
            or server_hdr in ("webserver", "app-webs/")
            and ("document error" in blob or "not found" in title)
            or server_hdr == "webserver"
        ):
            kind = "camera"
        out["kind"] = kind
    except Exception as exc:
        out["error"] = type(exc).__name__
    return out


# ── Endpoints ──────────────────────────────────────────────────────


@router.get("/api/net/info", summary="Local network info")
async def net_info(role: str = Depends(require_superadmin)) -> dict:
    ip = _local_ip()
    subnet24 = None
    if ip:
        parts = ip.split(".")
        if len(parts) == 4:
            subnet24 = ".".join(parts[:3])
    return {
        "ok": True,
        "ip": ip,
        "subnet24": subnet24,
        "gateway": _default_gateway(),
        "hostname": socket.gethostname(),
    }


@router.get("/api/net/reach", summary="TCP connect probe to a host:port")
async def net_reach(
    host: str = Query(..., min_length=1, max_length=253),
    port: int = Query(80, ge=1, le=65535),
    timeout: float = Query(1.5, ge=0.1, le=10.0),
    role: str = Depends(require_superadmin),
) -> dict:
    # Resolve hostname to make private-IP enforcement effective
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        resolved = infos[0][4][0] if infos else host
    except OSError:
        resolved = host
    if not _is_private_ip(resolved):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only private/RFC1918 addresses allowed.")
    reachable, latency = await _tcp_probe(resolved, port, timeout)
    return {
        "ok": True,
        "host": host,
        "resolved": resolved,
        "port": port,
        "reachable": reachable,
        "latency_ms": round(latency, 1),
    }


@router.get("/api/net/http-probe", summary="HTTP GET / on private host for fingerprinting")
async def net_http_probe(
    host: str = Query(...),
    port: int = Query(80, ge=1, le=65535),
    timeout: float = Query(2.0, ge=0.1, le=10.0),
    role: str = Depends(require_superadmin),
) -> dict:
    if not _is_private_ip(host):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only private/RFC1918 addresses allowed.")
    data = await _http_fingerprint(host, port, timeout)
    return {"ok": True, **data}


@router.get("/api/net/scan", summary="Scan a /24 subnet for responding hosts")
async def net_scan(
    subnet: str | None = Query(None, description="'10.27.252' or omit for auto-detect"),
    port: int = Query(80, ge=1, le=65535),
    timeout: float = Query(0.4, ge=0.1, le=3.0),
    fingerprint: bool = Query(True),
    role: str = Depends(require_superadmin),
) -> dict:
    if subnet is None:
        ip = _local_ip()
        if not ip:
            raise HTTPException(status_code=500, detail="Cannot auto-detect local subnet.")
        subnet = ".".join(ip.split(".")[:3])

    # Validate subnet
    test_ip = f"{subnet}.1"
    if not _is_private_ip(test_ip):
        raise HTTPException(status_code=400, detail="Only private/RFC1918 subnets allowed.")

    sem = asyncio.Semaphore(64)

    async def probe(ip: str) -> dict | None:
        async with sem:
            ok, latency = await _tcp_probe(ip, port, timeout)
        if not ok:
            return None
        entry: dict[str, Any] = {"ip": ip, "port": port, "latency_ms": round(latency, 1)}
        if fingerprint:
            fp = await _http_fingerprint(ip, port, timeout=min(1.5, timeout * 3))
            entry.update({k: fp.get(k) for k in ("status", "server", "title", "kind") if fp.get(k) is not None})
        return entry

    tasks = [probe(f"{subnet}.{i}") for i in range(1, 255)]
    started = time.perf_counter()
    results = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - started
    hosts = [r for r in results if r]
    # Sort by kind-priority, then IP
    kind_order = {"esp": 0, "camera": 1, "server": 2, "router": 3, "unknown": 4}
    hosts.sort(key=lambda h: (kind_order.get(h.get("kind", "unknown"), 9), int(h["ip"].rsplit(".", 1)[1])))
    return {
        "ok": True,
        "subnet": subnet,
        "port": port,
        "scanned": 254,
        "found": len(hosts),
        "duration_ms": round(elapsed * 1000, 0),
        "hosts": hosts,
    }


# ── System info ────────────────────────────────────────────────────


def _read_uptime() -> float | None:
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            return float(f.read().split()[0])
    except OSError:
        return None


def _read_meminfo() -> dict[str, int]:
    """Return dict of MemTotal/MemAvailable/etc in bytes."""
    out: dict[str, int] = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                key, _, rest = line.partition(":")
                if not rest:
                    continue
                parts = rest.strip().split()
                if not parts:
                    continue
                try:
                    kb = int(parts[0])
                    out[key.strip()] = kb * 1024
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def _loadavg() -> list[float] | None:
    try:
        return list(os.getloadavg())
    except (OSError, AttributeError):
        return None


def _service_active(unit: str) -> bool:
    """Check if a systemd unit is active (returns True/False)."""
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "--quiet", unit],
            timeout=2.0,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@router.get("/api/sys/info", summary="Host system info (disk, memory, uptime, services)")
async def sys_info(role: str = Depends(require_superadmin)) -> dict:
    # Disk usage of project root
    try:
        du = shutil.disk_usage(str(settings.project_root_abs) if hasattr(settings, "project_root_abs") else "/")
        disk = {"total": du.total, "used": du.used, "free": du.free, "percent": round(du.used * 100 / du.total, 1)}
    except OSError:
        disk = {}

    mem = _read_meminfo()
    total = mem.get("MemTotal", 0)
    avail = mem.get("MemAvailable", 0)
    mem_out = {
        "total": total,
        "available": avail,
        "used": total - avail if total else 0,
        "percent": round((total - avail) * 100 / total, 1) if total else None,
    }

    uptime = _read_uptime()
    services = {
        name: _service_active(name)
        for name in ("ssh", "tailscaled", "cloudflared", "nginx", "anydesk")
    }

    return {
        "ok": True,
        "hostname": socket.gethostname(),
        "uptime_seconds": int(uptime) if uptime is not None else None,
        "loadavg": _loadavg(),
        "disk": disk,
        "memory": mem_out,
        "services": services,
        "server": {"port": settings.py_server_port, "public_base_url": settings.public_base_url},
    }
