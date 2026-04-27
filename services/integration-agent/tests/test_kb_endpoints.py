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
  - KB export → 200 with JSON bundle
  - KB export with source_types filter → filters documents and chunks
  - KB export multiple comma-separated types → correct set
  - KB export unknown source_type → 400
  - KB import valid bundle → 200 with summary
  - KB import skip existing (overwrite=false) → skips duplicate
  - KB import overwrite existing → replaces duplicate
  - KB import invalid JSON → 400
  - KB import wrong version → 400
  - KB import unknown source_type filter → 400
  - KB import missing file → 422
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


# ── KB Export / Import ────────────────────────────────────────────────────────

import json
from unittest.mock import patch as _patch

_VALID_BUNDLE = {
    "export_version": "1.0",
    "exported_at": "2026-04-27T10:00:00Z",
    "source_types_included": ["file", "url"],
    "kb_documents": [
        {
            "id": "KB-AABBCCDD",
            "filename": "best_practice.pdf",
            "file_type": "pdf",
            "file_size_bytes": 1024,
            "tags": ["integration", "api"],
            "chunk_count": 2,
            "content_preview": "This document describes…",
            "uploaded_at": "2026-04-27T09:00:00Z",
            "source_type": "file",
            "url": None,
        }
    ],
    "chunks": [
        {
            "id": "KB-AABBCCDD-chunk-0",
            "text": "First chunk text.",
            "metadata": {"document_id": "KB-AABBCCDD", "source_type": "file", "chunk_index": 0},
        },
        {
            "id": "KB-AABBCCDD-chunk-1",
            "text": "Second chunk text.",
            "metadata": {"document_id": "KB-AABBCCDD", "source_type": "file", "chunk_index": 1},
        },
    ],
}


class TestKBExport:
    def test_export_returns_200_json_bundle(self, client):
        response = client.get("/api/v1/kb/export")
        assert response.status_code == 200
        data = response.json()
        assert data["export_version"] == "1.0"
        assert "exported_at" in data
        assert isinstance(data["kb_documents"], list)
        assert isinstance(data["chunks"], list)

    def test_export_source_types_filter_returns_correct_types(self, client):
        response = client.get("/api/v1/kb/export?source_types=url")
        assert response.status_code == 200
        data = response.json()
        assert data["source_types_included"] == ["url"]
        for doc in data["kb_documents"]:
            assert doc["source_type"] == "url"

    def test_export_unknown_source_type_returns_400(self, client):
        response = client.get("/api/v1/kb/export?source_types=unknown_type")
        assert response.status_code == 400

    def test_export_multiple_types_comma_separated(self, client):
        response = client.get("/api/v1/kb/export?source_types=file,url")
        assert response.status_code == 200
        data = response.json()
        assert set(data["source_types_included"]) == {"file", "url"}


class TestKBImport:
    def _post_bundle(self, client, bundle, *, source_types=None, overwrite=False):
        params = {}
        if source_types:
            params["source_types"] = source_types
        if overwrite:
            params["overwrite"] = "true"
        return client.post(
            "/api/v1/kb/import",
            params=params,
            files={"bundle_file": ("kb_export.json", io.BytesIO(json.dumps(bundle).encode()), "application/json")},
        )

    def test_import_valid_bundle_returns_200(self, client):
        import state
        # Ensure the document is not already in state to get a clean import count
        state.kb_docs.pop("KB-AABBCCDD", None)

        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        mock_collection.upsert.return_value = None

        import state as st
        original_col = st.kb_collection
        try:
            st.kb_collection = mock_collection
            response = self._post_bundle(client, _VALID_BUNDLE)
        finally:
            st.kb_collection = original_col

        assert response.status_code == 200
        data = response.json()
        assert data["documents_imported"] >= 1
        assert data["chunks_imported"] >= 1
        assert isinstance(data["errors"], list)

    def test_import_skip_existing_document(self, client):
        import state
        from schemas import KBDocument
        existing = KBDocument(**{k: v for k, v in _VALID_BUNDLE["kb_documents"][0].items()})
        state.kb_docs["KB-AABBCCDD"] = existing

        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": ["KB-AABBCCDD-chunk-0", "KB-AABBCCDD-chunk-1"],
            "documents": ["t1", "t2"],
            "metadatas": [{}, {}],
        }

        import state as st
        original_col = st.kb_collection
        try:
            st.kb_collection = mock_collection
            response = self._post_bundle(client, _VALID_BUNDLE, overwrite=False)
        finally:
            st.kb_collection = original_col
            state.kb_docs.pop("KB-AABBCCDD", None)

        assert response.status_code == 200
        data = response.json()
        assert data["documents_skipped"] >= 1
        assert data["chunks_skipped"] >= 1

    def test_import_overwrite_replaces_existing(self, client):
        import state
        from schemas import KBDocument
        existing = KBDocument(**{k: v for k, v in _VALID_BUNDLE["kb_documents"][0].items()})
        state.kb_docs["KB-AABBCCDD"] = existing

        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        mock_collection.upsert.return_value = None

        import state as st
        original_col = st.kb_collection
        try:
            st.kb_collection = mock_collection
            response = self._post_bundle(client, _VALID_BUNDLE, overwrite=True)
        finally:
            st.kb_collection = original_col
            state.kb_docs.pop("KB-AABBCCDD", None)

        assert response.status_code == 200
        data = response.json()
        assert data["documents_imported"] >= 1

    def test_import_invalid_json_returns_400(self, client):
        response = client.post(
            "/api/v1/kb/import",
            files={"bundle_file": ("bad.json", io.BytesIO(b"not valid json{{{"), "application/json")},
        )
        assert response.status_code == 400

    def test_import_wrong_version_returns_400(self, client):
        bad_bundle = {**_VALID_BUNDLE, "export_version": "99.0"}
        response = self._post_bundle(client, bad_bundle)
        assert response.status_code == 400

    def test_import_unknown_source_type_filter_returns_400(self, client):
        response = self._post_bundle(client, _VALID_BUNDLE, source_types="nonexistent")
        assert response.status_code == 400

    def test_import_missing_file_returns_422(self, client):
        response = client.post("/api/v1/kb/import")
        assert response.status_code == 422
