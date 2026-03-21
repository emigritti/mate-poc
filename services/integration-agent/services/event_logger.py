"""
Append-only audit event log (R19-MVP / ADR-023).

Writes structured events to the MongoDB 'events' collection.
All mutations in catalog, approvals, and documents routers
call record_event() fire-and-forget (failures are logged, not raised).
"""
import logging
from datetime import datetime, timezone

import db as db_module

logger = logging.getLogger(__name__)


async def record_event(event_type: str, payload: dict) -> None:
    """Append one audit event. Silently ignores failures (non-critical path).

    Args:
        event_type: Dot-separated event name, e.g. "catalog.generated", "approval.approved".
        payload:    Arbitrary context dict (integration_id, user, etc.).
    """
    if db_module.events_col is None:
        return  # DB not initialised (test/offline mode)
    try:
        await db_module.events_col.insert_one({
            "event_type": event_type,
            "ts": datetime.now(timezone.utc),
            **payload,
        })
    except Exception as exc:
        logger.warning("[AUDIT] Failed to record event %s: %s", event_type, exc)
