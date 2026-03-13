"""Tests for RAG filtering helper functions (Task 8)."""
import pytest
from unittest.mock import MagicMock
import asyncio


def test_build_rag_context_no_truncation():
    from main import _build_rag_context
    docs = ["short doc A", "short doc B"]
    result = _build_rag_context(docs)
    assert "short doc A" in result
    assert "short doc B" in result


def test_build_rag_context_truncation():
    from main import _build_rag_context
    import main
    original = main.settings.ollama_rag_max_chars
    main.settings.ollama_rag_max_chars = 10
    try:
        result = _build_rag_context(["a" * 20, "b" * 20])
        assert len(result) == 10
    finally:
        main.settings.ollama_rag_max_chars = original


def test_query_rag_tag_filtered_hit():
    from main import _query_rag_with_tags
    import main

    mock_collection = MagicMock()
    mock_collection.query.return_value = {"documents": [["example doc"]]}
    main.collection = mock_collection

    result, source = asyncio.run(_query_rag_with_tags("sync products", ["Sync"]))
    assert source == "tag_filtered"
    assert "example doc" in result


def test_query_rag_tag_miss_fallback():
    from main import _query_rag_with_tags
    import main

    def mock_query(**kwargs):
        if "where" in kwargs:
            return {"documents": [[]]}
        return {"documents": [["fallback doc"]]}

    mock_collection = MagicMock()
    mock_collection.query.side_effect = lambda **kwargs: mock_query(**kwargs)
    main.collection = mock_collection

    result, source = asyncio.run(_query_rag_with_tags("sync products", ["Sync"]))
    assert source == "similarity_fallback"
    assert "fallback doc" in result


def test_query_rag_no_collection():
    from main import _query_rag_with_tags
    import main

    original = main.collection
    main.collection = None
    try:
        result, source = asyncio.run(_query_rag_with_tags("sync products", ["Sync"]))
        assert result == ""
        assert source == "none"
    finally:
        main.collection = original


def test_query_rag_no_tags_uses_similarity():
    from main import _query_rag_with_tags
    import main

    mock_collection = MagicMock()
    mock_collection.query.return_value = {"documents": [["similarity doc"]]}
    main.collection = mock_collection

    result, source = asyncio.run(_query_rag_with_tags("sync products", []))
    # No tags → skip tag-filtered step → go straight to similarity
    assert source == "similarity_fallback"
