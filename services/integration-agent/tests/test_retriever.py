"""
Unit tests for services.retriever.HybridRetriever (R8, R9, R12, ADR-027/028).

Covers:
  - build_bm25_index: empty corpus, corpus with chunks
  - _expand_queries: 2 template variants always present; LLM variants added on success
  - _expand_queries: fallback to templates when LLM fails
  - _build_chroma_where_filter: single tag, multi-tag $or, no tags
  - _query_chroma: dedup by doc_id (highest score wins)
  - _query_bm25: returns scored chunks; empty when no index
  - _apply_threshold: filters chunks below threshold
  - _tfidf_rerank: orders by cosine similarity; returns unchanged on error
  - retrieve: integration test with mocked collection
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_chroma_result(docs, distances, doc_ids=None):
    metas = [{"doc_id": did} for did in (doc_ids or [f"id{i}" for i in range(len(docs))])]
    return {"documents": [docs], "distances": [distances], "metadatas": [metas]}


# ── build_bm25_index ──────────────────────────────────────────────────────────

def test_build_bm25_index_empty_corpus():
    from services.retriever import HybridRetriever
    r = HybridRetriever()
    r.build_bm25_index({})  # empty kb_chunks
    assert r._bm25 is None


def test_build_bm25_index_with_chunks():
    from services.retriever import HybridRetriever
    r = HybridRetriever()
    kb_chunks = {"doc1": ["Integration patterns for REST", "Error handling best practices"]}
    r.build_bm25_index(kb_chunks)
    assert r._bm25 is not None
    assert len(r._bm25_docs) == 2


# ── _build_chroma_where_filter ────────────────────────────────────────────────

def test_where_filter_no_tags():
    from services.retriever import HybridRetriever
    r = HybridRetriever()
    assert r._build_chroma_where_filter([]) is None


def test_where_filter_single_tag():
    from services.retriever import HybridRetriever
    r = HybridRetriever()
    result = r._build_chroma_where_filter(["Sync"])
    assert result == {"tags_csv": {"$contains": "Sync"}}


def test_where_filter_multi_tag_uses_or():
    from services.retriever import HybridRetriever
    r = HybridRetriever()
    result = r._build_chroma_where_filter(["Sync", "Export"])
    assert result == {"$or": [
        {"tags_csv": {"$contains": "Sync"}},
        {"tags_csv": {"$contains": "Export"}},
    ]}


# ── _expand_queries ───────────────────────────────────────────────────────────

def test_expand_queries_always_has_two_templates(monkeypatch):
    from services.retriever import HybridRetriever
    r = HybridRetriever()
    monkeypatch.setattr(
        "services.retriever.generate_with_ollama",
        AsyncMock(side_effect=Exception("LLM unavailable")),
    )
    result = asyncio.run(r._expand_queries(
        "sync products", ["Sync"], "ERP", "PLM", "Data Sync"
    ))
    assert len(result) == 2   # template 1 + template 2
    assert "sync products" in result
    assert "ERP to PLM Data Sync integration pattern" in result


def test_expand_queries_adds_llm_variants_on_success(monkeypatch):
    from services.retriever import HybridRetriever
    r = HybridRetriever()
    monkeypatch.setattr(
        "services.retriever.generate_with_ollama",
        AsyncMock(return_value='["technical variant", "business variant"]'),
    )
    result = asyncio.run(r._expand_queries(
        "sync products", ["Sync"], "ERP", "PLM", "Data Sync"
    ))
    assert len(result) == 4
    assert "technical variant" in result
    assert "business variant" in result


def test_expand_queries_fallback_on_llm_failure(monkeypatch):
    from services.retriever import HybridRetriever
    r = HybridRetriever()
    monkeypatch.setattr(
        "services.retriever.generate_with_ollama",
        AsyncMock(side_effect=Exception("timeout")),
    )
    result = asyncio.run(r._expand_queries("q", [], "S", "T", "C"))
    assert len(result) == 2  # templates only — no crash


# ── _query_chroma ─────────────────────────────────────────────────────────────

def test_query_chroma_deduplicates_by_doc_id():
    from services.retriever import HybridRetriever
    r = HybridRetriever()
    mock_col = MagicMock()
    # Both queries return the same doc_id with different scores
    mock_col.query.side_effect = [
        _make_chroma_result(["chunk A"], [0.2], ["doc1"]),  # score 1/(1+0.2) ≈ 0.833
        _make_chroma_result(["chunk A"], [0.5], ["doc1"]),  # score 1/(1+0.5) ≈ 0.667
    ]
    result = r._query_chroma(["query1", "query2"], mock_col, [])
    assert len(result) == 1
    assert abs(result[0].score - (1.0 / 1.2)) < 0.01  # highest score kept


def test_query_chroma_no_collection_returns_empty():
    from services.retriever import HybridRetriever
    r = HybridRetriever()
    result = r._query_chroma(["query"], None, [])
    assert result == []


# ── _query_bm25 ───────────────────────────────────────────────────────────────

def test_query_bm25_no_index_returns_empty():
    from services.retriever import HybridRetriever
    r = HybridRetriever()  # no index built
    result = r._query_bm25(["integration patterns"])
    assert result == []


def test_query_bm25_returns_scored_chunks():
    from services.retriever import HybridRetriever
    r = HybridRetriever()
    r.build_bm25_index({"doc1": ["REST integration patterns here", "Error handling guide"]})
    result = r._query_bm25(["REST integration"])
    assert len(result) > 0
    assert result[0].score > 0
    assert result[0].source_label == "kb_file"


# ── _apply_threshold ──────────────────────────────────────────────────────────

def test_apply_threshold_filters_low_score():
    from services.retriever import HybridRetriever, ScoredChunk
    r = HybridRetriever()
    chunks = [
        ScoredChunk(text="relevant", score=0.85, source_label="approved", tags=[]),
        ScoredChunk(text="irrelevant", score=0.3, source_label="approved", tags=[]),
    ]
    # threshold distance=0.8 means keep score >= 1/(1+0.8) = 1/1.8 ≈ 0.556
    filtered = r._apply_threshold(chunks)
    texts = [c.text for c in filtered]
    assert "relevant" in texts
    assert "irrelevant" not in texts


# ── _tfidf_rerank ─────────────────────────────────────────────────────────────

def test_tfidf_rerank_orders_by_relevance():
    from services.retriever import HybridRetriever, ScoredChunk
    r = HybridRetriever()
    chunks = [
        ScoredChunk(text="completely unrelated document about cooking", score=0.9,
                    source_label="approved", tags=[]),
        ScoredChunk(text="REST API integration pattern for SAP ERP", score=0.5,
                    source_label="approved", tags=[]),
    ]
    reranked = r._tfidf_rerank(chunks, "SAP ERP REST API integration")
    # The SAP chunk should rank higher despite lower initial score
    assert reranked[0].text == "REST API integration pattern for SAP ERP"


def test_tfidf_rerank_single_chunk_unchanged():
    from services.retriever import HybridRetriever, ScoredChunk
    r = HybridRetriever()
    chunks = [ScoredChunk(text="single chunk", score=0.7, source_label="approved", tags=[])]
    result = r._tfidf_rerank(chunks, "query")
    assert len(result) == 1
    assert result[0].text == "single chunk"


# ── retrieve (integration) ────────────────────────────────────────────────────

def test_retrieve_returns_top_k(monkeypatch):
    from services.retriever import HybridRetriever
    r = HybridRetriever()

    # Mock LLM expansion to return templates only (fast)
    monkeypatch.setattr(
        "services.retriever.generate_with_ollama",
        AsyncMock(side_effect=Exception("skip LLM")),
    )

    mock_col = MagicMock()
    mock_col.query.return_value = _make_chroma_result(
        ["chunk 1", "chunk 2", "chunk 3"],
        [0.1, 0.3, 0.5],
        ["d1", "d2", "d3"],
    )

    result = asyncio.run(r.retrieve(
        "sync ERP products", ["Sync"], mock_col,
        source="ERP", target="PLM", category="Data Sync",
    ))
    assert len(result) <= 5  # top-K default
    assert all(hasattr(c, "score") for c in result)
