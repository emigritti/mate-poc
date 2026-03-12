"""Unit tests — _detect_level() and log_agent()."""
import os
os.environ.setdefault("OLLAMA_HOST",  "http://fake-ollama:11434")
os.environ.setdefault("MONGO_URI",    "mongodb://fake-mongo:27017")
os.environ.setdefault("CHROMA_HOST",  "fake-chroma")

from datetime import datetime, timezone
import pytest
from main import _detect_level
from schemas import LogLevel


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

    def test_case_sensitivity(self):
        # [llm] lowercase should NOT match — prefixes are uppercase in log_agent calls
        assert _detect_level("[llm] something") == LogLevel.INFO
