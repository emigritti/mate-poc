"""
Unit tests for services.rag_service — query_kb_context and fetch_url_kb_context.

Covers:
  query_kb_context:
    - No kb_collection → returns empty string
    - Tag-filtered query succeeds → returns context
    - Tag-filtered misses → falls back to similarity search
    - No tags → skips tag-filter, goes straight to similarity
    - Context truncated when exceeds kb_max_rag_chars

  fetch_url_kb_context:
    - No matching URL docs → returns empty string
    - Matching doc fetched successfully → content included
    - Fetch failure → "[URL unavailable: ...]" placeholder
    - Tag filter: only URL docs whose tags overlap are fetched
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_kb_doc(url: str, tags: list[str], source_type: str = "url"):
    doc = MagicMock()
    doc.url = url
    doc.tags = tags
    doc.source_type = source_type
    return doc


# ── query_kb_context ──────────────────────────────────────────────────────────

def test_query_kb_context_no_collection_returns_empty():
    from services.rag_service import query_kb_context

    result = asyncio.run(query_kb_context("query", ["Sync"], None))
    assert result == ""


def test_query_kb_context_tag_filtered_hit():
    """When tag-filtered query returns results, context is returned immediately."""
    from services.rag_service import query_kb_context

    mock_col = MagicMock()
    mock_col.query.return_value = {"documents": [["Best practice chunk A"]]}

    result = asyncio.run(query_kb_context("sync query", ["Sync"], mock_col))
    assert "Best practice chunk A" in result
    # Only the tag-filtered query should have been made
    assert mock_col.query.call_count == 1


def test_query_kb_context_tag_filtered_miss_falls_back_to_similarity():
    """When tag-filtered query returns no results, similarity search is used."""
    from services.rag_service import query_kb_context

    call_count = {"n": 0}

    def _mock_query(**kwargs):
        call_count["n"] += 1
        if "where" in kwargs:
            return {"documents": [[]]}   # tag-filtered miss
        return {"documents": [["similarity chunk"]]}

    mock_col = MagicMock()
    mock_col.query.side_effect = lambda **kwargs: _mock_query(**kwargs)

    result = asyncio.run(query_kb_context("sync query", ["Sync"], mock_col))
    assert "similarity chunk" in result
    assert call_count["n"] == 2  # tag-filtered attempt + similarity attempt


def test_query_kb_context_no_tags_skips_to_similarity():
    """When no tags are provided, only the similarity query is executed."""
    from services.rag_service import query_kb_context

    mock_col = MagicMock()
    mock_col.query.return_value = {"documents": [["similarity chunk"]]}

    result = asyncio.run(query_kb_context("sync query", [], mock_col))
    assert "similarity chunk" in result
    # Only one query call — similarity (tag-filtered step skipped)
    assert mock_col.query.call_count == 1


def test_query_kb_context_truncates_at_max_chars():
    """Context exceeding kb_max_rag_chars is truncated."""
    from services.rag_service import query_kb_context
    from config import settings

    original = settings.kb_max_rag_chars
    settings.kb_max_rag_chars = 10
    try:
        mock_col = MagicMock()
        mock_col.query.return_value = {"documents": [["a" * 50, "b" * 50]]}

        result = asyncio.run(query_kb_context("query", [], mock_col))
        assert len(result) == 10
    finally:
        settings.kb_max_rag_chars = original


# ── fetch_url_kb_context ──────────────────────────────────────────────────────

def test_fetch_url_no_matching_docs_returns_empty():
    """No URL docs in kb_docs → returns empty string immediately."""
    from services.rag_service import fetch_url_kb_context

    result = asyncio.run(fetch_url_kb_context(["Sync"], {}))
    assert result == ""


def test_fetch_url_no_tag_overlap_returns_empty():
    """URL docs exist but none have overlapping tags → returns empty string."""
    from services.rag_service import fetch_url_kb_context

    kb_docs = {"d1": _make_kb_doc("https://example.com", tags=["ExportFlow"])}
    result = asyncio.run(fetch_url_kb_context(["Sync"], kb_docs))
    assert result == ""


def test_fetch_url_successful_fetch_returns_content():
    """Matching URL doc is fetched; plain text extracted and returned."""
    from services.rag_service import fetch_url_kb_context

    kb_docs = {"d1": _make_kb_doc("https://example.com/guide", tags=["Sync"])}

    mock_response = MagicMock()
    mock_response.text = "<html><body>Integration guide content</body></html>"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("services.rag_service.httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(fetch_url_kb_context(["Sync"], kb_docs))

    assert "https://example.com/guide" in result
    assert "Integration guide content" in result


def test_fetch_url_fetch_failure_returns_unavailable_placeholder():
    """If a URL fetch fails, the result contains '[URL unavailable: <url>]'."""
    from services.rag_service import fetch_url_kb_context

    kb_docs = {"d1": _make_kb_doc("https://broken.example.com", tags=["Sync"])}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))

    with patch("services.rag_service.httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(fetch_url_kb_context(["Sync"], kb_docs))

    assert "[URL unavailable: https://broken.example.com]" in result


def test_fetch_url_only_url_docs_are_fetched():
    """Non-URL KB docs (e.g., file uploads) are ignored by fetch_url_kb_context."""
    from services.rag_service import fetch_url_kb_context

    file_doc = _make_kb_doc("", tags=["Sync"], source_type="file")
    url_doc  = _make_kb_doc("https://example.com", tags=["Sync"], source_type="url")
    kb_docs  = {"f1": file_doc, "u1": url_doc}

    mock_response = MagicMock()
    mock_response.text = "URL content"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("services.rag_service.httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(fetch_url_kb_context(["Sync"], kb_docs))

    # Only the url doc was fetched — exactly one GET call
    mock_client.get.assert_called_once()
    assert "https://example.com" in result
