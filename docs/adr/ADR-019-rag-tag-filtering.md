# ADR-019 — RAG Tag-Filtering with HITL Tag Confirmation Gate

| Field          | Value                                                            |
|----------------|------------------------------------------------------------------|
| **Status**     | Accepted                                                         |
| **Date**       | 2026-03-13                                                       |
| **Author**     | AI-assisted (Claude Code)                                        |
| **Supersedes** | —                                                                |
| **OWASP**      | A04:2021 — Insecure Design (validated output paths)              |
| **CLAUDE.md**  | §2 (Responsible AI), §7 (Unit Testing), §11 (AI/Agentic Security)|

---

## Context

The existing agentic RAG flow queried ChromaDB with pure similarity search before LLM generation. This caused two operational problems on CPU-only deployments:

1. **RAG relevance degradation** — similarity-only retrieval returned past examples from unrelated integration categories (e.g., image-sync docs appearing in enrichment prompts), reducing prompt quality and increasing hallucination risk.

2. **CPU timeout exposure** — large RAG contexts injected unfiltered into the prompt caused Ollama to exceed its `num_predict` budget on CPU-bound llama3.1:8b instances (~3 tok/s), sometimes producing truncated or empty output.

Additionally, the catalog entry was created inside the generation flow itself, making it impossible to attach human-validated metadata (tags) before generation started.

---

## Decision

Introduce a **HITL tag-confirmation gate** before document generation:

1. **Upload creates CatalogEntries immediately** with `status=PENDING_TAG_REVIEW`.
2. **`GET /suggest-tags`** proposes tags from: (a) unique `category` field values extracted from requirements (deterministic, ≤5); (b) optional LLM suggestions (≤2, graceful fallback to `[]` on failure).
3. **`POST /confirm-tags`** moves the entry to `TAG_CONFIRMED` and stores the confirmed tag list.
4. **`POST /trigger`** blocks with `409` if any entry has `status=PENDING_TAG_REVIEW`.
5. **Generation flow** iterates only `TAG_CONFIRMED` entries; calls `_query_rag_with_tags(query_text, entry.tags)` which:
   - First: tag-filtered ChromaDB query using `where={"tags_csv": {"$contains": primary_tag}}`
   - Fallback: similarity-only query if no tag-matched results
   - Returns `(context_str, source_label)` where label is `tag_filtered | similarity_fallback | none`
6. **Approval (ChromaDB upsert)** stores `tags_csv` in metadata so future queries can filter by confirmed categories.

### State machine extension on `CatalogEntry`

```
PENDING_TAG_REVIEW  →  TAG_CONFIRMED  →  PROCESSING  →  DONE
```

### ChromaDB metadata schema change

Before:
```python
metadatas=[{"integration_id": ..., "type": ...}]
```

After:
```python
metadatas=[{"integration_id": ..., "type": ..., "tags_csv": "Sync,Enrichment"}]
```

---

## Alternatives Considered

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Similarity-only (status quo)** | Zero new UI/backend code | Poor relevance for multi-category repos; timeout risk | Rejected |
| **Post-generation tagging** | No blocking gate | Tags not available at RAG query time; no filtering benefit | Rejected |
| **Auto-tag from LLM (no HITL)** | Fully automated | LLM tags are unreliable; violates Responsible AI §2 (human-in-the-loop) | Rejected |
| **HITL gate (this ADR)** | Accurate tags; human-validated; filters RAG effectively | Adds one manual step before generation | **Accepted** |

---

## Consequences

### Positive
- RAG context is scoped to matching categories → fewer irrelevant examples → shorter prompts → lower timeout risk
- `rag_source` log label (`tag_filtered | similarity_fallback | none`) provides observability into RAG path taken
- Human validates all tags before generation → aligns with CLAUDE.md §2 Responsible AI principles
- `tags_csv` metadata enables future multi-tag filtering as ChromaDB corpus grows

### Negative / Trade-offs
- Upload-to-generation workflow now requires an explicit confirm-tags step
- `_suggest_tags_via_llm` adds a round-trip to Ollama per integration on the suggest-tags path (mitigated by graceful fallback to `[]`)
- ChromaDB `$contains` operator is string-match only; multi-tag intersection requires iterating tags (deferred to future ADR)

---

## Validation Plan

- 109 unit tests pass (50 original + 59 new tag-related tests)
- New test files: `test_schemas.py`, `test_tag_suggestion.py`, `test_upload_creates_catalog.py`, `test_suggest_tags_endpoint.py`, `test_confirm_tags.py`, `test_trigger_gate.py`, `test_rag_filtering.py`
- All tests run from: `cd services/integration-agent && python -m pytest tests/ -v`

---

## Rollback Strategy

Set environment variable `OLLAMA_RAG_TAG_FILTER_ENABLED=false` in `.env` (or compose override) to skip tag-filtered query and fall back to similarity-only. The `_query_rag_with_tags` function already implements this path as its `similarity_fallback` branch — no code changes needed for rollback.

Alternatively, revert to the previous `run_agentic_rag_flow` (pre-ADR-019) via `git revert` of commit range; entries created by the new upload endpoint remain compatible as they include all original fields.
