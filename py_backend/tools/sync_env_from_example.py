"""
Append missing KEY=value lines from .env_example into .env (never overwrites existing keys).

Usage (repo root, PYTHONPATH=py_backend):
  python -m tools.sync_env_from_example
  python -m tools.sync_env_from_example --dry-run
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV = REPO_ROOT / ".env"
DEFAULT_EXAMPLE = REPO_ROOT / ".env_example"

# KEY=value (KEY must start with letter or underscore for our vars)
_LINE_RE = re.compile(r"^[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(.*)$")


def _parse_keys_and_order(content: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Return (key->value map, ordered list of (key, value) from first occurrence)."""
    seen: dict[str, str] = {}
    order: list[tuple[str, str]] = []
    for raw in content.splitlines():
        line = raw.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).rstrip()
        if key not in seen:
            order.append((key, val))
        seen[key] = val
    return seen, order


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync missing env keys from .env_example into .env")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--example", type=Path, default=DEFAULT_EXAMPLE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    example_path = args.example.resolve()
    env_path = args.env.resolve()

    if not example_path.is_file():
        print(f"Lipsește {example_path}", file=sys.stderr)
        sys.exit(1)
    if not env_path.is_file():
        print(f"Lipsește {env_path} — copiază din .env_example mai întâi.", file=sys.stderr)
        sys.exit(1)

    ex_map, ex_order = _parse_keys_and_order(example_path.read_text(encoding="utf-8"))
    cur_map, _ = _parse_keys_and_order(env_path.read_text(encoding="utf-8"))

    missing: list[tuple[str, str]] = [(k, ex_map[k]) for k, _ in ex_order if k not in cur_map]

    if not missing:
        print("Nicio cheie lipsă — .env conține deja toate variabilele din .env_example.")
        sys.exit(0)

    print("Chei de adăugat din .env_example:")
    for k, v in missing:
        preview = v if len(v) <= 72 else v[:69] + "..."
        print(f"  + {k}={preview}")

    if args.dry_run:
        print("\n(--dry-run: nu s-a scris nimic în .env)")
        sys.exit(0)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = env_path.with_suffix(env_path.suffix + f".bak.{ts}")
    shutil.copy2(env_path, bak)
    print(f"\nBackup: {bak}")

    block = (
        "\n# --- Added by sync-env (keys were in .env_example but missing in .env) ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    text = env_path.read_text(encoding="utf-8")
    if text and not text.endswith("\n"):
        text += "\n"
    env_path.write_text(text + block, encoding="utf-8")
    print(f"Scriere {len(missing)} linii în {env_path}")


if __name__ == "__main__":
    main()
