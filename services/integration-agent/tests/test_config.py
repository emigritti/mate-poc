"""
Unit tests — config module
ADR-016: Fail-fast on missing required environment variables.

Coverage:
  - Settings instantiation fails if OLLAMA_HOST is missing
  - Settings instantiation fails if MONGO_URI is missing
  - Optional API_KEY defaults to None (not required)
  - cors_origins parses comma-separated string correctly

Design note: config.py executes `settings = Settings()` at module level.
The import here runs with conftest-provided env vars so that module-level
instantiation succeeds.  Individual tests then call `Settings(...)` with
monkeypatched env vars to exercise validation behaviour in isolation.
"""

import pytest
from pydantic import ValidationError

# Module-level import — conftest.py has already set OLLAMA_HOST and MONGO_URI,
# so the module-level settings = Settings() inside config.py succeeds.
from config import Settings


class TestSettings:
    def test_fails_without_ollama_host(self, monkeypatch):
        """Settings must raise if OLLAMA_HOST is absent.

        monkeypatch removes the conftest-provided env var so that a fresh
        Settings() call without the var raises ValidationError.
        """
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        with pytest.raises(ValidationError):
            Settings(mongo_uri="mongodb://localhost:27017")

    def test_fails_without_mongo_uri(self, monkeypatch):
        """Settings must raise if MONGO_URI is absent."""
        monkeypatch.delenv("MONGO_URI", raising=False)
        with pytest.raises(ValidationError):
            Settings(ollama_host="http://localhost:11434")

    def test_api_key_optional(self):
        """API_KEY should be falsy (None or empty string) — no auth in PoC mode.

        conftest sets API_KEY="" so pydantic-settings resolves it as an empty
        string rather than None.  Both values indicate 'no auth required'.
        """
        s = Settings(
            ollama_host="http://localhost:11434",
            mongo_uri="mongodb://localhost:27017",
        )
        assert not s.api_key  # accepts None or ""

    def test_cors_origins_comma_separated(self):
        """cors_origins is stored as a raw comma-separated string."""
        s = Settings(
            ollama_host="http://localhost:11434",
            mongo_uri="mongodb://localhost:27017",
            cors_origins="http://localhost:8080,http://localhost:3000",
        )
        origins = [o.strip() for o in s.cors_origins.split(",") if o.strip()]
        assert "http://localhost:8080" in origins
        assert "http://localhost:3000" in origins
        assert len(origins) == 2

    def test_default_ollama_model(self):
        s = Settings(
            ollama_host="http://localhost:11434",
            mongo_uri="mongodb://localhost:27017",
        )
        assert s.ollama_model == "llama3.1:8b"


def test_log_ttl_hours_default():
    """LOG_TTL_HOURS defaults to 4 when not set."""
    s = Settings()
    assert s.log_ttl_hours == 4


def test_log_ttl_hours_env_override(monkeypatch):
    """LOG_TTL_HOURS can be overridden via environment variable."""
    monkeypatch.setenv("LOG_TTL_HOURS", "8")
    s = Settings()
    assert s.log_ttl_hours == 8


def test_tag_num_predict_default():
    from config import Settings
    s = Settings()
    assert s.tag_num_predict == 20


def test_tag_timeout_seconds_default():
    from config import Settings
    s = Settings()
    assert s.tag_timeout_seconds == 15


def test_tag_temperature_default():
    from config import Settings
    s = Settings()
    assert s.tag_temperature == 0.0
