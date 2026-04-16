# ADR-044 — KB Semantic Metadata Enrichment and Upload Pipeline Deduplication

**Status:** Accepted
**Date:** 2026-04-16
**Author:** Integration Mate Team
**Related:** ADR-031 (Docling + LLaVA parser), ADR-032 (RAPTOR-lite summaries),
             ADR-043 (intent-aware retrieval)

---

## Context

Two independent problems were identified in `routers/kb.py` by SME review:

**Problem 1 — KB metadata is "multi-format correct" but semantically thin.**
The current upload pipeline stores six metadata fields per chunk:
`document_id`, `filename`, `chunk_index`, `chunk_type`, `page_num`, `section_header`,
and `tags_csv`. These fields describe the chunk's *position* in the document, but not
its *meaning* for integration generation. The retriever cannot distinguish a chunk that
defines business rules from one that contains a field mapping table or an error handling
pattern without reading its full text. As stated by the SME:

> "The KB today is 'multi-format correct', but I would make it stronger in semantic
> normalisation. … this way the retriever can become much smarter without always
> depending on free text."

**Problem 2 — Upload pipeline is duplicated between single and batch endpoints.**
`kb_upload()` (lines 110–219) and `kb_batch_upload()` (lines 222–329) contain
substantially identical logic: parse with Docling, auto-tag via LLM, upsert to ChromaDB,
update `state.kb_docs` / `state.kb_chunks`. The only intentional difference is RAPTOR
timing (background in single, inline in batch). Any future enrichment added to one
endpoint must be manually mirrored to the other, risking drift.

---

## Decision

### 1. Add `enrich_chunk_metadata()` to `document_parser.py`

A pure function that takes a `DoclingChunk` and the `source_modality` (file extension)
and returns a dict of 6 new metadata fields:

| Field | Type stored | Description |
|-------|------------|-------------|
| `semantic_type` | `str` | One of 8 fixed values classifying the chunk's functional role |
| `entity_names` | `str` (CSV) | PascalCase/CamelCase entity names found in the text (max 10) |
| `field_names` | `str` (CSV) | snake_case field names found in the text (max 15) |
| `rule_markers` | `str` (CSV) | Normative language found ("mandatory", "must", "validation", …) |
| `integration_keywords` | `str` (CSV) | Integration-domain terms found ("api", "webhook", "oauth", …) |
| `source_modality` | `str` | File extension passed in ("pdf", "docx", "md", …) |

**Semantic type classification** (deterministic, no LLM call):

| `semantic_type` | Condition |
|----------------|-----------|
| `"data_mapping_candidate"` | `chunk_type == "table"` |
| `"diagram_or_visual"` | `chunk_type == "figure"` |
| `"business_rule"` | text: ≥ 2 rule markers (mandatory, must, required, …) |
| `"error_handling"` | text: ≥ 2 error keywords (error, retry, fallback, …) |
| `"security_requirement"` | text: ≥ 2 security keywords (authentication, tls, credential, …) |
| `"architecture"` | text: ≥ 2 architecture keywords (architecture, pipeline, interface, …) |
| `"data_definition"` | text: ≥ 3 snake_case field names detected |
| `"general_text"` | fallback |

All values are plain strings (ChromaDB metadata constraint: no list types).
List-typed fields use comma-separated encoding, consistent with the existing
`tags_csv` convention.

**No LLM call** — deterministic extraction via frozenset membership checks and
`re.Pattern.findall()`. Zero latency added per chunk.

### 2. Extract `_process_kb_file()` shared pipeline function in `routers/kb.py`

A new private async function handles the shared pipeline steps:
parse → auto-tag → enrich → ChromaDB upsert → state update.

```
_process_kb_file(content, filename, file_type)
  → (doc_id, docling_chunks, auto_tags, tags_csv)
```

Raises `RuntimeError` on failure (parse error, empty document, ChromaDB write failure);
the caller maps this to the appropriate HTTP response:
- `kb_upload()` → `HTTPException(422)`
- `kb_batch_upload()` → `append error result, continue`

Steps remaining in each endpoint (intentional divergence):
- BM25 index rebuild (called after each file)
- MongoDB store
- RAPTOR timing: background (`background_tasks.add_task()`) in single, inline (`await`) in batch

---

## New Extraction Constants (`document_parser.py`)

| Constant | Purpose |
|----------|---------|
| `_RULE_MARKERS` | 15 normative language terms for business-rule detection |
| `_INTEGRATION_KEYWORDS` | 19 integration-domain terms for protocol/pattern detection |
| `_ARCHITECTURE_KEYWORDS` | 13 structural terms for architecture chunk detection |
| `_ERROR_KEYWORDS` | 11 fault-tolerance terms |
| `_SECURITY_KEYWORDS` | 12 security/auth terms |
| `_FIELD_PATTERN` | `re.Pattern` — snake_case field names |
| `_ENTITY_PATTERN` | `re.Pattern` — PascalCase/CamelCase entity names |

---

## Modified Files

| File | Change |
|------|--------|
| `document_parser.py` | Added constants + `enrich_chunk_metadata()` public function |
| `routers/kb.py` | Added `_process_kb_file()`; refactored `kb_upload()` and `kb_batch_upload()` to use it; imports `enrich_chunk_metadata` |
| `tests/test_document_parser.py` | Added `TestEnrichChunkMetadata` — 15 tests |
| `tests/test_kb_upload_docling.py` | Added `test_upload_stores_semantic_metadata_in_chromadb` — 1 test |

---

## Alternatives Considered

### Alt A — LLM-based semantic extraction per chunk

Use an Ollama call to extract `semantic_type`, `entity_names`, etc. from each chunk
as structured JSON (similar to the FactPack extraction in ADR-041).

**Rejected:** One LLM call per chunk × up to hundreds of chunks per document would
increase upload latency from ~5 s to several minutes on a CPU-only t3.2xlarge. The
RAPTOR summarization already adds LLM calls per section (capped by
`kb_max_summarize_sections`). Deterministic extraction at zero latency is sufficient
for the phase-1 enrichment goal.

### Alt B — Add `semantic_type` field only (no field/entity extraction)

Implement only the `semantic_type` classification and skip field/entity/keyword extraction.

**Rejected:** `entity_names`, `field_names`, and `integration_keywords` are low-cost to
extract (regex-only) and directly enable future ADR-043 intent-aware retrieval boosting
without requiring additional ChromaDB schema migrations. Extracting them now is cheaper
than a future migration.

### Alt C — Separate enrichment service module

Create `services/semantic_enricher.py` as a standalone module.

**Rejected:** Per CLAUDE.md §8, a new file for a single function called only from one
location is a premature abstraction. `enrich_chunk_metadata()` belongs in
`document_parser.py` alongside the `DoclingChunk` it analyses.

### Alt D — Merge all upload logic including RAPTOR and BM25

Fully unify the pipeline so a single function handles parse through BM25 rebuild, with
a parameter controlling RAPTOR timing.

**Rejected:** BM25 rebuild and RAPTOR timing represent genuinely different operational
contracts between the two endpoints. Keeping them in the callers makes each endpoint's
behavior explicit without a complex `raptor_mode` parameter.

---

## Consequences

**Positive:**
- ChromaDB now stores semantic intent metadata alongside structural metadata, enabling
  future retrieval improvements (ADR-043 `intent` parameter can filter/boost by
  `semantic_type` without full-text search).
- Elimination of pipeline duplication reduces risk of single/batch drift when future
  enrichment is added.
- `enrich_chunk_metadata()` is a pure function — independently testable, no LLM calls,
  zero risk of runtime failure.
- 15 new unit tests validate all 8 `semantic_type` values plus extraction correctness.

**Negative / Trade-offs:**
- Each ChromaDB chunk now stores 6 additional metadata fields. Storage overhead is
  negligible (~200 bytes per chunk) but the fields are opaque to the current retriever
  (ADR-043 `intent` is not yet wired to filter on `semantic_type`).
- `_RULE_MARKERS`, `_INTEGRATION_KEYWORDS`, etc. require manual update if new domain
  terminology must be recognised. Frequency of updates is expected to be low.
- Heuristic entity extraction (PascalCase regex) may produce false positives on
  document-starting words. Limiting to `_ENTITY_PATTERN` (multi-component CamelCase)
  mitigates but does not eliminate this.

---

## Security Considerations

- All extraction is deterministic — no external calls, no user-supplied code execution.
- `source_modality` is derived from the server-side `detect_file_type()` result, never
  from user-supplied metadata, so it cannot be injected.
- The metadata fields are stored in ChromaDB. They do not affect prompt construction
  and are not currently surfaced in LLM context. No prompt-injection risk.

---

## Validation Plan

| Test | Coverage |
|------|---------|
| `TestEnrichChunkMetadata` (15 tests) | All 8 `semantic_type` values; snake_case field extraction; CamelCase entity extraction; rule markers, integration keywords; `source_modality` passthrough; ChromaDB string-value constraint; empty-text edge case |
| `test_upload_stores_semantic_metadata_in_chromadb` | All 6 semantic fields present in ChromaDB upsert call; all values are strings |
| Pre-existing 70 tests in `test_document_parser.py` + KB test files | Verify no regression in existing metadata fields, BM25 corpus, RAPTOR summarization |

Total new tests: 16 (15 + 1).

---

## Rollback Strategy

1. **Instant rollback:** Remove the `**enrich_chunk_metadata(c, file_type)` spread from
   the metadata dict in `_process_kb_file()`. ChromaDB will stop receiving the 6 new fields.
   Existing documents already stored retain the fields (harmless extra metadata).

2. **Code rollback:** Revert `document_parser.py` and `routers/kb.py` to pre-ADR-044
   commits. No schema migration required — ChromaDB ignores unrecognised metadata fields
   during `query()` and `get()` calls.
