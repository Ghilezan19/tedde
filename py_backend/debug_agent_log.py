"""Append NDJSON lines for Cursor debug session (no secrets in callers)."""

from __future__ import annotations

import json
import time
from pathlib import Path

_LOG = Path(__file__).resolve().parent.parent / ".cursor" / "debug-e5dd89.log"


def agent_log(
    *,
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict | None = None,
    run_id: str = "pre-fix",
) -> None:
    try:
        payload = {
            "sessionId": "e5dd89",
            "timestamp": int(time.time() * 1000),
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "runId": run_id,
            "data": data or {},
        }
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass
