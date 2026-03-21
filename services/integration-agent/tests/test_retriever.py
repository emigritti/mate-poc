"""
Unit tests for services.retriever.HybridRetriever (R8, R9, R12, ADR-027/028).

Covers:
  - build_bm25_index: empty corpus, corpus with chunks
  - _expand_queries: 2 template variants always present; LLM variants added on success
  - _expand_queries: fallback to templates when LLM fails
  - _tags_match_meta: Python post-filter helper for TAGS_CSV_FIELD substring matching (R12)
  - _query_chroma: dedup by doc_id (highest score wins); prefers tag-matched chunks
  - _query_bm25: returns scored chunks; empty when no index
  - _apply_threshold: filters chunks below threshold
  - _tfidf_rerank: orders by cosine similarity; returns unchanged on error
  - retrieve: integration test with mocked collection
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_chroma_result(docs, distances, doc_ids=None, tags_csv=None):
    """Build a fake ChromaDB query result.

    tags_csv: optional list of tags_csv strings per document (e.g. ["Sync,Export", None]).
    Uses zip-based iteration so mismatched lengths never cause IndexError.
    """
    ids = doc_ids or [f"id{i}" for i in range(len(docs))]
    tc  = tags_csv or [None] * len(docs)
    metas = [
        {**{"doc_id": did}, **({"tags_csv": tag} if tag else {})}
        for did, tag in zip(ids, tc)
    ]
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


# ── _tags_match_meta ──────────────────────────────────────────────────────────

def test_tags_match_meta_single_tag_present():
    from services.retriever import HybridRetriever
    assert HybridRetriever._tags_match_meta({"tags_csv": "Sync,Export"}, ["Sync"]) is True


def test_tags_match_meta_single_tag_absent():
    from services.retriever import HybridRetriever
    assert HybridRetriever._tags_match_meta({"tags_csv": "Export,PLM"}, ["Sync"]) is False


def test_tags_match_meta_multi_tag_any_match():
    from services.retriever import HybridRetriever
    # "Sync" not in csv, "PLM" is — should return True (any match)
    assert HybridRetriever._tags_match_meta({"tags_csv": "PLM,Export"}, ["Sync", "PLM"]) is True


def test_tags_match_meta_no_tags_always_true():
    from services.retriever import HybridRetriever
    assert HybridRetriever._tags_match_meta({"tags_csv": "Sync"}, []) is True


def test_tags_match_meta_none_meta():
    from services.retriever import HybridRetriever
    assert HybridRetriever._tags_match_meta(None, ["Sync"]) is False


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


def test_query_chroma_prefers_tag_matched_chunks():
    """Python post-filter returns only tag-matched chunks when available."""
    from services.retriever import HybridRetriever
    r = HybridRetriever()
    mock_col = MagicMock()
    # Two docs: one matches "Sync", one does not
    mock_col.query.return_value = _make_chroma_result(
        ["chunk tagged", "chunk untagged"],
        [0.1, 0.1],
        ["doc_tagged", "doc_untagged"],
        tags_csv=["Sync,Export", "PLM"],
    )
    result = r._query_chroma(["query"], mock_col, ["Sync"])
    assert len(result) == 1
    assert result[0].text == "chunk tagged"


def test_query_chroma_falls_back_to_all_when_no_tag_match():
    """Falls back to all results when no chunk matches the requested tags."""
    from services.retriever import HybridRetriever
    r = HybridRetriever()
    mock_col = MagicMock()
    mock_col.query.return_value = _make_chroma_result(
        ["chunk A", "chunk B"],
        [0.2, 0.3],
        ["doc1", "doc2"],
        tags_csv=["PLM", "Export"],
    )
    result = r._query_chroma(["query"], mock_col, ["Sync"])  # "Sync" not in any doc
    assert len(result) == 2  # fallback: all results returned


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
