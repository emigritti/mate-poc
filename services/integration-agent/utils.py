"""
Shared utilities for integration-agent routers.

Centralises small helpers that were duplicated across router modules (R15).
"""

from datetime import datetime, timezone


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
