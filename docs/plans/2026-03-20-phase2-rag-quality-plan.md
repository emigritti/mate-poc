# Phase 2 — RAG Quality Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the RAG pipeline from naive single-query ChromaDB lookups to a production-grade Hybrid RAG pipeline with multi-query expansion, BM25 ensemble, TF-IDF re-ranking, semantic chunking, and unified context assembly.

**Architecture:** New `services/retriever.py` (`HybridRetriever`) handles retrieval (R8, R9, R12, BM25); `rag_service.py` gains `ContextAssembler` (R10); `document_parser.py` gains `semantic_chunk()` (R11). All changes are additive — existing functions preserved for backward compatibility.

**Tech Stack:** Python 3.13, FastAPI, ChromaDB, LangChain (`langchain-text-splitters`), `rank-bm25`, `scikit-learn`, pytest

**Design doc:** `docs/plans/2026-03-20-phase2-rag-quality-design.md`

**ADRs to create:** ADR-027, ADR-028, ADR-029, ADR-030

**Run tests from:** `services/integration-agent/`
```bash
cd services/integration-agent && python -m pytest tests/ -v
```

---

## Task 1: Add Dependencies and Config Params

**Files:**
- Modify: `services/integration-agent/requirements.txt`
- Modify: `services/integration-agent/config.py`

### Step 1: Add Python packages to requirements.txt

Append to `services/integration-agent/requirements.txt`:
```
langchain-text-splitters==0.3.8
rank-bm25==0.2.2
scikit-learn==1.6.1
anyio==4.9.0
```

> `langchain-text-splitters` is a lightweight sub-package of LangChain — no LLM dependencies.
> `anyio` is a transitive dep needed for async tests (already in the env via pytest-asyncio, pinning explicitly).

### Step 2: Add RAG Phase 2 config params to `config.py`

In the `# ── Knowledge Base ─────` section, after `kb_url_max_chars_per_source`, add:

```python
    # ── RAG Phase 2 (R8, R9) ─────────────────────────────────────────────────
    # Max ChromaDB distance to keep a chunk (0 = perfect, 2 = worst).
    # Chunks with distance >= threshold are discarded before re-ranking.
    rag_distance_threshold: float = 0.8    # override: RAG_DISTANCE_THRESHOLD

    # BM25 weight in ensemble (ChromaDB weight = 1 - this).
    rag_bm25_weight: float = 0.4           # override: RAG_BM25_WEIGHT

    # ChromaDB n_results per query variant (4 variants × n_results = candidates).
    rag_n_results_per_query: int = 3       # override: RAG_N_RESULTS_PER_QUERY

    # Final top-K chunks passed to ContextAssembler after re-ranking.
    rag_top_k_chunks: int = 5              # override: RAG_TOP_K_CHUNKS
```

### Step 3: Install dependencies

```bash
cd services/integration-agent
pip install langchain-text-splitters==0.3.8 rank-bm25==0.2.2 "scikit-learn==1.6.1"
```

Expected: packages install without errors.

### Step 4: Verify config loads

```bash
cd services/integration-agent
python -c "from config import settings; print(settings.rag_top_k_chunks)"
```

Expected output: `5`

### Step 5: Run existing tests — must stay green

```bash
python -m pytest tests/ -v --tb=short -q
```

Expected: `216 passed`

### Step 6: Commit

```bash
git add services/integration-agent/requirements.txt services/integration-agent/config.py
git commit -m "feat(phase2): add LangChain/BM25/sklearn deps and RAG Phase 2 config params"
```

---

## Task 2: Add `kb_chunks` to Shared State

**Files:**
- Modify: `services/integration-agent/state.py`

BM25 needs the raw chunk texts from KB documents. We store them in-memory keyed by `doc_id`
so the `HybridRetriever` can build its index. At startup, chunks are loaded from ChromaDB.
At runtime, updated on KB upload/delete.

### Step 1: Add `kb_chunks` dict to `state.py`

After the `kb_docs` line, add:

```python
# ── BM25 chunk corpus (in-memory, populated from ChromaDB at startup) ─────────
# key: doc_id (matches kb_docs key), value: list of chunk texts
kb_chunks: dict[str, list[str]] = {}
```

### Step 2: Run tests — must stay green

```bash
python -m pytest tests/ -v -q
```

Expected: `216 passed`

### Step 3: Commit

```bash
git add services/integration-agent/state.py
git commit -m "feat(phase2): add kb_chunks in-memory corpus to state for BM25 index"
```

---

## Task 3: R11 — Semantic Chunking with LangChain

**Files:**
- Modify: `services/integration-agent/document_parser.py`
- Create: `services/integration-agent/tests/test_semantic_chunk.py`

### Step 1: Write failing tests first

Create `services/integration-agent/tests/test_semantic_chunk.py`:

```python
"""
Unit tests for semantic_chunk() — LangChain RecursiveCharacterTextSplitter (R11).

Covers:
  - Heading boundaries respected (## splits before character limit)
  - Paragraph boundaries respected (\n\n)
  - Empty text returns empty list
  - Overlap works
  - Backward compat: chunk_text() still works unchanged
"""
import pytest


def test_semantic_chunk_empty_text_returns_empty():
    from document_parser import semantic_chunk
    assert semantic_chunk("") == []


def test_semantic_chunk_short_text_single_chunk():
    from document_parser import semantic_chunk
    result = semantic_chunk("Short text.", chunk_size=1000, chunk_overlap=100)
    assert len(result) == 1
    assert result[0].text == "Short text."
    assert result[0].index == 0


def test_semantic_chunk_respects_heading_boundary():
    """Heading ## should be a split point before char limit is hit."""
    from document_parser import semantic_chunk
    text = ("## Section One\n" + "A" * 300 + "\n\n## Section Two\n" + "B" * 300)
    result = semantic_chunk(text, chunk_size=400, chunk_overlap=0)
    # Section One and Section Two must end up in separate chunks
    combined = " ".join(c.text for c in result)
    assert "Section One" in combined
    assert "Section Two" in combined
    assert len(result) >= 2


def test_semantic_chunk_respects_paragraph_boundary():
    """Double newline (paragraph break) preferred over mid-sentence split."""
    from document_parser import semantic_chunk
    text = ("First paragraph content here.\n\n"
            "Second paragraph content here.\n\n"
            "Third paragraph content here.")
    result = semantic_chunk(text, chunk_size=50, chunk_overlap=0)
    # Each paragraph is ~35 chars — should land in separate chunks
    assert len(result) >= 2


def test_semantic_chunk_indices_are_sequential():
    from document_parser import semantic_chunk
    text = "Line one.\n\nLine two.\n\nLine three.\n\nLine four."
    result = semantic_chunk(text, chunk_size=20, chunk_overlap=0)
    indices = [c.index for c in result]
    assert indices == list(range(len(result)))


def test_semantic_chunk_returns_text_chunks():
    from document_parser import semantic_chunk, TextChunk
    result = semantic_chunk("Some content.", chunk_size=1000, chunk_overlap=100)
    assert all(isinstance(c, TextChunk) for c in result)


def test_chunk_text_still_works_unchanged():
    """Backward compat: original chunk_text() must work unchanged after R11."""
    from document_parser import chunk_text
    result = chunk_text("Hello world. " * 100, chunk_size=100, chunk_overlap=20)
    assert len(result) > 1
    assert all(c.text for c in result)
```

### Step 2: Run tests — verify they fail

```bash
python -m pytest tests/test_semantic_chunk.py -v
```

Expected: `ERRORS` — `ImportError: cannot import name 'semantic_chunk' from 'document_parser'`

### Step 3: Implement `semantic_chunk()` in `document_parser.py`

Add after the `chunk_text()` function (at the end of the file):

```python
def semantic_chunk(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[TextChunk]:
    """Split text into overlapping chunks respecting semantic boundaries (R11).

    Uses LangChain RecursiveCharacterTextSplitter with separator priority:
      H2 heading → H3 heading → paragraph → newline → sentence → word

    This replaces fixed-size splitting in chunk_text() for new KB uploads.
    chunk_text() is preserved for backward compatibility.

    ADR-030: Semantic chunking with LangChain RecursiveCharacterTextSplitter.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    if not text.strip():
        return []

    clean = re.sub(r"\n{3,}", "\n\n", text.strip())

    splitter = RecursiveCharacterTextSplitter(
        separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " "],
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )

    lc_chunks = splitter.create_documents([clean])

    result: list[TextChunk] = []
    for i, doc in enumerate(lc_chunks):
        stripped = doc.page_content.strip()
        if stripped:
            result.append(TextChunk(
                text=stripped,
                index=len(result),
                metadata={"char_start": 0, "char_end": len(stripped)},
            ))

    logger.info(
        "[KB] Semantic chunked into %d chunks (size=%d, overlap=%d).",
        len(result), chunk_size, chunk_overlap,
    )
    return result
```

### Step 4: Run tests — must pass

```bash
python -m pytest tests/test_semantic_chunk.py -v
```

Expected: `7 passed`

### Step 5: Run full suite — no regressions

```bash
python -m pytest tests/ -v -q
```

Expected: `223 passed`

### Step 6: Commit

```bash
git add services/integration-agent/document_parser.py \
        services/integration-agent/tests/test_semantic_chunk.py
git commit -m "feat(phase2/R11): add semantic_chunk() with LangChain RecursiveCharacterTextSplitter"
```

---

## Task 4: R8 + R9 + R12 — HybridRetriever

**Files:**
- Create: `services/integration-agent/services/retriever.py`
- Create: `services/integration-agent/tests/test_retriever.py`

### Step 1: Write failing tests first

Create `services/integration-agent/tests/test_retriever.py`:

```python
"""
Unit tests for services.retriever.HybridRetriever (R8, R9, R12, ADR-027/028).

Covers:
  - build_bm25_index: empty corpus, corpus with chunks
  - _expand_queries: 2 template variants always present; LLM variants added on success
  - _expand_queries: fallback to templates when LLM fails
  - _build_chroma_where_filter: single tag, multi-tag $or, no tags
  - _query_chroma: dedup by doc_id (highest score wins)
  - _query_bm25: returns scored chunks; empty when no index
  - _ensemble_merge: weighted combination; BM25 score adds to existing Chroma score
  - _apply_threshold: filters chunks below threshold
  - _tfidf_rerank: orders by cosine similarity; returns unchanged on error
  - retrieve: integration test with mocked collection
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_kb_doc(doc_id: str, chunks: list[str]):
    doc = MagicMock()
    doc.id = doc_id
    doc.source_type = "file"
    doc.chunks_text = chunks   # we'll use a dict approach in the retriever
    return doc


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
        _make_chroma_result(["chunk A"], [0.2], ["doc1"]),  # score 0.8
        _make_chroma_result(["chunk A"], [0.5], ["doc1"]),  # score 0.5
    ]
    result = r._query_chroma(["query1", "query2"], mock_col, [])
    assert len(result) == 1
    assert abs(result[0].score - 0.8) < 0.01  # highest score kept


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
        ScoredChunk(text="irrelevant", score=0.05, source_label="approved", tags=[]),
    ]
    # threshold distance=0.8 means keep score >= 0.2 (1 - 0.8)
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
```

### Step 2: Run tests — verify they fail

```bash
python -m pytest tests/test_retriever.py -v
```

Expected: `ERRORS` — `ModuleNotFoundError: No module named 'services.retriever'`

### Step 3: Create `services/retriever.py`

Create `services/integration-agent/services/retriever.py`:

```python
"""
Hybrid Retriever — BM25 + ChromaDB dense retrieval with multi-query expansion.

Phase 2 — R8 (multi-query expansion), R9 (threshold + TF-IDF re-rank + BM25),
           R12 (multi-dimensional $or tag filter).

ADR-027: BM25 Hybrid Retrieval (rank_bm25 + ensemble scoring).
ADR-028: Multi-Query Expansion 2+2 (2 template + 2 LLM variants).
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Callable

from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config import settings
from services.llm_service import generate_with_ollama, llm_overrides

logger = logging.getLogger(__name__)


@dataclass
class ScoredChunk:
    """A retrieved text chunk with its relevance score and source metadata."""
    text: str
    score: float
    source_label: str   # "approved" | "kb_file" | "kb_url"
    tags: list[str] = field(default_factory=list)


class HybridRetriever:
    """
    Combines ChromaDB dense retrieval with BM25 sparse retrieval.

    Pipeline (per call to retrieve()):
      1. Query expansion: 2 template + 2 LLM variants (R8 / ADR-028)
      2. ChromaDB query: parallel, $or tag filter, include distances (R12)
      3. BM25 query: in-memory index of KB file chunks (ADR-027)
      4. Ensemble merge: weighted score combination (0.6 dense / 0.4 sparse)
      5. Distance threshold filter (R9)
      6. TF-IDF cosine re-rank (R9)
      7. Top-K selection
    """

    def __init__(self) -> None:
        self._bm25: BM25Okapi | None = None
        self._bm25_docs: list[str] = []
        self._bm25_ids: list[str] = []

    # ── BM25 Index ────────────────────────────────────────────────────────────

    def build_bm25_index(self, kb_chunks: dict[str, list[str]]) -> None:
        """Build BM25 in-memory index from KB chunk corpus.

        Args:
            kb_chunks: dict mapping doc_id → list of chunk texts.
                       Populated from state.kb_chunks (loaded from ChromaDB at startup).

        Called at startup by main.py lifespan and after every KB upload/delete.
        """
        all_texts: list[str] = []
        all_ids: list[str] = []

        for doc_id, chunks in kb_chunks.items():
            for chunk in chunks:
                all_texts.append(chunk)
                all_ids.append(doc_id)

        if not all_texts:
            self._bm25 = None
            self._bm25_docs = []
            self._bm25_ids = []
            logger.info("[BM25] No KB chunks — index cleared.")
            return

        tokenized = [t.lower().split() for t in all_texts]
        self._bm25 = BM25Okapi(tokenized)
        self._bm25_docs = all_texts
        self._bm25_ids = all_ids
        logger.info("[BM25] Index built: %d chunks across %d documents.", len(all_texts), len(kb_chunks))

    # ── Query Expansion (R8 / ADR-028) ───────────────────────────────────────

    async def _expand_queries(
        self,
        query_text: str,
        tags: list[str],
        source: str,
        target: str,
        category: str,
        *,
        log_fn: Callable[[str], None] | None = None,
    ) -> list[str]:
        """Generate 2 template + up to 2 LLM query variants.

        Template variants are always generated (deterministic, zero latency).
        LLM variants are attempted using tag_llm settings (lightweight call).
        If LLM call fails for any reason, only template variants are used.
        """
        _log = log_fn or (lambda msg: logger.info(msg))

        variants: list[str] = [
            query_text,
            f"{source} to {target} {category} integration pattern",
        ]

        prompt = (
            f'Given this integration query: "{query_text[:500]}"\n'
            "Generate 2 alternative phrasings:\n"
            "1. A technical systems integration perspective\n"
            "2. A business process perspective\n"
            'Reply with a JSON array only: ["technical variant", "business variant"]'
        )
        try:
            raw = await generate_with_ollama(
                prompt,
                num_predict=llm_overrides.get("tag_num_predict", settings.tag_num_predict),
                timeout=llm_overrides.get("tag_timeout_seconds", settings.tag_timeout_seconds),
                temperature=0.3,
                log_fn=log_fn,
            )
            match = re.search(r"\[.*?\]", raw, re.DOTALL)
            if match:
                llm_variants = json.loads(match.group())
                if isinstance(llm_variants, list):
                    valid = [str(v).strip() for v in llm_variants[:2] if str(v).strip()]
                    variants.extend(valid)
                    _log(f"[RAG] Query expansion: {len(variants)} variants (2 template + {len(valid)} LLM)")
        except Exception as exc:
            _log(f"[RAG] Query expansion LLM unavailable — using 2 template variants: {exc}")

        return variants

    # ── Tag Filter (R12) ──────────────────────────────────────────────────────

    def _build_chroma_where_filter(self, tags: list[str]) -> dict | None:
        """Build ChromaDB $or tag filter for multi-dimensional matching (R12).

        Before (single tag): {"tags_csv": {"$contains": tags[0]}}
        After  (all tags):   {"$or": [{"tags_csv": {"$contains": t}} for t in tags]}
        """
        if not tags:
            return None
        if len(tags) == 1:
            return {"tags_csv": {"$contains": tags[0]}}
        return {"$or": [{"tags_csv": {"$contains": t}} for t in tags]}

    # ── ChromaDB Query ────────────────────────────────────────────────────────

    def _query_chroma(
        self,
        queries: list[str],
        collection,
        tags: list[str],
    ) -> list[ScoredChunk]:
        """Query ChromaDB with all query variants; deduplicate by doc_id."""
        if not collection:
            return []

        where = self._build_chroma_where_filter(tags)
        seen: dict[str, ScoredChunk] = {}
        n = settings.rag_n_results_per_query

        for query in queries:
            try:
                kwargs: dict = {
                    "query_texts": [query],
                    "n_results": n,
                    "include": ["documents", "distances", "metadatas"],
                }
                if where:
                    kwargs["where"] = where

                results = collection.query(**kwargs)
                docs  = (results.get("documents") or [[]])[0]
                dists = (results.get("distances")  or [[]])[0]
                metas = (results.get("metadatas")  or [[]])[0]

                for doc, dist, meta in zip(docs, dists, metas):
                    score  = max(0.0, 1.0 - dist)   # distance → similarity score
                    doc_id = (meta or {}).get("doc_id", doc[:50])
                    if doc_id not in seen or seen[doc_id].score < score:
                        seen[doc_id] = ScoredChunk(
                            text=doc,
                            score=score,
                            source_label="approved",
                            tags=tags,
                        )
            except Exception as exc:
                logger.warning("[RAG] ChromaDB query failed for variant: %s", exc)

        return list(seen.values())

    # ── BM25 Query ────────────────────────────────────────────────────────────

    def _query_bm25(self, queries: list[str]) -> list[ScoredChunk]:
        """Query BM25 index with all query variants; return deduplicated chunks."""
        if not self._bm25 or not self._bm25_docs:
            return []

        seen: dict[int, ScoredChunk] = {}

        for query in queries:
            tokens = query.lower().split()
            scores = self._bm25.get_scores(tokens)
            for idx, score in enumerate(scores):
                if score <= 0.0:
                    continue
                if idx not in seen or seen[idx].score < score:
                    seen[idx] = ScoredChunk(
                        text=self._bm25_docs[idx],
                        score=float(score),
                        source_label="kb_file",
                        tags=[],
                    )

        return list(seen.values())

    # ── Ensemble Merge (ADR-027) ──────────────────────────────────────────────

    def _ensemble_merge(
        self,
        chroma_chunks: list[ScoredChunk],
        bm25_chunks: list[ScoredChunk],
    ) -> list[ScoredChunk]:
        """Weighted merge of ChromaDB (dense) and BM25 (sparse) results.

        Weights: Chroma = (1 - rag_bm25_weight), BM25 = rag_bm25_weight.
        Scores are normalised within each set before weighting.
        Chunks appearing in both sets have their scores summed.
        """
        chroma_w = 1.0 - settings.rag_bm25_weight
        bm25_w   = settings.rag_bm25_weight

        def _normalize(chunks: list[ScoredChunk], weight: float) -> list[ScoredChunk]:
            if not chunks:
                return []
            max_s = max(c.score for c in chunks) or 1.0
            return [
                ScoredChunk(
                    text=c.text,
                    score=(c.score / max_s) * weight,
                    source_label=c.source_label,
                    tags=c.tags,
                )
                for c in chunks
            ]

        merged: dict[str, ScoredChunk] = {}

        for chunk in _normalize(chroma_chunks, chroma_w):
            key = chunk.text[:100]
            if key not in merged or merged[key].score < chunk.score:
                merged[key] = chunk

        for chunk in _normalize(bm25_chunks, bm25_w):
            key = chunk.text[:100]
            if key not in merged:
                merged[key] = chunk
            else:
                existing = merged[key]
                merged[key] = ScoredChunk(
                    text=existing.text,
                    score=existing.score + chunk.score,
                    source_label=existing.source_label,
                    tags=existing.tags,
                )

        return list(merged.values())

    # ── Threshold Filter (R9) ─────────────────────────────────────────────────

    def _apply_threshold(self, chunks: list[ScoredChunk]) -> list[ScoredChunk]:
        """Discard chunks below the relevance threshold.

        settings.rag_distance_threshold is a ChromaDB distance (0 = perfect, 2 = worst).
        After ensemble normalisation, scores are in [0, 1].
        We keep chunks where score >= (1 - threshold).
        """
        min_score = 1.0 - settings.rag_distance_threshold
        filtered = [c for c in chunks if c.score >= min_score]
        if len(filtered) < len(chunks):
            logger.info("[RAG] Threshold (%.2f): %d → %d chunks.", min_score, len(chunks), len(filtered))
        return filtered

    # ── TF-IDF Re-rank (R9) ──────────────────────────────────────────────────

    def _tfidf_rerank(
        self,
        chunks: list[ScoredChunk],
        query: str,
    ) -> list[ScoredChunk]:
        """Re-rank chunks by TF-IDF cosine similarity to the original query.

        Final score = 0.5 × ensemble_score + 0.5 × tfidf_cosine_similarity.
        Falls back to score-only ordering if TF-IDF fails.
        """
        if len(chunks) <= 1:
            return chunks

        try:
            texts = [query] + [c.text for c in chunks]
            vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
            matrix = vectorizer.fit_transform(texts)
            sims = cosine_similarity(matrix[0], matrix[1:])[0]

            reranked = [
                ScoredChunk(
                    text=c.text,
                    score=(c.score * 0.5) + (float(sim) * 0.5),
                    source_label=c.source_label,
                    tags=c.tags,
                )
                for c, sim in zip(chunks, sims)
            ]
            return sorted(reranked, key=lambda c: c.score, reverse=True)

        except Exception as exc:
            logger.warning("[RAG] TF-IDF re-rank failed, using score order: %s", exc)
            return sorted(chunks, key=lambda c: c.score, reverse=True)

    # ── Public API ────────────────────────────────────────────────────────────

    async def retrieve(
        self,
        query_text: str,
        tags: list[str],
        collection,
        source: str = "",
        target: str = "",
        category: str = "",
        *,
        log_fn: Callable[[str], None] | None = None,
    ) -> list[ScoredChunk]:
        """Full retrieval pipeline for a single integration.

        Returns top-K ScoredChunks ordered by final relevance score.
        """
        _log = log_fn or (lambda msg: logger.info(msg))

        queries = await self._expand_queries(
            query_text, tags, source, target, category, log_fn=log_fn
        )

        chroma_chunks = self._query_chroma(queries, collection, tags)
        bm25_chunks   = self._query_bm25(queries)
        _log(f"[RAG] Retrieved: {len(chroma_chunks)} Chroma + {len(bm25_chunks)} BM25 chunks")

        merged   = self._ensemble_merge(chroma_chunks, bm25_chunks)
        filtered = self._apply_threshold(merged)
        reranked = self._tfidf_rerank(filtered, query_text)
        top_k    = reranked[:settings.rag_top_k_chunks]

        _log(f"[RAG] Final: {len(top_k)} chunks after ensemble+threshold+rerank")
        return top_k


# ── Module-level singleton ────────────────────────────────────────────────────
# Initialized at startup in main.py lifespan. Routers import this instance.
hybrid_retriever = HybridRetriever()
```

### Step 4: Run tests — must pass

```bash
python -m pytest tests/test_retriever.py -v
```

Expected: `17 passed`

### Step 5: Run full suite — no regressions

```bash
python -m pytest tests/ -v -q
```

Expected: `240 passed`

### Step 6: Commit

```bash
git add services/integration-agent/services/retriever.py \
        services/integration-agent/tests/test_retriever.py
git commit -m "feat(phase2/R8+R9+R12): add HybridRetriever with BM25, multi-query, TF-IDF re-rank"
```

---

## Task 5: R10 — ContextAssembler

**Files:**
- Modify: `services/integration-agent/services/rag_service.py`
- Create: `services/integration-agent/tests/test_context_assembler.py`

### Step 1: Write failing tests first

Create `services/integration-agent/tests/test_context_assembler.py`:

```python
"""
Unit tests for ContextAssembler (R10 / ADR-029).

Covers:
  - Chunks from all sources are included (approved, kb_file, kb_url)
  - Output respects max_chars budget
  - Higher-scored chunks appear first
  - Source sections formatted with correct headers
  - Empty inputs return empty string
  - Backward compat: build_rag_context() unchanged
"""


def _make_chunk(text: str, score: float, source: str, tags=None):
    from services.retriever import ScoredChunk
    return ScoredChunk(text=text, score=score, source_label=source, tags=tags or [])


def test_context_assembler_empty_inputs_returns_empty():
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    result = ca.assemble([], [], [], max_chars=5000)
    assert result == ""


def test_context_assembler_approved_section_present():
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    chunks = [_make_chunk("approved doc content", 0.9, "approved")]
    result = ca.assemble(chunks, [], [], max_chars=5000)
    assert "PAST APPROVED EXAMPLES" in result
    assert "approved doc content" in result


def test_context_assembler_kb_section_present():
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    chunks = [_make_chunk("best practice chunk", 0.8, "kb_file")]
    result = ca.assemble([], chunks, [], max_chars=5000)
    assert "BEST PRACTICE PATTERNS" in result
    assert "best practice chunk" in result


def test_context_assembler_url_section_present():
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    chunks = [_make_chunk("url content fetched", 0.7, "kb_url")]
    result = ca.assemble([], [], chunks, max_chars=5000)
    assert "url content fetched" in result


def test_context_assembler_respects_max_chars_budget():
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    chunks = [_make_chunk("A" * 1000, 0.9, "approved")] * 10
    result = ca.assemble(chunks, [], [], max_chars=500)
    assert len(result) <= 600   # some header overhead allowed


def test_context_assembler_orders_by_score():
    from services.rag_service import ContextAssembler
    ca = ContextAssembler()
    low  = _make_chunk("low relevance content",  0.3, "approved")
    high = _make_chunk("high relevance content", 0.9, "approved")
    result = ca.assemble([low, high], [], [], max_chars=5000)
    # Higher score should appear first
    assert result.index("high relevance content") < result.index("low relevance content")


def test_build_rag_context_still_works():
    """Backward compat: build_rag_context() must remain unchanged."""
    from services.rag_service import build_rag_context
    result = build_rag_context(["doc A", "doc B"])
    assert "doc A" in result
    assert "doc B" in result
```

### Step 2: Run tests — verify they fail

```bash
python -m pytest tests/test_context_assembler.py -v
```

Expected: `ERRORS` — `ImportError: cannot import name 'ContextAssembler' from 'services.rag_service'`

### Step 3: Add `ContextAssembler` to `rag_service.py`

At the top of `services/rag_service.py`, add this import after the existing imports:
```python
from services.retriever import ScoredChunk
```

At the end of the file, append:

```python

class ContextAssembler:
    """Unified context fusion from multiple RAG sources (R10 / ADR-029).

    Collects ScoredChunks from approved integrations, KB files, and KB URLs,
    orders by relevance score, applies a char budget, and formats with source
    section headers so the LLM can distinguish pattern types.

    Output format:
        ## PAST APPROVED EXAMPLES (use as style reference):
        ### Source: approved · score: 0.92
        [chunk]

        ## BEST PRACTICE PATTERNS (follow these patterns in your output):
        ### Source: kb_file · score: 0.87
        [chunk]
    """

    def assemble(
        self,
        approved_chunks: list[ScoredChunk],
        kb_chunks: list[ScoredChunk],
        url_chunks: list[ScoredChunk],
        max_chars: int,
    ) -> str:
        """Assemble a structured context string for the LLM prompt.

        Args:
            approved_chunks: Chunks from approved_integrations ChromaDB collection.
            kb_chunks:       Chunks from knowledge_base ChromaDB collection.
            url_chunks:      Chunks from live-fetched URL KB entries.
            max_chars:       Hard character budget for the assembled context.

        Returns:
            Formatted context string, or empty string if no chunks provided.
        """
        if not approved_chunks and not kb_chunks and not url_chunks:
            return ""

        # Sort all chunks by score descending within each section
        approved_sorted = sorted(approved_chunks, key=lambda c: c.score, reverse=True)
        kb_sorted       = sorted(kb_chunks + url_chunks, key=lambda c: c.score, reverse=True)

        sections: list[str] = []
        chars_used = 0

        if approved_sorted:
            header = "## PAST APPROVED EXAMPLES (use as style reference):"
            section_parts = [header]
            for chunk in approved_sorted:
                entry = f"### Source: approved · score: {chunk.score:.2f}\n{chunk.text}"
                if chars_used + len(entry) > max_chars:
                    break
                section_parts.append(entry)
                chars_used += len(entry)
            if len(section_parts) > 1:
                sections.append("\n\n".join(section_parts))

        if kb_sorted and chars_used < max_chars:
            header = "## BEST PRACTICE PATTERNS (follow these patterns in your output):"
            section_parts = [header]
            for chunk in kb_sorted:
                label = "kb_url" if chunk.source_label == "kb_url" else "kb_file"
                entry = f"### Source: {label} · score: {chunk.score:.2f}\n{chunk.text}"
                if chars_used + len(entry) > max_chars:
                    break
                section_parts.append(entry)
                chars_used += len(entry)
            if len(section_parts) > 1:
                sections.append("\n\n".join(section_parts))

        return "\n\n".join(sections)
```

### Step 4: Run tests — must pass

```bash
python -m pytest tests/test_context_assembler.py -v
```

Expected: `7 passed`

### Step 5: Run full suite — no regressions

```bash
python -m pytest tests/ -v -q
```

Expected: `247 passed`

### Step 6: Commit

```bash
git add services/integration-agent/services/rag_service.py \
        services/integration-agent/tests/test_context_assembler.py
git commit -m "feat(phase2/R10): add ContextAssembler for unified RAG context fusion"
```

---

## Task 6: Wire Semantic Chunking into KB Upload

**Files:**
- Modify: `services/integration-agent/routers/kb.py`

KB upload must now use `semantic_chunk()` instead of `chunk_text()`, populate `state.kb_chunks`,
and trigger a BM25 index rebuild.

### Step 1: Update imports in `routers/kb.py`

Replace the existing `document_parser` import line:
```python
from document_parser import (
    DocumentParseError,
    chunk_text,
    detect_file_type,
    parse_document,
)
```
with:
```python
from document_parser import (
    DocumentParseError,
    semantic_chunk,
    detect_file_type,
    parse_document,
)
```

Add at the end of the imports block:
```python
import state
from services.retriever import hybrid_retriever
```

> Note: `state` and `hybrid_retriever` are used to update `kb_chunks` and rebuild the BM25 index.

### Step 2: Replace `chunk_text` call with `semantic_chunk` in `kb_upload`

Find the line in `kb_upload` that calls `chunk_text`:
```python
chunks = chunk_text(result.text, settings.kb_chunk_size, settings.kb_chunk_overlap)
```
Replace with:
```python
chunks = semantic_chunk(result.text, settings.kb_chunk_size, settings.kb_chunk_overlap)
```

### Step 3: Add BM25 corpus update after storing `kb_doc`

After `state.kb_docs[doc_id] = kb_doc` in `kb_upload`, add:
```python
    # Update BM25 corpus and rebuild index (Phase 2 / ADR-027)
    state.kb_chunks[doc_id] = [c.text for c in chunks]
    hybrid_retriever.build_bm25_index(state.kb_chunks)
```

### Step 4: Add BM25 corpus cleanup in `kb_delete`

Find the `kb_delete` endpoint. After `state.kb_docs.pop(doc_id, None)`, add:
```python
    # Remove from BM25 corpus and rebuild index
    state.kb_chunks.pop(doc_id, None)
    hybrid_retriever.build_bm25_index(state.kb_chunks)
```

### Step 5: Run full test suite — must stay green

```bash
python -m pytest tests/ -v -q
```

Expected: `247 passed` (KB upload tests use mock content that passes through `semantic_chunk`)

### Step 6: Commit

```bash
git add services/integration-agent/routers/kb.py
git commit -m "feat(phase2): wire semantic_chunk and BM25 rebuild into KB upload/delete"
```

---

## Task 7: Wire BM25 Index Build into Startup Lifespan

**Files:**
- Modify: `services/integration-agent/main.py`

At startup, after KB docs are seeded from MongoDB, load chunk texts from ChromaDB
and build the initial BM25 index.

### Step 1: Add import to `main.py`

After the existing service imports, add:
```python
from services.retriever import hybrid_retriever
```

### Step 2: Add ChromaDB chunk loading + BM25 build in lifespan

In the `lifespan` function, after the KB documents seeding block:
```python
    # Seed Knowledge Base docs from MongoDB
    if db.kb_documents_col is not None:
        async for doc in db.kb_documents_col.find({}, {"_id": 0}):
            state.kb_docs[doc["id"]] = KBDocument(**doc)
        logger.info("[DB] Seeded %d KB documents from MongoDB.", len(state.kb_docs))
```

Add immediately after:
```python
    # Load KB chunk texts from ChromaDB and build BM25 index (Phase 2 / ADR-027)
    if state.kb_collection is not None:
        try:
            result = state.kb_collection.get(include=["documents", "metadatas"])
            docs  = result.get("documents") or []
            metas = result.get("metadatas") or []
            for doc_text, meta in zip(docs, metas):
                doc_id = (meta or {}).get("doc_id", "unknown")
                state.kb_chunks.setdefault(doc_id, []).append(doc_text)
            hybrid_retriever.build_bm25_index(state.kb_chunks)
            logger.info("[BM25] Index built from %d KB chunks at startup.", len(docs))
        except Exception as exc:
            logger.warning("[BM25] Failed to build index at startup: %s", exc)
```

### Step 3: Run full test suite — must stay green

```bash
python -m pytest tests/ -v -q
```

Expected: `247 passed`

### Step 4: Commit

```bash
git add services/integration-agent/main.py
git commit -m "feat(phase2): build BM25 index from ChromaDB chunks at startup"
```

---

## Task 8: Wire HybridRetriever + ContextAssembler into Agentic Flow

**Files:**
- Modify: `services/integration-agent/routers/agent.py`

Replace the existing `query_rag_with_tags` / `query_kb_context` / `fetch_url_kb_context`
calls in `run_agentic_rag_flow()` with `HybridRetriever` + `ContextAssembler`.

### Step 1: Update imports in `routers/agent.py`

Replace:
```python
from services.rag_service import (
    fetch_url_kb_context,
    query_kb_context,
    query_rag_with_tags,
)
```
with:
```python
from services.rag_service import ContextAssembler
from services.retriever import hybrid_retriever
from services.rag_service import fetch_url_kb_context  # kept for URL context (string)
```

### Step 2: Replace RAG section in `run_agentic_rag_flow()`

Find the block from comment `# 1. Agentic RAG` through `# 3. Build prompt` and replace:

```python
        # 1. Agentic RAG: query ChromaDB filtered by confirmed tags
        query_text = " ".join(r.description for r in reqs)
        log_agent(f"[RAG] Querying for {entry.id} with tags={entry.tags}...")
        rag_context, rag_source = await query_rag_with_tags(
            query_text, entry.tags, state.collection, log_fn=log_agent
        )
        log_agent(f"[RAG] Source: {rag_source} | chars: {len(rag_context)}")

        # 2. Query Knowledge Base for best-practice context
        log_agent(f"[KB-RAG] Querying Knowledge Base for {entry.id}...")
        kb_context = await query_kb_context(
            query_text, entry.tags, state.kb_collection, log_fn=log_agent
        )
        if kb_context:
            log_agent(f"[KB-RAG] KB context chars: {len(kb_context)}")
        else:
            log_agent("[KB-RAG] No KB best practices found.")

        # 2b. Fetch live URL KB entries (tag-filtered, fetched at generation time)
        url_context = await fetch_url_kb_context(
            entry.tags, state.kb_docs, log_fn=log_agent
        )
        if url_context:
            log_agent(f"[KB-URL] URL context chars: {len(url_context)}")
            kb_context = (kb_context + "\n\n" + url_context).strip() if kb_context else url_context

        # 3. Build prompt from meta-prompt template (G-09)
        prompt = build_prompt(
            source_system=source,
            target_system=target,
            formatted_requirements=query_text,
            rag_context=rag_context,
            kb_context=kb_context,
        )
```

with:

```python
        # 1. Multi-query hybrid retrieval (R8 + R9 + R12 + BM25 / Phase 2)
        query_text = " ".join(r.description for r in reqs)
        category   = entry.tags[0] if entry.tags else ""

        log_agent(f"[RAG] Hybrid retrieval for {entry.id} (tags={entry.tags})...")
        approved_chunks = await hybrid_retriever.retrieve(
            query_text,
            entry.tags,
            state.collection,
            source=source,
            target=target,
            category=category,
            log_fn=log_agent,
        )

        kb_scored_chunks = await hybrid_retriever.retrieve(
            query_text,
            entry.tags,
            state.kb_collection,
            source=source,
            target=target,
            category=category,
            log_fn=log_agent,
        )

        # 2. Fetch live URL KB entries (tag-filtered)
        url_raw = await fetch_url_kb_context(
            entry.tags, state.kb_docs, log_fn=log_agent
        )
        from services.retriever import ScoredChunk as _SC
        url_chunks = ([_SC(text=url_raw, score=0.5, source_label="kb_url")]
                      if url_raw else [])

        # 3. ContextAssembler: unified context with structured sections (R10)
        assembler   = ContextAssembler()
        rag_context = assembler.assemble(
            approved_chunks,
            kb_scored_chunks,
            url_chunks,
            max_chars=settings.ollama_rag_max_chars,
        )
        log_agent(f"[RAG] Assembled context: {len(rag_context)} chars")

        # 4. Build prompt from meta-prompt template (G-09)
        prompt = build_prompt(
            source_system=source,
            target_system=target,
            formatted_requirements=query_text,
            rag_context=rag_context,
            kb_context="",  # now included in rag_context via ContextAssembler
        )
```

### Step 3: Run full test suite — must stay green

```bash
python -m pytest tests/ -v -q
```

Expected: `247 passed`
> Note: Existing agent flow tests mock `generate_with_ollama` via `main.httpx.AsyncClient`.
> The `hybrid_retriever.retrieve()` call also uses `generate_with_ollama` for query expansion —
> if tests fail due to unexpected LLM calls, mock `services.retriever.generate_with_ollama` as well.

### Step 4: Commit

```bash
git add services/integration-agent/routers/agent.py
git commit -m "feat(phase2): wire HybridRetriever + ContextAssembler into run_agentic_rag_flow"
```

---

## Task 9: Create ADRs 027–030 and Update DOCS_MANIFEST

**Files:**
- Create: `docs/adr/ADR-027-bm25-hybrid-retrieval.md`
- Create: `docs/adr/ADR-028-multi-query-expansion.md`
- Create: `docs/adr/ADR-029-context-assembler.md`
- Create: `docs/adr/ADR-030-semantic-chunking-langchain.md`
- Modify: `services/integration-agent/routers/admin.py` (DOCS_MANIFEST)

### Step 1: Create ADR-027

Create `docs/adr/ADR-027-bm25-hybrid-retrieval.md`:

```markdown
# ADR-027 — BM25 Hybrid Retrieval: Dense + Sparse Ensemble

| Field        | Value                                          |
|--------------|------------------------------------------------|
| **Status**   | Accepted                                       |
| **Date**     | 2026-03-20                                     |
| **Tags**     | rag, retrieval, bm25, chromadb, phase2         |

## Context
Pure dense retrieval (ChromaDB embeddings) underperforms on exact technical terms
(e.g. "SAP IDOC", "REST webhook", "SFTP batch"). BM25 sparse retrieval is strong
on keyword matching but weak on semantic similarity. Combining both addresses both failure modes.

## Decision
Introduce `rank_bm25` (BM25Okapi) alongside ChromaDB. Scores are normalised within each
retriever and merged with weights 0.6 (dense) / 0.4 (sparse), configurable via
`RAG_BM25_WEIGHT`. The BM25 index is built in-memory from KB chunk texts at startup
and rebuilt after every KB upload/delete.

## Alternatives Considered
- **Dense only** (current): misses keyword-heavy queries. Rejected.
- **Cross-encoder re-ranker**: too slow for CPU instances; deferred to Phase 2b.
- **ElasticSearch/OpenSearch**: operational overhead not justified for PoC scale. Rejected.

## Rollback
Remove `services/retriever.py` and revert `routers/agent.py` to use `query_rag_with_tags`.
No data migration required.
```

### Step 2: Create ADR-028

Create `docs/adr/ADR-028-multi-query-expansion.md`:

```markdown
# ADR-028 — Multi-Query Expansion: 2 Template + 2 LLM Variants

| Field        | Value                                          |
|--------------|------------------------------------------------|
| **Status**   | Accepted                                       |
| **Date**     | 2026-03-20                                     |
| **Tags**     | rag, query-expansion, llm, phase2              |

## Context
A single query over requirement descriptions misses semantically related content.
Multi-query retrieval (2-3 variants) consistently improves recall in RAG literature.

## Decision
Generate 4 query variants per integration: (1) original query text, (2) structured
template "{source}→{target} {category} integration pattern", (3+4) two LLM-generated
rephrasings (technical + business perspective) via a single lightweight Ollama call
(tag_llm settings: low timeout, low num_predict).

LLM variants are optional — if the call fails, only the 2 deterministic templates are
used. This ensures no pipeline dependency on LLM availability for retrieval.

## Rollback
Revert `_expand_queries` to return `[query_text]` only. No data changes.
```

### Step 3: Create ADR-029

Create `docs/adr/ADR-029-context-assembler.md`:

```markdown
# ADR-029 — ContextAssembler: Unified Context Fusion with Token Budget

| Field        | Value                                           |
|--------------|-------------------------------------------------|
| **Status**   | Accepted                                        |
| **Date**     | 2026-03-20                                      |
| **Tags**     | rag, context, prompt-engineering, phase2        |

## Context
The previous pipeline concatenated approved docs, KB chunks, and URL content as raw
strings with no structure. The LLM could not distinguish pattern types or prioritise
by relevance. Context regularly exceeded the token budget, causing truncation at an
arbitrary character boundary.

## Decision
`ContextAssembler.assemble()` takes scored chunks from all sources, sorts by relevance,
respects `ollama_rag_max_chars` budget, and formats output with explicit section headers:
"PAST APPROVED EXAMPLES" (style reference) and "BEST PRACTICE PATTERNS" (follow these).
Each chunk carries its score in the header for transparency.

## Rollback
Revert `run_agentic_rag_flow` to use `build_rag_context()` + `query_kb_context()`.
No data changes.
```

### Step 4: Create ADR-030

Create `docs/adr/ADR-030-semantic-chunking-langchain.md`:

```markdown
# ADR-030 — Semantic Chunking with LangChain RecursiveCharacterTextSplitter

| Field        | Value                                              |
|--------------|----------------------------------------------------|
| **Status**   | Accepted                                           |
| **Date**     | 2026-03-20                                         |
| **Tags**     | chunking, langchain, kb, document-parser, phase2   |

## Context
Fixed-size character splitting (1000 chars, 200 overlap) cuts through headings, paragraphs,
and sentences arbitrarily. Chunks containing incomplete thoughts degrade RAG retrieval quality.

## Decision
Add `semantic_chunk()` using `langchain-text-splitters` `RecursiveCharacterTextSplitter`
with separator priority: `["\n## ", "\n### ", "\n\n", "\n", ". ", " "]`.
The chunker attempts to split at heading boundaries first, then paragraph breaks, then
sentences, before falling back to character-level. Parameters (chunk_size, chunk_overlap)
remain identical to `chunk_text()` so no config changes are needed.

`chunk_text()` is preserved unchanged for backward compatibility.
Existing KB documents are not re-chunked; only new uploads use semantic chunking.

## Dependency
`langchain-text-splitters==0.3.8` — lightweight sub-package (no LLM deps).

## Rollback
Revert `routers/kb.py` to call `chunk_text()`. No data migration needed.
```

### Step 5: Update DOCS_MANIFEST in `routers/admin.py`

After the ADR-026 entry in `DOCS_MANIFEST`, add:

```python
    {"path": "adr/ADR-027-bm25-hybrid-retrieval.md", "name": "ADR-027 BM25 Hybrid Retrieval", "category": "ADR", "description": "BM25 + ChromaDB dense ensemble retrieval."},
    {"path": "adr/ADR-028-multi-query-expansion.md", "name": "ADR-028 Multi-Query Expansion", "category": "ADR", "description": "2 template + 2 LLM query variants."},
    {"path": "adr/ADR-029-context-assembler.md", "name": "ADR-029 ContextAssembler", "category": "ADR", "description": "Unified context fusion with token budget."},
    {"path": "adr/ADR-030-semantic-chunking-langchain.md", "name": "ADR-030 Semantic Chunking", "category": "ADR", "description": "LangChain RecursiveCharacterTextSplitter."},
```

### Step 6: Run full test suite — must stay green

```bash
python -m pytest tests/ -v -q
```

Expected: `247 passed`

### Step 7: Commit

```bash
git add docs/adr/ADR-027-bm25-hybrid-retrieval.md \
        docs/adr/ADR-028-multi-query-expansion.md \
        docs/adr/ADR-029-context-assembler.md \
        docs/adr/ADR-030-semantic-chunking-langchain.md \
        services/integration-agent/routers/admin.py
git commit -m "docs(phase2): add ADR-027..030 for BM25, multi-query, ContextAssembler, semantic chunking"
```

---

## Task 10: Final Verification

### Step 1: Run complete test suite

```bash
cd services/integration-agent
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: `247 passed, 0 failed, 1 warning`

### Step 2: Verify new packages import cleanly

```bash
python -c "
from services.retriever import HybridRetriever, ScoredChunk, hybrid_retriever
from services.rag_service import ContextAssembler
from document_parser import semantic_chunk
from config import settings
print('rag_top_k_chunks:', settings.rag_top_k_chunks)
print('rag_bm25_weight:', settings.rag_bm25_weight)
print('All Phase 2 imports OK')
"
```

Expected: `All Phase 2 imports OK`

### Step 3: Final commit + tag

```bash
git add -A
git commit -m "feat(phase2): complete RAG Quality pipeline — R8/R9/R10/R11/R12 + BM25 hybrid"
```

---

## Summary of Changes

| File | Action | Reason |
|------|--------|--------|
| `requirements.txt` | Add 3 packages | LangChain splitter, rank-bm25, scikit-learn |
| `config.py` | +4 params | rag_distance_threshold, rag_bm25_weight, rag_n_results_per_query, rag_top_k_chunks |
| `state.py` | +1 field | `kb_chunks: dict[str, list[str]]` for BM25 corpus |
| `document_parser.py` | +1 function | `semantic_chunk()` — R11 |
| `services/retriever.py` | **NEW** | `HybridRetriever` — R8, R9, R12, BM25 |
| `services/rag_service.py` | +1 class | `ContextAssembler` — R10 |
| `routers/kb.py` | Updated | Use `semantic_chunk` + BM25 rebuild |
| `main.py` | Updated | BM25 index build at startup |
| `routers/agent.py` | Updated | Use `HybridRetriever` + `ContextAssembler` |
| `routers/admin.py` | Updated | DOCS_MANIFEST +4 ADRs |
| `docs/adr/ADR-027..030` | **NEW** | Architecture decisions |
| `tests/test_semantic_chunk.py` | **NEW** | 7 tests |
| `tests/test_retriever.py` | **NEW** | 17 tests |
| `tests/test_context_assembler.py` | **NEW** | 7 tests |
