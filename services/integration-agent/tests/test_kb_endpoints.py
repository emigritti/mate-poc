"""
Unit tests — Knowledge Base API endpoints.

Uses FastAPI TestClient with mocked external services (ChromaDB, MongoDB)
so no real infrastructure is needed.

Coverage:
  - KB list documents → 200
  - KB get non-existent → 404
  - KB delete non-existent → 404
  - KB update tags non-existent → 404
  - KB update tags empty → 422
  - KB search empty query → 422
  - KB stats → 200 (empty KB)
  - KB upload unsupported file → 415
  - KB upload oversized file → 413
"""

import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    """
    TestClient with mocked external connections.

    Patches applied before lifespan runs so no real DB/ChromaDB connections
    are attempted.  db.catalog_col etc. remain None → MongoDB upserts skipped.
    """
    with (
        patch("db.init_db",          new_callable=AsyncMock),
        patch("db.close_db",         new_callable=AsyncMock),
        patch("main._init_chromadb", new_callable=AsyncMock),
    ):
        from main import app
        with TestClient(app) as c:
            yield c


class TestKBListAndGet:
    def test_list_returns_200(self, client):
        response = client.get("/api/v1/kb/documents")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert isinstance(data["data"], list)

    def test_get_nonexistent_returns_404(self, client):
        response = client.get("/api/v1/kb/documents/KB-NONEXISTENT")
        assert response.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        response = client.delete("/api/v1/kb/documents/KB-NONEXISTENT")
        assert response.status_code == 404


class TestKBUpdateTags:
    def test_update_tags_nonexistent_returns_404(self, client):
        response = client.put(
            "/api/v1/kb/documents/KB-NONEXISTENT/tags",
            json={"tags": ["Integration"]},
        )
        assert response.status_code == 404

    def test_update_tags_empty_list_returns_422(self, client):
        response = client.put(
            "/api/v1/kb/documents/KB-NONEXISTENT/tags",
            json={"tags": []},
        )
        assert response.status_code == 422


class TestKBSearch:
    def test_search_without_query_returns_422(self, client):
        response = client.get("/api/v1/kb/search")
        assert response.status_code == 422

    def test_search_empty_query_returns_422(self, client):
        response = client.get("/api/v1/kb/search?q=")
        assert response.status_code == 422


class TestKBStats:
    def test_stats_returns_200(self, client):
        response = client.get("/api/v1/kb/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_documents" in data
        assert "total_chunks" in data
        assert "file_types" in data
        assert "all_tags" in data


class TestKBUploadValidation:
    def test_upload_unsupported_mime_returns_415(self, client):
        response = client.post(
            "/api/v1/kb/upload",
            files={"file": ("archive.zip", io.BytesIO(b"PK\x03\x04"), "application/zip")},
        )
        assert response.status_code == 415

    def test_upload_oversized_returns_413(self, client):
        # Build a file larger than 10MB
        big = b"x" * (10_485_760 + 1024)
        response = client.post(
            "/api/v1/kb/upload",
            files={"file": ("big.md", io.BytesIO(big), "text/markdown")},
        )
        assert response.status_code == 413
