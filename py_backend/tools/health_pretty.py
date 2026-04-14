"""
Pretty-print GET /api/health JSON or run startup_check standalone (no server).

With --full --base-url: GET /api/health + POST /api/alpr/test (ALPR live pe snapshot).

Usage (repo root, PYTHONPATH=py_backend):
  curl -sS http://127.0.0.1:8000/api/health | python -m tools.health_pretty --stdin
  python -m tools.health_pretty --standalone
  python -m tools.health_pretty --full --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any


def _use_color() -> bool:
    if os.environ.get("NO_COLOR", "").strip():
        return False
    if os.environ.get("FORCE_COLOR", "").strip():
        return True
    return sys.stdout.isatty()


_C = _use_color()
GREEN = "\033[32m" if _C else ""
RED = "\033[31m" if _C else ""
YELLOW = "\033[33m" if _C else ""
DIM = "\033[2m" if _C else ""
RESET = "\033[0m" if _C else ""


def _trunc(s: str, max_len: int) -> str:
    s = s.replace("\n", " ").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _detail(obj: dict[str, Any]) -> str:
    parts: list[str] = []
    d = obj.get("detail")
    if d:
        parts.append(str(d))
    if "latency_ms" in obj:
        parts.append(f"{obj['latency_ms']}ms")
    if "ip" in obj and "port" in obj:
        parts.append(f"{obj['ip']}:{obj['port']}")
    if "path" in obj:
        parts.append(str(obj["path"]))
    if "count" in obj:
        parts.append(f"count={obj['count']}")
    return _trunc("  ".join(parts), 72)


def _status_cell(ok: bool | None) -> str:
    if ok is True:
        return f"{GREEN}OK{RESET}"
    if ok is False:
        return f"{RED}FAIL{RESET}"
    return "?"


def print_health_table(data: dict[str, Any]) -> None:
    started = data.get("started_at", "—")
    overall = data.get("overall", "—")
    preferred = [
        "ffmpeg",
        "camera1_rtsp",
        "camera2_rtsp",
        "camera2_http",
        "snapshots_dir",
        "recordings_dir",
        "events_dir",
        "data_dir",
    ]
    print()
    print("=" * 78)
    print(f"  Tedde health   started_at: {started}")
    print("=" * 78)
    print(f"  {'Probe':<28}  {'Status':<20}  Detail")
    print("-" * 78)

    def print_row(key: str) -> None:
        val = data.get(key)
        if not isinstance(val, dict):
            return
        ok = val.get("ok")
        status = _status_cell(ok)
        name = key[:28]
        print(f"  {name:<28}  {status:<20}  {_detail(val)}")

    seen: set[str] = set()
    for key in preferred:
        if key in data:
            print_row(key)
            seen.add(key)
    for key in sorted(data.keys()):
        if key in ("started_at", "overall") or key in seen:
            continue
        val = data[key]
        if isinstance(val, dict):
            print_row(key)

    print("-" * 78)
    ov_ok = overall == "ok"
    ov_degraded = overall == "degraded"
    if ov_ok:
        ov_s = f"{GREEN}{overall}{RESET}"
    elif ov_degraded:
        ov_s = f"{YELLOW}{overall}{RESET}"
    else:
        ov_s = f"{RED}{overall}{RESET}"
    print(f"  {'overall':<28}  {ov_s}")
    print("=" * 78)
    print()


def print_alpr_live_block(data: dict[str, Any], http_status: int) -> None:
    print()
    print("=" * 78)
    print("  ALPR — snapshot live (POST /api/alpr/test)")
    print("=" * 78)

    if http_status >= 400:
        err = data.get("error", data.get("details", str(data)))
        print(f"  {RED}FAIL{RESET}  HTTP {http_status}: {_trunc(str(err), 68)}")
        print("=" * 78)
        print()
        return

    enabled = data.get("enabled", data.get("alpr_enabled"))
    if enabled is False:
        print(f"  {YELLOW}ALPR dezactivat{RESET} (ALPR_ENABLED=0). Snapshot salvat; inferență oprită.")
        if data.get("snapshot_url"):
            print(f"  {DIM}snapshot: {data['snapshot_url']}{RESET}")
        print("=" * 78)
        print()
        return

    plates = data.get("plates") if isinstance(data.get("plates"), list) else []
    selected = data.get("selected_plate")
    conf = data.get("selected_confidence")

    if plates:
        parts = []
        for p in plates:
            plate = p.get("plate", "?")
            c = p.get("confidence")
            parts.append(f"{plate}" + (f" ({c}%)" if c is not None else ""))
        line = ", ".join(parts)
        print(f"  {GREEN}OK{RESET}  Plăcuțe detectate ({len(plates)}): {line}")
        if selected and conf is not None:
            print(f"  {DIM}ales: {selected} ({conf}% încredere){RESET}")
        elif selected:
            print(f"  {DIM}ales: {selected}{RESET}")
    elif selected:
        print(f"  {GREEN}OK{RESET}  Plăcuță: {selected}" + (f" ({conf}%)" if conf is not None else ""))
    else:
        print(f"  {RED}FAIL{RESET}  Nicio plăcuță detectată pe acest snapshot.")
        if data.get("alpr_retried_with_main"):
            print(f"  {DIM}(sub stream fără detecție — recapturat pe main){RESET}")
    if data.get("snapshot_url"):
        print(f"  {DIM}snapshot: {data['snapshot_url']}{RESET}")
    print("=" * 78)
    print()


def run_full_server_check(base_url: str) -> None:
    import httpx

    from config import settings

    base = base_url.rstrip("/")
    with httpx.Client(timeout=httpx.Timeout(125.0, connect=10.0)) as client:
        r = client.get(f"{base}/api/health")
        r.raise_for_status()
        print_health_table(r.json())

        body = {"camera": int(settings.alpr_camera), "quality": "main"}
        r2 = client.post(f"{base}/api/alpr/test", json=body)
        try:
            payload = r2.json()
        except Exception:
            payload = {"error": r2.text[:500]}
        print_alpr_live_block(payload, r2.status_code)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pretty-print Tedde /api/health JSON (+ optional ALPR live)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stdin", action="store_true", help="Read one JSON object from stdin (health only)")
    group.add_argument("--standalone", action="store_true", help="Run startup_check.run_all() locally (no ALPR HTTP)")
    group.add_argument("--full", action="store_true", help="GET /api/health + POST /api/alpr/test via HTTP")
    parser.add_argument("--base-url", default="", help="With --full: server base URL, e.g. http://127.0.0.1:8000")
    args = parser.parse_args()

    if args.full:
        if not args.base_url.strip():
            print("--full necesită --base-url http://127.0.0.1:PORT", file=sys.stderr)
            sys.exit(2)
        run_full_server_check(args.base_url.strip())
        return

    if args.standalone:
        import startup_check

        data = asyncio.run(startup_check.run_all())
    else:
        raw = sys.stdin.read()
        if not raw.strip():
            print("Nu există JSON pe stdin. Folosește: curl -sS URL | python -m tools.health_pretty --stdin", file=sys.stderr)
            sys.exit(1)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"JSON invalid: {exc}", file=sys.stderr)
            sys.exit(1)

    if not isinstance(data, dict):
        print("Așteptat obiect JSON.", file=sys.stderr)
        sys.exit(1)

    print_health_table(data)


if __name__ == "__main__":
    main()
