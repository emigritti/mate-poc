"""
Unit tests for POST /api/v1/kb/batch-upload endpoint (Phase 5).

TDD: tests written before implementing the endpoint in routers/kb.py.

Verifies:
  - Returns per-file results for multiple valid files
  - Partial success: one failed file does not abort the others
  - Rejects requests exceeding the 10-file limit with 400
  - Requires auth token (401 without token)
  - Returns 200 with results array (not 207, per plan)
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from document_parser import DoclingChunk


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_chunks(section: str = "## Intro", count: int = 2) -> list[DoclingChunk]:
    return [
        DoclingChunk(text=f"Chunk {i}.", chunk_type="text",
                     page_num=1, section_header=section, index=i, metadata={})
        for i in range(count)
    ]


@pytest.fixture(scope="module")
def client():
    """TestClient with all external services mocked at startup."""
    with (
        patch("db.init_db",          new_callable=AsyncMock),
        patch("db.close_db",         new_callable=AsyncMock),
        patch("main._init_chromadb", new_callable=AsyncMock),
    ):
        from main import app
        with TestClient(app) as c:
            yield c


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_batch_upload_returns_per_file_results(client):
    """Uploading two valid files returns a results array with one entry per file."""
    chunks = _make_chunks()

    with patch("routers.kb.parse_with_docling", new=AsyncMock(return_value=chunks)), \
         patch("routers.kb.suggest_kb_tags_via_llm", new=AsyncMock(return_value=["api"])), \
         patch("routers.kb.summarize_section", new=AsyncMock(return_value=None)), \
         patch("routers.kb.hybrid_retriever"), \
         patch("routers.kb.state") as mock_state, \
         patch("routers.kb.db") as mock_db:
        mock_state.kb_collection = MagicMock()
        mock_state.summaries_col = None
        mock_state.kb_docs = {}
        mock_state.kb_chunks = {}
        mock_db.kb_documents_col = None

        response = client.post(
            "/api/v1/kb/batch-upload",
            files=[
                ("files", ("doc1.md", b"# Doc 1", "text/markdown")),
                ("files", ("doc2.md", b"# Doc 2", "text/markdown")),
            ],
        )

    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) == 2


def test_batch_upload_result_contains_expected_fields(client):
    """Each result entry contains filename, status, and chunks_created."""
    chunks = _make_chunks(count=3)

    with patch("routers.kb.parse_with_docling", new=AsyncMock(return_value=chunks)), \
         patch("routers.kb.suggest_kb_tags_via_llm", new=AsyncMock(return_value=["api"])), \
         patch("routers.kb.summarize_section", new=AsyncMock(return_value=None)), \
         patch("routers.kb.hybrid_retriever"), \
         patch("routers.kb.state") as mock_state, \
         patch("routers.kb.db") as mock_db:
        mock_state.kb_collection = MagicMock()
        mock_state.summaries_col = None
        mock_state.kb_docs = {}
        mock_state.kb_chunks = {}
        mock_db.kb_documents_col = None

        response = client.post(
            "/api/v1/kb/batch-upload",
            files=[("files", ("guide.pdf", b"%PDF content", "application/pdf"))],
        )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["filename"] == "guide.pdf"
    assert result["status"] == "success"
    assert result["chunks_created"] == 3
    assert "error" not in result or result["error"] is None


def test_batch_upload_partial_success_when_one_file_fails(client):
    """If one file fails to parse, its result has status=error; other files still succeed."""
    good_chunks = _make_chunks(count=2)

    call_count = 0

    async def _parse_side_effect(content, file_type):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("corrupt file")
        return good_chunks

    with patch("routers.kb.parse_with_docling", side_effect=_parse_side_effect), \
         patch("routers.kb.suggest_kb_tags_via_llm", new=AsyncMock(return_value=["api"])), \
         patch("routers.kb.summarize_section", new=AsyncMock(return_value=None)), \
         patch("routers.kb.hybrid_retriever"), \
         patch("routers.kb.state") as mock_state, \
         patch("routers.kb.db") as mock_db:
        mock_state.kb_collection = MagicMock()
        mock_state.summaries_col = None
        mock_state.kb_docs = {}
        mock_state.kb_chunks = {}
        mock_db.kb_documents_col = None

        response = client.post(
            "/api/v1/kb/batch-upload",
            files=[
                ("files", ("bad.pdf",  b"corrupt",   "application/pdf")),
                ("files", ("good.md",  b"# Good doc", "text/markdown")),
            ],
        )

    assert response.status_code == 200
    results = response.json()["results"]
    statuses = {r["filename"]: r["status"] for r in results}
    assert statuses["bad.pdf"] == "error"
    assert statuses["good.md"] == "success"


def test_batch_upload_rejects_more_than_10_files(client):
    """More than 10 files in a single request returns 400."""
    files = [
        ("files", (f"doc{i}.md", b"# Content", "text/markdown"))
        for i in range(11)
    ]

    response = client.post("/api/v1/kb/batch-upload", files=files)

    assert response.status_code == 400
    assert "10" in response.json()["detail"]


def test_batch_upload_requires_auth_token(client):
    """Endpoint is protected: missing token returns 401."""
    # Remove auth header — TestClient sends no Authorization by default
    # Patch settings.api_key to a non-None value so auth is enforced
    with patch("routers.kb.settings") as mock_settings, \
         patch("auth.settings") as mock_auth_settings:
        mock_settings.api_key = "secret"
        mock_settings.kb_max_file_bytes = 10 * 1024 * 1024
        mock_auth_settings.api_key = "secret"

        response = client.post(
            "/api/v1/kb/batch-upload",
            files=[("files", ("doc.md", b"# Doc", "text/markdown"))],
        )

    assert response.status_code == 401
