"""
Run startup_check probes without starting FastAPI (first-configuration / ops).

Usage (from repo root):
  PYTHONPATH=py_backend python -m tools.health_standalone
  PYTHONPATH=py_backend python -m tools.health_standalone --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Tedde startup health probes (standalone).")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args()

    import startup_check

    results = asyncio.run(startup_check.run_all())
    overall = results.get("overall", "error")

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print("overall:", overall)
        for key, val in results.items():
            if key == "started_at" or not isinstance(val, dict):
                continue
            ok = val.get("ok")
            mark = "OK" if ok else "FAIL"
            print(f"  [{mark}] {key}: {val.get('detail', val)}")

    # ok / degraded => exit 0 (cameras may come later); error => 1
    if overall == "error":
        sys.exit(1)
    if overall == "degraded":
        print(
            "(avertisment: camere indisponibile sau parțial — continuarea first-config este permisă)",
            file=sys.stderr,
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
