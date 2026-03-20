"""Tests for RAG filtering helper functions (Task 8).

Updated for R15 refactoring: functions moved to services.rag_service
and now take collection as a parameter instead of using a global.
"""
import pytest
from unittest.mock import MagicMock
import asyncio


def test_build_rag_context_no_truncation():
    from services.rag_service import build_rag_context
    docs = ["short doc A", "short doc B"]
    result = build_rag_context(docs)
    assert "short doc A" in result
    assert "short doc B" in result


def test_build_rag_context_truncation():
    from services.rag_service import build_rag_context
    from config import settings
    original = settings.ollama_rag_max_chars
    settings.ollama_rag_max_chars = 10
    try:
        result = build_rag_context(["a" * 20, "b" * 20])
        assert len(result) == 10
    finally:
        settings.ollama_rag_max_chars = original


def test_query_rag_tag_filtered_hit():
    from services.rag_service import query_rag_with_tags

    mock_collection = MagicMock()
    mock_collection.query.return_value = {"documents": [["example doc"]]}

    result, source = asyncio.run(query_rag_with_tags("sync products", ["Sync"], mock_collection))
    assert source == "tag_filtered"
    assert "example doc" in result


def test_query_rag_tag_miss_fallback():
    from services.rag_service import query_rag_with_tags

    def mock_query(**kwargs):
        if "where" in kwargs:
            return {"documents": [[]]}
        return {"documents": [["fallback doc"]]}

    mock_collection = MagicMock()
    mock_collection.query.side_effect = lambda **kwargs: mock_query(**kwargs)

    result, source = asyncio.run(query_rag_with_tags("sync products", ["Sync"], mock_collection))
    assert source == "similarity_fallback"
    assert "fallback doc" in result


def test_query_rag_no_collection():
    from services.rag_service import query_rag_with_tags

    result, source = asyncio.run(query_rag_with_tags("sync products", ["Sync"], None))
    assert result == ""
    assert source == "none"


def test_query_rag_no_tags_uses_similarity():
    from services.rag_service import query_rag_with_tags

    mock_collection = MagicMock()
    mock_collection.query.return_value = {"documents": [["similarity doc"]]}

    result, source = asyncio.run(query_rag_with_tags("sync products", [], mock_collection))
    # No tags → skip tag-filtered step → go straight to similarity
    assert source == "similarity_fallback"
