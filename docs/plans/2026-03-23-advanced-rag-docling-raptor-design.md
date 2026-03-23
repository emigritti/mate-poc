# Advanced RAG Pipeline — Docling + LLaVA + RAPTOR-lite

**Date:** 2026-03-23
**Status:** Implemented
**ADRs:** ADR-034 (Docling + LLaVA), ADR-035 (RAPTOR-lite)

---

## Problem Statement

The existing hybrid RAG pipeline (BM25Plus + ChromaDB, ADR-027/030) had two quality gaps:

1. **Visual content gap**: Charts, architecture diagrams, and data-flow figures in PDFs/DOCX
   were silently discarded. Integration documents rely heavily on visual content.
2. **Retrieval granularity gap**: Chunk-level retrieval loses section-level context.
   Related concepts spread across many chunks are not summarised for the LLM.

All processing must remain **100% local** (Accenture data-privacy compliance).

---

## Solution Overview

Combined implementation of two complementary improvements:

```
INGESTION (extended)
  File upload
    └─ parse_with_docling(file_bytes, file_type)
         ├─ TextItem  → DoclingChunk(chunk_type="text",   section_header, page_num)
         ├─ TableItem → DoclingChunk(chunk_type="table",  section_header, page_num)
         └─ PictureItem → caption_figure(img_bytes) → DoclingChunk(chunk_type="figure")
                                        │
                           RAPTOR-lite summariser
                           group by section_header
                           sections ≥ 3 chunks → summarize_section() → SummaryChunk
                           upsert SummaryChunk → summaries_col (ChromaDB "kb_summaries")
                                        │
         upsert all chunks (text+table+figure) → kb_collection (existing)
         rebuild BM25 index (all chunk types, including figure captions)

RETRIEVAL (extended)
  Query
    ├─ HybridRetriever.retrieve()         ← unchanged (BM25+ChromaDB, threshold, TF-IDF)
    ├─ HybridRetriever.retrieve_summaries() ← NEW (dense-only, summaries_col, top-3)
    └─ ContextAssembler.assemble(..., summary_chunks=...)
         ├─ ## DOCUMENT SUMMARIES      ← NEW (500 chars budget, first section)
         ├─ ## PAST APPROVED EXAMPLES  ← unchanged
         └─ ## BEST PRACTICE PATTERNS  ← unchanged
  Total context budget: 3000 chars (raised from 1500)
```

---

## New Components

### `services/vision_service.py`
`caption_figure(image_bytes: bytes) → str`

- Posts base64-encoded image bytes to `{OLLAMA_HOST}/api/chat` with model `llava:7b`.
- Controlled by `settings.vision_captioning_enabled` (default `True`).
- Returns `"[FIGURE: no caption available]"` on any error or when disabled.
- No exception propagates to the upload handler.

### `services/summarizer_service.py`
`summarize_section(chunks, doc_id, tags) → SummaryChunk | None`
`SummaryChunk` dataclass: `text, document_id, section_header, tags`

- Skips if `raptor_summarization_enabled=False` or section has fewer than 3 chunks.
- Calls `generate_with_retry()` (existing LLM service) with a concise prompt.
- Returns `None` on any LLM failure — no crash propagation.

### `DoclingChunk` dataclass (in `document_parser.py`)
```python
@dataclass
class DoclingChunk:
    text: str
    chunk_type: str      # "text" | "table" | "figure"
    page_num: int
    section_header: str
    index: int
    metadata: dict
```

---

## Modified Components

| Component | Change |
|-----------|--------|
| `config.py` | Added: `vision_captioning_enabled`, `vision_model_name`, `raptor_summarization_enabled`, `rag_summary_max_chars`; changed `ollama_rag_max_chars` 1500→3000 |
| `state.py` | Added `summaries_col = None` |
| `main.py` | Lifespan creates `kb_summaries` ChromaDB collection → `state.summaries_col` |
| `document_parser.py` | Added `DoclingChunk`, `parse_with_docling()`, `_docling_fallback()`; existing `parse_document()` and `semantic_chunk()` unchanged |
| `routers/kb.py` | Upload uses `parse_with_docling()`; groups by `section_header`; calls `summarize_section()`; upserts to `summaries_col`; BM25 includes all chunk types |
| `services/retriever.py` | Added `HybridRetriever.retrieve_summaries()` |
| `services/rag_service.py` | `ContextAssembler.assemble()` extended with `summary_chunks` and `summary_max_chars` params |
| `services/agent_service.py` | Calls `retrieve_summaries()` and passes `summary_chunks` to assembler |

---

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `vision_captioning_enabled` | `True` | Enable LLaVA figure captioning |
| `vision_model_name` | `"llava:7b"` | Ollama model for vision |
| `raptor_summarization_enabled` | `True` | Enable RAPTOR-lite section summaries |
| `rag_summary_max_chars` | `500` | Char budget for DOCUMENT SUMMARIES section |
| `ollama_rag_max_chars` | `3000` | Total RAG context budget |

---

## Tests Written (all GREEN)

| File | Count | Coverage |
|------|-------|----------|
| `tests/test_vision_service.py` | 5 | caption_figure(), disabled flag, timeout, connect error, HTTP error |
| `tests/test_document_parser_docling.py` | 7 | DoclingChunk fields, table/figure chunks, Docling fallback, empty doc |
| `tests/test_summarizer_service.py` | 7 | SummaryChunk fields, disabled, <3 chunks, LLM failure, tags |
| `tests/test_kb_upload_docling.py` | 4 | chunk_type metadata upserted, summaries upserted, BM25 rebuilt, empty file |
| `tests/test_retriever.py` (new additions) | 4 | retrieve_summaries: source_label, tag filter, None collection, top-K |
| `tests/test_context_assembler.py` (new additions) | 4 | DOCUMENT SUMMARIES section: present, order, absent, budget |
| `tests/test_advanced_rag_pipeline_integration.py` | 4 | E2E: 3 chunk types, summary stored, context has summaries, vision disabled |
| **Total new** | **35** | |

**Total test suite: 282 tests (247 baseline + 35 new) — all passing.**

---

## Fallback Strategy

| Scenario | Behaviour |
|----------|-----------|
| `docling` not installed | `parse_with_docling()` falls back to `_docling_fallback()` (legacy parser) |
| `vision_captioning_enabled=False` | Figure chunks get `"[FIGURE: no caption available]"` |
| LLaVA Ollama timeout/error | Same placeholder, no crash |
| `raptor_summarization_enabled=False` | `summarize_section()` returns `None`, no summary upserted |
| LLM summarisation failure | `None` returned, section silently skipped |
| `summaries_col=None` | `retrieve_summaries()` returns `[]`, no DOCUMENT SUMMARIES section |

---

## Accenture Compliance

- All inference runs locally via Ollama daemon (llama3.1:8b text, llava:7b vision).
- No file bytes or extracted content leave the server boundary.
- `OLLAMA_HOST` environment variable controls the Ollama endpoint (default: `localhost`).
- Complies with Accenture data classification: data classified as "Internal" or below only.
