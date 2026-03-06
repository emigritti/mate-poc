"""
Unit tests — config module
ADR-016: Fail-fast on missing required environment variables.

Coverage:
  - Settings instantiation fails if OLLAMA_HOST is missing
  - Settings instantiation fails if MONGO_URI is missing
  - Optional API_KEY defaults to None (not required)
  - cors_origins parses comma-separated string correctly
"""

import pytest
from pydantic import ValidationError


class TestSettings:
    def test_fails_without_ollama_host(self):
        """Settings must raise if OLLAMA_HOST is absent."""
        from config import Settings
        with pytest.raises((ValidationError, Exception)):
            Settings(mongo_uri="mongodb://localhost:27017")  # missing ollama_host

    def test_fails_without_mongo_uri(self):
        """Settings must raise if MONGO_URI is absent."""
        from config import Settings
        with pytest.raises((ValidationError, Exception)):
            Settings(ollama_host="http://localhost:11434")  # missing mongo_uri

    def test_api_key_optional(self):
        """API_KEY should default to None — no auth in unauthenticated PoC mode."""
        from config import Settings
        s = Settings(
            ollama_host="http://localhost:11434",
            mongo_uri="mongodb://localhost:27017",
        )
        assert s.api_key is None

    def test_cors_origins_comma_separated(self):
        """cors_origins is stored as a raw comma-separated string."""
        from config import Settings
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
        from config import Settings
        s = Settings(
            ollama_host="http://localhost:11434",
            mongo_uri="mongodb://localhost:27017",
        )
        assert s.ollama_model == "llama3.1:8b"
