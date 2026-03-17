"""Unit tests — _detect_level() and log_agent()."""
import os
os.environ.setdefault("OLLAMA_HOST",  "http://fake-ollama:11434")
os.environ.setdefault("MONGO_URI",    "mongodb://fake-mongo:27017")
os.environ.setdefault("CHROMA_HOST",  "fake-chroma")

from datetime import datetime, timezone
import pytest
import main as agent_main
from main import _detect_level
from schemas import LogEntry, LogLevel


class TestDetectLevel:
    def test_llm_prefix(self):
        assert _detect_level("[LLM] Calling model") == LogLevel.LLM

    def test_rag_prefix(self):
        assert _detect_level("[RAG] Querying ChromaDB") == LogLevel.RAG

    def test_error_prefix(self):
        assert _detect_level("[ERROR] Connection failed") == LogLevel.ERROR

    def test_guard_prefix(self):
        assert _detect_level("[GUARD] Output rejected") == LogLevel.WARN

    def test_cancel_stop_symbol(self):
        assert _detect_level("⛔ Agent execution cancelled") == LogLevel.CANCEL

    def test_cancel_keyword(self):
        assert _detect_level("Task cancelled by user") == LogLevel.CANCEL

    def test_success_completed(self):
        assert _detect_level("Generation completed. Pending documents...") == LogLevel.SUCCESS

    def test_success_approved(self):
        assert _detect_level("Approved and saved to RAG.") == LogLevel.SUCCESS

    def test_default_info(self):
        assert _detect_level("Started Agent Processing Task") == LogLevel.INFO

    def test_success_checkmark(self):
        assert _detect_level("✓ Integration spec saved") == LogLevel.SUCCESS

    def test_case_sensitivity(self):
        # [llm] lowercase should NOT match — prefixes are uppercase in log_agent calls
        assert _detect_level("[llm] something") == LogLevel.INFO


class TestLogAgent:
    def test_log_agent_appends_log_entry(self):
        """log_agent() must append a LogEntry with correct level and message."""
        original_len = len(agent_main.agent_logs)
        agent_main.log_agent("[LLM] Test call")
        assert len(agent_main.agent_logs) == original_len + 1
        entry = agent_main.agent_logs[-1]
        assert isinstance(entry, LogEntry)
        assert entry.level == LogLevel.LLM
        assert entry.message == "Test call"  # bracket prefix stripped; level is the structured field
        assert entry.ts.tzinfo is not None
        # cleanup
        agent_main.agent_logs.pop()

    def test_log_agent_strips_bracket_prefix(self):
        """Stored message must NOT repeat the bracket prefix — level is the structured field."""
        original_len = len(agent_main.agent_logs)
        agent_main.log_agent("[ERROR] Something went wrong")
        entry = agent_main.agent_logs[-1]
        assert entry.level == LogLevel.ERROR
        assert entry.message == "Something went wrong"
        assert not entry.message.startswith("[ERROR]")
        # cleanup
        agent_main.agent_logs.pop()

    def test_log_agent_strips_kb_rag_prefix(self):
        """[KB-RAG] prefix is stripped and detected as RAG level."""
        original_len = len(agent_main.agent_logs)
        agent_main.log_agent("[KB-RAG] KB context found: 450 chars")
        entry = agent_main.agent_logs[-1]
        assert entry.level == LogLevel.RAG
        assert entry.message == "KB context found: 450 chars"
        # cleanup
        agent_main.agent_logs.pop()


def test_prune_removes_old_entries():
    """_prune_logs() must remove LogEntry objects older than settings.log_ttl_hours."""
    from datetime import timedelta
    from unittest.mock import patch

    old_ts = datetime.now(timezone.utc) - timedelta(hours=5)
    new_ts = datetime.now(timezone.utc)

    old_entry = LogEntry(ts=old_ts, level=LogLevel.INFO, message="old")
    new_entry = LogEntry(ts=new_ts, level=LogLevel.INFO, message="new")

    agent_main.agent_logs[:] = [old_entry, new_entry]
    try:
        with patch.object(agent_main.settings, "log_ttl_hours", 4):
            agent_main._prune_logs()
        assert len(agent_main.agent_logs) == 1
        assert agent_main.agent_logs[0].message == "new"
    finally:
        agent_main.agent_logs.clear()


@pytest.fixture(scope="module")
def logs_client():
    from unittest.mock import AsyncMock, patch
    with (
        patch("db.init_db",            new_callable=AsyncMock),
        patch("db.close_db",           new_callable=AsyncMock),
        patch("main._init_chromadb",   new_callable=AsyncMock),
        patch("main._prune_logs_loop", new_callable=AsyncMock),
    ):
        from main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield c


def test_logs_endpoint_returns_structured_entries(logs_client):
    """GET /api/v1/agent/logs must return list of {ts, level, message} dicts."""
    agent_main.agent_logs[:] = [
        LogEntry(ts=datetime.now(timezone.utc), level=LogLevel.LLM, message="LLM call"),
        LogEntry(ts=datetime.now(timezone.utc), level=LogLevel.ERROR, message="Oops"),
    ]
    try:
        response = logs_client.get("/api/v1/agent/logs")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        logs = data["logs"]
        assert len(logs) == 2
        assert logs[0]["level"] == "LLM"
        assert logs[1]["level"] == "ERROR"
        assert "ts" in logs[0]
        assert "message" in logs[0]
    finally:
        agent_main.agent_logs.clear()
