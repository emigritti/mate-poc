"""Unit tests — LogLevel enum and LogEntry schema."""
from datetime import datetime, timezone
import pytest
from schemas import LogLevel, LogEntry


class TestLogLevel:
    def test_all_expected_levels_exist(self):
        expected = {"INFO", "LLM", "RAG", "SUCCESS", "WARN", "ERROR", "CANCEL"}
        assert {l.value for l in LogLevel} == expected

    def test_log_level_is_str(self):
        assert isinstance(LogLevel.INFO, str)
        assert LogLevel.LLM == "LLM"


class TestLogEntry:
    def test_log_entry_creation(self):
        entry = LogEntry(
            ts=datetime.now(timezone.utc),
            level=LogLevel.INFO,
            message="Test message",
        )
        assert entry.level == LogLevel.INFO
        assert entry.message == "Test message"
        assert entry.ts.tzinfo is not None  # must be UTC-aware

    def test_log_entry_model_dump_contains_expected_keys(self):
        entry = LogEntry(
            ts=datetime.now(timezone.utc),
            level=LogLevel.LLM,
            message="LLM call",
        )
        d = entry.model_dump()
        assert set(d.keys()) == {"ts", "level", "message"}
