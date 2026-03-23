# ADR-035 — RAPTOR-lite Section Summaries

| Field        | Value                                                        |
|--------------|--------------------------------------------------------------|
| **Status**   | Accepted                                                     |
| **Date**     | 2026-03-23                                                   |
| **Tags**     | rag, retrieval, raptor, summaries, chromadb, phase4          |

## Context

The existing hybrid retriever (BM25 + ChromaDB dense, ADR-027) operates at **chunk level**
(~500 chars). When a user uploads a long integration specification, individual chunks capture
local detail but lose section-level context: e.g. "field mapping between PLM and PIM" might
appear in 8 chunks across 3 sections, but no single chunk explains *why* the mapping exists
or what the overall data-flow looks like.

This is the "lost-in-the-middle" problem for long documents. The full RAPTOR algorithm
(Recursive Abstractive Processing for Tree-Organised Retrieval, Sarthi et al. 2024) addresses
it by clustering chunks and building a recursive summary tree. Full RAPTOR requires an
embedding clustering step (k-means or UMAP) that adds significant complexity and latency.

## Alternatives Considered

### Alt A — Full RAPTOR with k-means clustering
- Cluster all chunks in embedding space; summarise each cluster; recurse.
- Pros: theoretically optimal coverage; proven in academic literature.
- Cons: requires UMAP/k-means at index time (minutes on large corpora); clusters are
  content-based (not aligned with document structure); harder to explain/debug.
- **Rejected**: Operational complexity is disproportionate to the PoC scale. Latency at
  upload time would exceed acceptable limits on CPU-only instances.

### Alt B — RAPTOR-lite: section-header grouping (chosen)
- Group `DoclingChunk` objects by their `section_header` field (populated by ADR-034).
- Sections with ≥ 3 chunks are summarised via a single llama3.1:8b call.
- Summaries are stored in a dedicated ChromaDB collection (`kb_summaries`).
- At retrieval time, a dense-only query over `kb_summaries` returns up to 3 `ScoredChunk`
  objects with `source_label="summary"`, which are injected as the first context section.
- Disabled via `raptor_summarization_enabled=False` with zero performance impact.
- **Chosen**: Aligns with existing `section_header` metadata (no extra embedding step);
  deterministic grouping (no clustering randomness); graceful fallback.

### Alt C — Sliding-window abstractive summarisation
- Summarise every fixed-size window of N chunks regardless of section boundaries.
- Pros: simple to implement.
- Cons: window boundaries are arbitrary; may split coherent sections; produces redundant
  summaries for short documents.
- **Rejected**: Section-header grouping (Alt B) is more semantically coherent at equivalent
  implementation cost.

## Decision

Implement RAPTOR-lite as described in Alt B:

1. **Ingest path** (`routers/kb.py`):
   - After `parse_with_docling()` produces `DoclingChunk` objects, group by `section_header`
     using `itertools.groupby`.
   - For each group with ≥ `_MIN_CHUNKS_FOR_SUMMARY` (3) chunks, call
     `summarizer_service.summarize_section(chunks, doc_id, tags)`.
   - On success, upsert the resulting `SummaryChunk` to `state.summaries_col` with metadata
     `{document_id, section_header, tags_csv}`.
   - On any LLM failure or if `raptor_summarization_enabled=False`, skip silently.

2. **Retrieval path** (`services/retriever.py`):
   - `HybridRetriever.retrieve_summaries(query_text, tags, summaries_col, top_k=3)`.
   - Dense-only (no BM25): summaries are long descriptive text better suited to semantic search.
   - Applies `_tags_match_meta()` tag filter (same logic as `_query_chroma`).
   - Returns `ScoredChunk(source_label="summary")`.
   - Returns `[]` when `summaries_col is None` (collection unavailable).

3. **Context assembly** (`services/rag_service.py`):
   - `ContextAssembler.assemble()` extended with `summary_chunks` kwarg.
   - When non-empty, inserts `## DOCUMENT SUMMARIES (overview context):` as the **first**
     section, before `## PAST APPROVED EXAMPLES` and `## BEST PRACTICE PATTERNS`.
   - Separate char budget: `rag_summary_max_chars` (default 500).
   - The total context budget is raised to `ollama_rag_max_chars=3000` (was 1500).

## New Dataclass

```python
@dataclass
class SummaryChunk:
    text: str
    document_id: str
    section_header: str
    tags: list[str] = field(default_factory=list)
```

## ChromaDB Collection

| Collection     | Purpose                               | Created at          |
|----------------|---------------------------------------|---------------------|
| `kb_summaries` | RAPTOR-lite document section summaries | App startup (lifespan) |

`state.summaries_col` holds the collection reference alongside `state.kb_collection`.

## Configuration

| Setting                          | Default | Purpose                                        |
|----------------------------------|---------|------------------------------------------------|
| `raptor_summarization_enabled`   | `True`  | Enable/disable RAPTOR-lite summarisation       |
| `rag_summary_max_chars`          | `500`   | Char budget for DOCUMENT SUMMARIES section     |
| `ollama_rag_max_chars`           | `3000`  | Total context budget (raised from 1500)        |

## Validation Plan

- `tests/test_summarizer_service.py` — 7 tests:
  - `SummaryChunk` fields populated from LLM response
  - `raptor_summarization_enabled=False` returns `None`
  - Fewer than 3 chunks returns `None`
  - LLM failure returns `None` (no crash)
  - `doc_id` and `section_header` propagated correctly
  - Tags forwarded to `SummaryChunk.tags`
  - Empty `generate_with_retry` response returns `None`
- `tests/test_retriever.py` (4 new tests):
  - `retrieve_summaries` returns `ScoredChunk` with `source_label="summary"`
  - Tag filtering excludes mismatched summaries
  - `summaries_col=None` returns `[]`
  - Top-K limit respected
- `tests/test_context_assembler.py` (4 new tests):
  - `## DOCUMENT SUMMARIES` section present when `summary_chunks` non-empty
  - Section appears before `## PAST APPROVED EXAMPLES`
  - Section absent when `summary_chunks=[]` or omitted
  - `summary_max_chars` budget enforced
- `tests/test_advanced_rag_pipeline_integration.py`:
  - Scenario 2: upload doc with ≥ 4 chunks in same section → `SummaryChunk.text` in summaries_col
  - Scenario 3: retrieve → `ContextAssembler` output contains `DOCUMENT SUMMARIES`

## Rollback

1. Set `RAPTOR_SUMMARIZATION_ENABLED=false` → upload flow skips summarisation immediately;
   existing `kb_summaries` entries are not queried (retrieve_summaries returns `[]` only when
   collection is absent, but tag-filtered queries will naturally skip unrelated entries).
2. Drop the `kb_summaries` ChromaDB collection: `chroma_client.delete_collection("kb_summaries")`.
3. Revert `ContextAssembler.assemble()` call sites in `agent_service.py` to omit
   `summary_chunks` kwarg (backward-compatible: parameter defaults to `None`).
4. Revert `state.py` (`summaries_col = None`) and `main.py` lifespan — no data migration needed.

## Accenture Compliance

All summarisation is performed locally via Ollama llama3.1:8b.
No content leaves the server boundary.
