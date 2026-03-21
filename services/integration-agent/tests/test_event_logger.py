"""Tests for services.event_logger.record_event (R19-MVP)."""
import asyncio
from unittest.mock import AsyncMock, patch
import pytest

import db as db_module


def test_record_event_inserts_document():
    """record_event inserts a document with event_type and ts fields."""
    from services.event_logger import record_event
    mock_col = AsyncMock()
    mock_col.insert_one = AsyncMock()

    with patch.object(db_module, "events_col", mock_col):
        asyncio.run(record_event("catalog.generated", {"integration_count": 3}))

    mock_col.insert_one.assert_awaited_once()
    call_args = mock_col.insert_one.call_args[0][0]
    assert call_args["event_type"] == "catalog.generated"
    assert "ts" in call_args
    assert call_args["integration_count"] == 3


def test_record_event_silent_when_col_is_none():
    """record_event must not raise when events_col is None (offline/test mode)."""
    from services.event_logger import record_event
    with patch.object(db_module, "events_col", None):
        asyncio.run(record_event("catalog.generated", {}))  # must not raise


def test_record_event_silent_on_db_error():
    """record_event swallows DB errors (non-critical path)."""
    from services.event_logger import record_event
    mock_col = AsyncMock()
    mock_col.insert_one = AsyncMock(side_effect=Exception("DB unavailable"))

    with patch.object(db_module, "events_col", mock_col):
        asyncio.run(record_event("catalog.generated", {}))  # must not raise
