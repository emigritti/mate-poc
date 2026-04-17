# ADR-048 — KB Metadata v2 Schema and In-Place Enrichment

**Status:** Accepted  
**Date:** 2026-04-17  
**Deciders:** Emiliano Gritti  
**Refs:** ADR-044 (KB semantic enrichment), ADR-026 (modular decomposition), ADR-027 (hybrid retrieval), ADR-043 (intent-aware retrieval)

---

## Context

ADR-044 introduced a first semantic enrichment layer for KB chunks at upload time, producing 6 metadata fields (`semantic_type`, `entity_names`, `field_names`, `rule_markers`, `integration_keywords`, `source_modality`).  This layer has two limitations:

1. **Retroactive gap** — chunks uploaded before ADR-044 have no semantic fields.
2. **Coarse taxonomy** — the 8-type `semantic_type` is not fine-grained enough to drive intent-aware re-ranking.

The goal of ADR-048 is to enrich the entire existing KB with a richer v2 metadata schema and wire that schema into the retrieval pipeline for measurably better Integration Spec quality.

---

## Decision

### 1. In-place enrichment — not destroy/recreate, not shadow collections

**Rejected: Destroy + recreate** — Users would need to manually re-upload all documents.  Disruptive and error-prone.

**Rejected: Shadow collections (`chroma_kb_v1` / `chroma_kb_v2`)** — Dual BM25 indices, dual retrieval paths, complex merge logic.  Overkill for a PoC with no production SLA.

**Accepted: In-place enrichment via ChromaDB `upsert()`** — Same chunk IDs, same document text, updated metadata dict.  ChromaDB leaves the existing embedding unchanged.  A `kb_schema_version=v2` flag tags enriched chunks.  V1 chunks remain readable and the retriever degrades gracefully for any chunk that lacks the new fields.

### 2. v2 Metadata Schema

Defined in `services/integration-agent/services/metadata_schema.py`.

**Minimum required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `chunk_id` | str | ChromaDB ID for the chunk |
| `document_id` | str | Parent document identifier |
| `kb_schema_version` | str | Always `"v2"` after enrichment |
| `source_modality` | str | `pdf\|docx\|xlsx\|html\|md\|…` |
| `chunk_type` | str | See `ChunkType` (12 values) |
| `semantic_type` | str | See `SemanticType` (15 values) |
| `section_header` | str | Nearest section heading |
| `page_num` | int | Source page |
| `entity_names` | csv | PascalCase entity names |
| `field_names` | csv | snake_case field names |
| `system_names` | csv | Capitalised system/service names |
| `business_terms` | csv | Integration domain vocabulary |
| `rule_markers` | csv | Normative language markers |
| `integration_keywords` | csv | Protocol/integration keywords |
| `state_transitions` | csv | `A -> B` state changes |
| `error_markers` | csv | Fault/recovery vocabulary |
| `tags_csv` | csv | Existing tags (backward compat) |
| `contains_table` | bool | Content structure flag |
| `contains_rules` | bool | Content structure flag |
| `contains_mapping` | bool | Content structure flag |
| `confidence_semantic_enrichment` | float | 0.5–0.95 rule-based signal strength |
| `enrichment_method` | str | `"rule_only"` (LLM layer deferred) |
| `is_active` | bool | Lifecycle flag |

**`ChunkType` taxonomy (12 values):**  
`text | table | figure | code | rule | mapping | ui_flow | validation | state_transition | endpoint | schema | summary`

**`SemanticType` taxonomy (15 values, replacing ADR-044's 8):**  
`generic_context | business_rule | data_mapping_candidate | integration_flow | system_overview | error_handling | validation_rule | entity_definition | field_definition | api_contract | event_definition | ui_interaction | state_model | security_requirement | diagram_or_visual`

### 3. Semantic Classifier

`services/integration-agent/services/semantic_classifier.py`

Deterministic rule-based extraction (no LLM, no I/O).  Reuses all vocabulary sets from ADR-044 (`document_parser.py`) and extends them with `_MAPPING_MARKERS`, `_STATE_MARKERS`, `_VALIDATION_MARKERS`, `_EVENT_MARKERS`, `_UI_MARKERS`, `_BUSINESS_TERMS`, `_SYSTEM_CONTEXT_PATTERN`.

Priority-ordered scoring table (first threshold that fires wins):

| Priority | Condition | SemanticType |
|----------|-----------|--------------|
| 1 | chunk_type == figure | `diagram_or_visual` |
| 2 | chunk_type == table | `data_mapping_candidate` |
| 3 | validation_score ≥ 3 | `validation_rule` |
| 4 | rule_score ≥ 2 | `business_rule` |
| 5 | error_score ≥ 2 | `error_handling` |
| 6 | security_score ≥ 2 | `security_requirement` |
| 7 | mapping_score ≥ 2 | `data_mapping_candidate` |
| 8 | state_score ≥ 3 | `state_model` |
| 9 | event_score ≥ 2 | `event_definition` |
| 10 | ui_score ≥ 3 | `ui_interaction` |
| 11 | integ_score ≥ 3 | `api_contract` |
| 12 | arch_score ≥ 2 | `integration_flow` |
| 13 | field_score ≥ 5 | `field_definition` |
| 14 | entity_score ≥ 3 | `entity_definition` |
| 15 | short text, 0 fields | `system_overview` |
| 16 | default | `generic_context` |

`document_parser.enrich_chunk_metadata()` now delegates to `semantic_classifier.classify_chunk()`, so new uploads automatically receive v2 metadata.

### 4. KB Enrichment Service

`services/integration-agent/services/kb_enrichment_service.py`

- `enrich_document(doc_id, kb_collection, *, force=False) -> EnrichmentResult`  
  Reads all chunks for a doc from ChromaDB, classifies each, upserts updated metadata.  Skips chunks already at v2 unless `force=True`.

- `enrich_all_documents(kb_collection, *, max_docs=None, force=False) -> BatchEnrichmentResult`  
  Iterates all unique `document_id` values, delegates to `enrich_document`, reports summary.

Two new API endpoints (auth-protected):
- `POST /api/v1/kb/enrich` — batch enrichment
- `POST /api/v1/kb/enrich/{document_id}` — single document

### 5. Retriever Enhancement

`services/integration-agent/services/retriever.py`

- `ScoredChunk` dataclass gains `semantic_type: str = ""` — populated from ChromaDB metadata for v2 chunks; empty for v1 (no penalty).
- New `_apply_semantic_bonus()` method: after TF-IDF re-rank, adds a +0.08 score bonus to chunks whose `semantic_type` matches the retrieval intent.  No hard filter — v1 chunks are still returned, just without the bonus.
- Intent → bonus semantic types mapping:
  - `overview` → `system_overview`, `integration_flow`
  - `business_rules` → `business_rule`, `validation_rule`
  - `data_mapping` → `data_mapping_candidate`, `field_definition`, `entity_definition`
  - `errors` → `error_handling`
  - `architecture` → `integration_flow`, `api_contract`, `security_requirement`

### 6. Context Assembler Enhancement

`services/integration-agent/services/rag_service.py`

KB chunk section headers now include the `semantic_type` hint when present:
```
### Source: kb_file · score: 0.87 · type: data_mapping_candidate
```
This surfaces the classification to the LLM, enabling it to weight chunks by their semantic role during Integration Spec generation.

---

## Alternatives Considered

| Approach | Reason Rejected |
|----------|-----------------|
| Destroy + recreate KB | Requires manual re-upload of all source files; disruptive |
| Shadow collection (chroma_kb_v1/v2) | Dual indices, dual retrieval logic, high complexity for PoC |
| LLM-assisted enrichment (Layer 3) | Deferred; rule-based quality must be validated first |
| Hard filter on semantic_type | Would exclude v1 chunks entirely; backward compatibility broken |

---

## Consequences

**Positive:**
- Existing KB chunks gain rich semantic metadata without re-uploading documents
- New uploads automatically receive v2 metadata via `enrich_chunk_metadata()`
- Retrieval quality improves via semantic intent bonus (measurable via section completeness)
- Context assembly surfaces chunk semantics to the LLM
- Full backward compatibility: v1 chunks continue to work without change

**Negative/Risks:**
- Enrichment is rule-based only (no LLM Layer 3 yet); semantic_type may be imprecise for ambiguous chunks
- `confidence_semantic_enrichment` is a heuristic (0.5–0.95) — not calibrated against ground truth

---

## Rollback Strategy

No data is lost. If enrichment produces poor results:
1. Revert the code changes (git revert)
2. Optionally re-run `enrich_all_documents(force=True)` after fix
3. V1 chunks (no `kb_schema_version`) are never deleted — they remain fully functional

---

## Validation Plan

1. `python -m pytest tests/test_metadata_schema.py tests/test_semantic_classifier.py tests/test_kb_enrichment_service.py -v` — all pass
2. Full suite regression: `python -m pytest tests/ -v` — 329+ tests pass, 0 regressions
3. Call `POST /api/v1/kb/enrich` on a live instance → verify `kb_schema_version=v2` on chunks via ChromaDB query
4. Generate an Integration Spec before and after enrichment → compare `n/a` section count
5. Upload a new document → verify v2 metadata present in ChromaDB

---

## Files Changed

| File | Change |
|------|--------|
| `services/integration-agent/services/metadata_schema.py` | NEW |
| `services/integration-agent/services/semantic_classifier.py` | NEW |
| `services/integration-agent/services/kb_enrichment_service.py` | NEW |
| `services/integration-agent/document_parser.py` | `enrich_chunk_metadata()` delegates to classifier |
| `services/integration-agent/routers/kb.py` | 2 new enrichment endpoints |
| `services/integration-agent/services/retriever.py` | `ScoredChunk.semantic_type`, `_apply_semantic_bonus()` |
| `services/integration-agent/services/rag_service.py` | `semantic_type` hint in context headers |
| `tests/test_metadata_schema.py` | NEW (unit tests) |
| `tests/test_semantic_classifier.py` | NEW (unit tests) |
| `tests/test_kb_enrichment_service.py` | NEW (unit tests) |
