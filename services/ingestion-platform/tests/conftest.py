"""
Ingestion Platform — Test Configuration

Sets up environment variables before any Settings() instantiation.
Pattern mirrors integration-agent/tests/conftest.py.
"""
import os

# Required env vars — must be set before any module-level Settings() import
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("CHROMA_HOST", "localhost")

# ANTHROPIC_API_KEY is optional; ensure it doesn't break Settings
os.environ.pop("ANTHROPIC_API_KEY", None)
# ADR-X4: disable contextual retrieval in tests (no LLM reachable in CI)
os.environ.setdefault("CONTEXTUAL_RETRIEVAL_ENABLED", "false")

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def mock_mongo_collection():
    """In-memory mock for a motor AsyncIOMotorCollection."""
    col = AsyncMock()
    col.find_one = AsyncMock(return_value=None)
    col.insert_one = AsyncMock()
    col.replace_one = AsyncMock()
    col.delete_one = AsyncMock()
    col.find = MagicMock()
    col.find.return_value.to_list = AsyncMock(return_value=[])
    return col


@pytest.fixture
def mock_chroma_collection():
    """Minimal ChromaDB collection mock."""
    col = MagicMock()
    col.upsert = MagicMock()
    col.delete = MagicMock()
    col.get = MagicMock(return_value={"ids": [], "documents": [], "metadatas": []})
    return col
