# Phase 2 — RAG Quality: Design Document

| Field        | Value                                              |
|--------------|----------------------------------------------------|
| **Date**     | 2026-03-20                                         |
| **Phase**    | 2 — RAG Quality                                    |
| **Scope**    | R8, R9, R10, R11, R12 + BM25 Hybrid Retrieval     |
| **Status**   | Approved — ready for implementation                |
| **ADRs**     | ADR-027, ADR-028, ADR-029, ADR-030                 |

---

## Context

Phase 1 delivered the backend decomposition (R15), LLM retry (R13), and frontend foundation
(R1, R3). The RAG pipeline is functional but naive:

- **Single-query**: one ChromaDB call per integration, no semantic expansion
- **No relevance filtering**: all results used regardless of distance score
- **Naive concatenation**: approved docs + KB chunks + URL content joined as raw strings
- **Fixed-size chunking**: 1000-char splits ignore paragraph/heading boundaries
- **Fragile tag filter**: only first tag matched via `$contains` string search
- **No BM25**: pure dense retrieval misses exact technical terms (e.g. "SAP IDOC", "REST webhook")

Phase 2 upgrades the RAG pipeline to production quality before adding generation improvements
in Phase 3.

---

## Decisions Made (Brainstorming Session 2026-03-20)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LangChain dependency | Yes — introduce `langchain-community` | Future extensibility (Phase 2b multimodal, Phase 3 agents) |
| Query expansion strategy | **Hybrid 2+2**: 2 template + 2 LLM variants | Deterministic coverage + semantic richness; LLM fallback if unavailable |
| Re-ranking | **Distance threshold + TF-IDF** (scikit-learn) | Right trade-off for small enterprise corpus |
| BM25 Hybrid | **Included in Phase 2** via `rank_bm25` + LangChain `EnsembleRetriever` | Low effort with LangChain; improves recall on technical terms |
| Architecture pattern | **Approach C**: new `services/retriever.py` module | Isolates complexity; `rag_service.py` remains stable public API |
| Multimodal (images/graphs) | **Deferred to Phase 2b** (separate branch) | Scope control; requires LLaVA + PyMuPDF |
| Chunking | **LangChain `RecursiveCharacterTextSplitter`** | Semantic boundaries; heading → paragraph → sentence priority |

---

## Architecture

### Module Layout

```
services/integration-agent/
├── services/
│   ├── llm_service.py       (unchanged — R13 done in Phase 1)
│   ├── tag_service.py       (unchanged)
│   ├── retriever.py         ← NEW  (R8, R9, R12, BM25 Hybrid)
│   └── rag_service.py       ← UPDATED  (R10 ContextAssembler)
├── document_parser.py       ← UPDATED  (R11 semantic chunking)
├── config.py                ← UPDATED  (new RAG config params)
└── routers/agent.py         ← UPDATED  (use new pipeline)
```

### New Dependencies (`requirements.txt`)

```
langchain-community>=0.2
rank-bm25>=0.2.2
scikit-learn>=1.4
```

---

## R8 — Multi-Query Expansion

### Query Generation

```
Input: query_text (joined requirement descriptions), tags, source, target, category
         │
         ├── Template 1:  query_text  (original — always present)
         ├── Template 2:  "{source}→{target} {category} integration pattern"
         ├── LLM 1:       technical rephrase   ┐
         └── LLM 2:       business rephrase    ┘ single Ollama call (tag_llm settings)
```

**LLM expansion prompt** (lightweight — uses `tag_llm` settings: low num_predict, temperature=0.3):
```
Given this integration query: "{query}"
Generate 2 alternative phrasings:
1. A technical systems integration perspective
2. A business process perspective
Reply with a JSON array only: ["technical variant", "business variant"]
```

**Fallback**: if LLM call fails or times out, only the 2 template variants are used.
The pipeline is never blocked by LLM unavailability.

### Deduplication

Results from all 4 queries are merged and deduplicated by `document_id` (ChromaDB metadata field).
When the same chunk appears in multiple query results, the **highest score** is kept.

---

## R9 — Relevance Threshold + Re-ranking + BM25 Hybrid

### Pipeline

```
4 query variants
      │
      ├──→ ChromaDB dense (include=["distances"])
      │     where: {"$or": [{"tags_csv": {"$contains": t}} for t in tags]}
      │     n_results=3 per query → up to 12 candidates
      │
      ├──→ BM25 sparse (rank_bm25 on KB chunk corpus)
      │     top-3 per query → up to 12 candidates
      │
      └──→ LangChain EnsembleRetriever
              weights: [0.6 ChromaDB, 0.4 BM25]
              │
              dedup by document_id (keep max score)
              │
              distance threshold: distance < settings.rag_distance_threshold (default: 0.8)
              │
              TF-IDF cosine re-rank (scikit-learn TfidfVectorizer)
              │
              top-K chunks → ContextAssembler
```

### BM25 Index Lifecycle

- **Built at startup**: `main.py` lifespan calls `retriever.build_bm25_index(state.kb_docs)`
- **Rebuilt on KB mutation**: `kb_upload`, `kb_delete` endpoints call `retriever.rebuild_bm25_index()`
- **In-memory only**: no persistence needed — rebuild is fast for small corpora
- **Thread safety**: rebuild is synchronous, guarded by the existing `agent_lock`

### New Config Parameters

```python
rag_distance_threshold: float = 0.8       # max distance for relevance filter
rag_bm25_weight: float = 0.4              # BM25 weight in ensemble (Chroma = 1 - this)
rag_n_results_per_query: int = 3          # ChromaDB n_results per query variant
rag_top_k_chunks: int = 5                 # final top-K after re-ranking
```

---

## R10 — ContextAssembler

### Responsibility

Replaces the naive string concatenation in `run_agentic_rag_flow()`. Collects chunks from
all three sources, orders by score, applies token budget, and formats with source metadata
so the LLM can distinguish pattern types.

### Output Format (prompt section)

```markdown
## PAST APPROVED EXAMPLES (use as style reference):
### Source: approved_integrations · score: 0.92
[chunk content]

## BEST PRACTICE PATTERNS (follow these patterns in your output):
### Source: API_Integration_Guide.pdf · tag: Data Sync · score: 0.87
[chunk content]
### Source: https://example.com/patterns · tag: Error Handling · score: 0.71
[chunk content]
```

### API

```python
class ContextAssembler:
    def assemble(
        self,
        approved_chunks: list[ScoredChunk],
        kb_chunks: list[ScoredChunk],
        url_chunks: list[ScoredChunk],
        max_chars: int,
    ) -> str: ...
```

`ScoredChunk` is a lightweight dataclass: `(text, score, source_label, tags)`.

### Backward Compatibility

`build_rag_context()` in `rag_service.py` is preserved unchanged. `ContextAssembler` is
additive — used only by the updated `run_agentic_rag_flow()`.

---

## R11 — Semantic Chunking

### New function `semantic_chunk()` in `document_parser.py`

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

def semantic_chunk(text: str, chunk_size: int, chunk_overlap: int) -> list[ChunkResult]:
    splitter = RecursiveCharacterTextSplitter(
        separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " "],
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )
    ...
```

**Separator priority**: H2 heading → H3 heading → blank line (paragraph) → newline → sentence → space.
The chunker respects semantic boundaries before falling back to character-level splitting.

### Backward Compatibility

`chunk_text()` is **preserved unchanged**. `semantic_chunk()` is the new function.
The KB upload endpoint (`routers/kb.py`) is updated to call `semantic_chunk()` instead.
Existing KB documents are not re-chunked (no migration needed).

---

## R12 — Multi-Dimensional Tag Filter

### Change in `retriever.py`

```python
# Before (fragile — only first tag, string contains)
where={"tags_csv": {"$contains": tags[0]}}

# After (all tags, $or filter)
where={"$or": [{"tags_csv": {"$contains": t}} for t in tags]}
```

No data migration required — `tags_csv` metadata field structure is unchanged.
The filter now participates all available tags instead of only the first.

---

## ADRs to Create

| ADR | Title | Key Decision |
|-----|-------|-------------|
| **ADR-027** | BM25 Hybrid Retrieval | Introduce `rank_bm25` + LangChain `EnsembleRetriever` (0.6/0.4 weights) |
| **ADR-028** | Multi-Query Expansion 2+2 | 2 template variants + 2 LLM variants with deterministic fallback |
| **ADR-029** | ContextAssembler — Unified Context Fusion | Structured prompt sections with source metadata and token budget |
| **ADR-030** | Semantic Chunking with LangChain | Replace fixed-size chunking with `RecursiveCharacterTextSplitter` |

---

## Testing Strategy (CLAUDE.md §7)

Every new module must have dedicated unit tests before the implementation is considered done.

| Test file | Covers |
|-----------|--------|
| `tests/test_retriever.py` | `expand_queries`, `threshold_filter`, `tfidf_rerank`, `ensemble`, `build_bm25_index` |
| `tests/test_context_assembler.py` | `ContextAssembler.assemble` — budget, ordering, formatting |
| `tests/test_semantic_chunk.py` | `semantic_chunk` — heading boundaries, overlap, fallback |
| Updated `tests/test_rag_filtering.py` | `query_rag_with_tags` updated for `$or` tag filter |

---

## Phase 2b (Deferred — Separate Branch)

The following items are explicitly out of scope for Phase 2 and will be addressed on a
dedicated `phase-2b-multimodal` branch after Phase 2 is merged:

- PDF/DOCX image extraction (PyMuPDF)
- Vision model integration (LLaVA 7B via Ollama)
- Multimodal chunk indexing (image descriptions → ChromaDB)

---

## Rollback Strategy

All Phase 2 changes are additive:
- `retriever.py` is a new file — removing it restores old behaviour
- `semantic_chunk()` is a new function — `chunk_text()` unchanged
- `ContextAssembler` is additive — `build_rag_context()` unchanged
- `$or` tag filter is a query-time change — no data migration

A full rollback is a single `git revert` of the Phase 2 commit(s).
