"""
Debug agent logging stub.
No-op implementation used when the debug agent log is not active.
"""
from __future__ import annotations
from typing import Any


def agent_log(
    hypothesis_id: str = "",
    location: str = "",
    message: str = "",
    data: Any = None,
) -> None:
    """No-op stub for debug agent logging."""
    pass
