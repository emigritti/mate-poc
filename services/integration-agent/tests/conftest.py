"""
Shared pytest configuration.

IMPORTANT: environment variables MUST be set before any app module is imported,
because pydantic-settings reads them at Settings() instantiation time (module level).
This file is loaded by pytest before any test module.
"""

import os

# Required by config.Settings — no defaults, so tests fail without these.
os.environ.setdefault("MONGO_URI",    "mongodb://localhost:27017")
os.environ.setdefault("OLLAMA_HOST",  "http://localhost:11434")
os.environ.setdefault("CHROMA_HOST",  "localhost")

# Ensure API_KEY is absent so settings.api_key = None and _require_token
# bypasses auth enforcement (PoC dev mode).  setdefault("API_KEY", "") is
# NOT sufficient because _require_token checks `is None`, not falsiness.
os.environ.pop("API_KEY", None)
