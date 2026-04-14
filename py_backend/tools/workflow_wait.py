"""
Poll GET /api/workflow/status until the workflow is idle, then emit last_event JSON.

Used by lib/cmd_test_record.sh after POST /api/workflow/trigger.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from camera.recording import workflow_output_status


def _fetch_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _validate_event_videos(ev: Path, *, strict_both: bool) -> str | None:
    outs, _warns = workflow_output_status(ev)
    n_ok = sum(1 for v in outs.values() if v)
    if n_ok == 0:
        return "No valid recording (need at least one MP4 with sufficient size)."
    if strict_both and n_ok < 2:
        return "Strict mode: both camera1.mp4 and camera2.mp4 must be valid."
    return None


def _maybe_warn_partial(ev: Path) -> None:
    outs, warns = workflow_output_status(ev)
    n_ok = sum(1 for v in outs.values() if v)
    if n_ok == 1:
        print("WARNING: only one camera produced a valid recording.", file=sys.stderr)
        for w in warns:
            print(f"WARNING: {w}", file=sys.stderr)


def main() -> int:
    p = argparse.ArgumentParser(description="Wait for workflow to finish (busy=false).")
    p.add_argument("--base-url", required=True, help="e.g. http://127.0.0.1:8000")
    p.add_argument("--timeout", type=int, default=300, help="Max seconds to poll (default 300).")
    p.add_argument("--interval", type=float, default=2.0, help="Seconds between polls (default 2).")
    p.add_argument(
        "--validate-under",
        metavar="DIR",
        help="After success, check MP4s under DIR/<event_folder>/ (>=1 valid by default).",
    )
    p.add_argument(
        "--strict-both",
        action="store_true",
        help="With --validate-under, require both camera1 and camera2 valid MP4s.",
    )
    p.add_argument(
        "--write-state",
        metavar="PATH",
        help="Write JSON for test-send: event_id, license_plate, completed_at, base_url.",
    )
    args = p.parse_args()

    base = args.base_url.rstrip("/")
    status_url = f"{base}/api/workflow/status"
    deadline = time.monotonic() + max(1, args.timeout)

    last_payload: dict | None = None
    while time.monotonic() < deadline:
        try:
            last_payload = _fetch_json(status_url, timeout=15.0)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"workflow_wait: request failed: {exc}", file=sys.stderr)
            return 4

        if not last_payload.get("busy"):
            le = last_payload.get("last_event")
            if le is None:
                print(
                    "workflow_wait: idle but last_event is null (no completed run on this process).",
                    file=sys.stderr,
                )
                return 3
            err = le.get("error")
            if err:
                print(json.dumps(le, indent=2, ensure_ascii=False), file=sys.stderr)
                print(f"workflow_wait: workflow reported error: {err}", file=sys.stderr)
                return 2

            event_folder = le.get("event_folder") or le.get("event_id")
            if not event_folder:
                print("workflow_wait: last_event has no event_folder/event_id", file=sys.stderr)
                return 6

            if args.validate_under:
                ev = Path(args.validate_under) / str(event_folder)
                vmsg = _validate_event_videos(ev, strict_both=args.strict_both)
                if vmsg:
                    print(vmsg, file=sys.stderr)
                    return 5
                if not args.strict_both:
                    _maybe_warn_partial(ev)

            if args.write_state:
                out = {
                    "event_id": str(event_folder),
                    "license_plate": le.get("selected_plate") or "",
                    "completed_at": le.get("completed_at"),
                    "base_url": base,
                }
                wp = Path(args.write_state)
                wp.parent.mkdir(parents=True, exist_ok=True)
                wp.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

            print(json.dumps(le, ensure_ascii=False))
            return 0

        time.sleep(max(0.5, args.interval))

    print("workflow_wait: timeout waiting for busy=false", file=sys.stderr)
    if last_payload is not None:
        print(json.dumps(last_payload, indent=2, ensure_ascii=False), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
