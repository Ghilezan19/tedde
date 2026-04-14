"""
POST /api/customer-links for orchestrator test-send (mock SMS / URL only).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _read_plate_from_event(events_dir: Path, event_id: str) -> str:
    p = events_dir / event_id / "alpr.json"
    if not p.is_file():
        raise SystemExit(f"Missing {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    plate = (data.get("selected_plate") or "").strip()
    if not plate:
        raise SystemExit(f"No selected_plate in {p}")
    return plate


def main() -> int:
    p = argparse.ArgumentParser(description="Create customer portal link (test-send).")
    p.add_argument("--base-url", required=True)
    p.add_argument("--repo-root", required=True, help="Repository root (for events/ and state file).")
    p.add_argument("--state", default="logs/test_portal_last.json", help="Path to test_portal_last.json")
    p.add_argument("--no-sms", action="store_true", help="Set send_sms false (URL only).")
    p.add_argument("event_id", nargs="?", default=None, help="Override event folder; plate from alpr.json")
    args = p.parse_args()

    repo = Path(args.repo_root).resolve()
    state_path = Path(args.state)
    if not state_path.is_absolute():
        state_path = repo / state_path

    base = args.base_url.rstrip("/")
    url = f"{base}/api/customer-links"

    if args.event_id:
        event_id = args.event_id.strip()
        # Resolve events dir like Settings: repo-relative default ./events
        events_dir = repo / "events"
        env_file = repo / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("EVENTS_DIR="):
                    raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if raw.startswith("/"):
                        events_dir = Path(raw)
                    else:
                        if raw.startswith("./"):
                            raw = raw[2:]
                        events_dir = (repo / raw).resolve()
                    break
        license_plate = _read_plate_from_event(events_dir, event_id)
    else:
        if not state_path.is_file():
            print(f"Missing state file {state_path} — run test-record first or pass EVENT_ID.", file=sys.stderr)
            return 1
        st = json.loads(state_path.read_text(encoding="utf-8"))
        event_id = (st.get("event_id") or "").strip()
        license_plate = (st.get("license_plate") or "").strip()
        if not event_id or not license_plate:
            print("State file must contain event_id and license_plate.", file=sys.stderr)
            return 1

    owner = os.environ.get("TEST_PORTAL_OWNER_NAME", "Test Owner").strip() or "Test Owner"
    mechanic = os.environ.get("TEST_PORTAL_MECHANIC_NAME", "Test Mechanic").strip() or "Test Mechanic"
    phone = os.environ.get("TEST_PORTAL_PHONE", "+00000000000").strip() or "+00000000000"

    body = {
        "event_id": event_id,
        "license_plate": license_plate,
        "owner_name": owner,
        "mechanic_name": mechanic,
        "phone_number": phone,
        "send_sms": not args.no_sms,
    }
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {err_body}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(data, indent=2, ensure_ascii=False))
    if data.get("success") and data.get("public_url"):
        print("\nOpen in browser (quiz, then videos):", data["public_url"])
        if args.no_sms:
            print("(send_sms was false — no SMS sent.)")
        else:
            print("SMS:", data.get("sms_status"), data.get("sms_error") or "")
    return 0 if data.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
