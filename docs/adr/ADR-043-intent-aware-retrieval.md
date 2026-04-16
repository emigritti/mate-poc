# ADR-043 — Intent-Aware Retrieval, Tag Fix, and Query Perspective Extension

**Status:** Accepted
**Date:** 2026-04-16
**Author:** Integration Mate Team
**Related:** ADR-027 (BM25 Hybrid Retrieval), ADR-028 (Multi-Query Expansion 2+2),
             ADR-019 (tag-based result preference R12)

---

## Context

Three independent deficiencies were identified in `services/retriever.py` by SME review:

**Problem 1 — `_tags_match_meta()` false positives.**
`_tags_match_meta()` used a raw substring scan (`any(t in tags_str for t in tags)`).
Short tags such as `"PL"` incorrectly matched `"PLM,SAP"`, and `"SA"` matched `"SAP"`.
This made tag-based retrieval unreliable as the KB grew to include more overlapping tokens.
Additionally, the old implementation treated an empty `tags_csv` field as a match for any
requested tag (`"" in ""` evaluates to `True` in Python), masking missing metadata.

**Problem 2 — Query expansion perspectives are hardcoded.**
`_expand_queries()` always requested "technical systems integration" and "business process"
perspectives from the LLM, regardless of the retrieval context. A data-mapping query and an
error-handling query received identical LLM prompts, missing retrieval recall for specialized
intents. The SME analysis specifically called out "data/domain" and "exception/edge-case"
perspectives as commonly undercovered.

**Problem 3 — TF-IDF re-ranking is intent-blind.**
`_tfidf_rerank()` scored chunks against the raw query string with no domain vocabulary
augmentation. A chunk rich in intent-relevant terminology (e.g., "retry", "dead-letter",
"compensation" for an error-handling section) could rank below a structurally irrelevant
chunk with a higher ensemble score if the raw query lacked those specific terms.

**Additional constraint:**
`chunk_type` and `section_header` — available in `DoclingChunk` during ingestion — are NOT
propagated to the integration-agent ChromaDB metadata. Intent-based boosting therefore cannot
rely on metadata fields and must operate at text level only.

---

## Decision

### 1. Fix `_tags_match_meta()` — whole-token set comparison

Replace `any(t in tags_str for t in tags)` with comma-split, `.strip().lower()` set
intersection:

```python
stored_tokens = {t.strip().lower() for t in tags_str.split(",") if t.strip()}
query_tokens  = {t.strip().lower() for t in tags   if t.strip()}
return bool(stored_tokens & query_tokens)
```

No ChromaDB metadata migration required — existing `tags_csv` values are already
comma-separated. The fix propagates automatically to all two call sites:
`_query_chroma()` and `retrieve_summaries()`.

**Behavior change on edge case:** `_tags_match_meta({"tags_csv": ""}, ["Sync"])` now
returns `False` (previously `True` via the `"" in ""` Python quirk). This is the correct
behavior — an empty CSV should never be treated as matching any requested tag.

### 2. Add `_INTENT_PERSPECTIVES` — selectable LLM query perspectives

Two module-level constants control which perspective pair is sent to the LLM:

- `_DEFAULT_PERSPECTIVES` — replicates the pre-ADR-043 strings (`"technical systems
  integration"` + `"business process"`) for exact backward compatibility.
- `_INTENT_PERSPECTIVES` — maps each of 5 intent values to a domain-specific pair.

`_expand_queries()` gains `intent: str = ""`. The dict lookup
`_INTENT_PERSPECTIVES.get(intent, _DEFAULT_PERSPECTIVES)` handles all cases:
- `intent=""` (default) → falls back to `_DEFAULT_PERSPECTIVES` → unchanged behavior
- `intent="data_mapping"` → "field-level data transformation" + "data domain model"
- Unknown intent string → falls back to `_DEFAULT_PERSPECTIVES`

The 2+2 query budget (ADR-028 R8) is preserved — the LLM prompt still requests exactly
2 variants.

### 3. Add `_INTENT_VOCABULARY` — TF-IDF query augmentation

A module-level dict maps each intent to a string of domain-specific keywords.
`_tfidf_rerank()` gains `intent: str = ""`. When intent is set:
```python
augmented_query = f"{query} {_INTENT_VOCABULARY[intent]}".strip()
```
The augmented query is passed to `TfidfVectorizer` instead of the raw query, biasing
cosine similarity toward domain-relevant terminology. No TF-IDF formula or weight changes.
Unknown/empty intent → no augmentation, neutral behavior.

### 4. Add `intent: str = ""` keyword-only parameter to `retrieve()`

`intent` is added after the `*` sentinel in `retrieve()`, making it keyword-only.
This ensures the two existing call sites in `agent_service.py` (which use positional +
keyword arguments but do not pass `intent`) compile cleanly without modification.
The parameter is propagated internally to `_expand_queries()` and `_tfidf_rerank()`.

---

## Intent Values

| `intent` | LLM Perspectives | TF-IDF Vocabulary Focus |
|----------|-----------------|------------------------|
| `""` (default) | technical systems integration + business process | none (neutral) |
| `"overview"` | high-level architecture + business capability | scope, flow, component |
| `"business_rules"` | rule validation + governance | constraint, policy, approval |
| `"data_mapping"` | field transformation + data domain | mapping, schema, canonical |
| `"errors"` | error handling + exception edge case | retry, fallback, dead-letter |
| `"architecture"` | middleware pattern + non-functional | API, protocol, SLA |

---

## New Public API (`services/retriever.py`)

| Symbol | Type | Change |
|--------|------|--------|
| `_DEFAULT_PERSPECTIVES` | `list[str]` | New constant |
| `_INTENT_PERSPECTIVES` | `dict[str, list[str]]` | New constant |
| `_INTENT_VOCABULARY` | `dict[str, str]` | New constant |
| `retrieve(..., *, intent: str = "")` | Method | New keyword-only param |
| `_expand_queries(..., intent: str = "")` | Method | New positional param |
| `_tfidf_rerank(..., intent: str = "")` | Method | New positional param |
| `_tags_match_meta()` | Method | Bug fix — whole-token match |

---

## Modified Files

| File | Change |
|------|--------|
| `services/retriever.py` | All three enhancements + docstring updates |
| `tests/test_retriever.py` | +13 new tests (total: 24 → 37) |

---

## Alternatives Considered

### Alt A — Metadata-based intent filter (chunk_type in ChromaDB)

Index `chunk_type` ("text" / "table" / "figure") into ChromaDB metadata and filter/boost
by chunk type per intent (e.g., `intent="data_mapping"` → prefer `chunk_type="table"`).

**Rejected:** `chunk_type` is produced by Docling ingestion but NOT propagated to the
integration-agent ChromaDB metadata. Implementing this would require:
1. A ChromaDB metadata schema migration for all existing documents.
2. Changing the ingestion path to include `chunk_type` in `to_chroma_metadata()`.
Reserved for a future phase once the ingestion pipeline is aligned.

### Alt B — Separate retriever class per intent

Create `DataMappingRetriever`, `ErrorRetriever`, etc., each with dedicated parameters.

**Rejected:** Violates CLAUDE.md §8 (no speculative abstractions). Five parallel classes
for 5 intents would triple the retriever codebase with no behavioral advantage over the
single-class design with an `intent` parameter.

### Alt C — Increase LLM variant budget to 4 (2+4 total queries)

Request 4 LLM variants to cover all perspective types simultaneously.

**Rejected:** Violates ADR-028 R8 (2+2 query budget). This would increase Ollama LLM
calls per retrieval from 1 to 2 and total query variants from 4 to 6, increasing latency
without a proven recall gain. The intent-selectable 2-perspective approach achieves domain
focus without budget increase.

### Alt D — Section-level intent injection from `agent_service.py`

Pass a different `intent` value for each of the 16 template sections in
`generate_integration_doc()` — e.g., `intent="data_mapping"` for the data mapping section.

**Deferred:** This requires section-level retrieval (16 separate `retrieve()` calls per
document), which increases latency from ~90 s to ~25 min on a CPU-only instance (same
constraint documented in ADR-042). The `intent` parameter is introduced here as an
extension point; section-level wiring is a future enhancement once model speed improves.

---

## Consequences

**Positive:**
- `_tags_match_meta()` false positives eliminated — tag filtering is now reliable as the KB grows.
- Intent-aware LLM perspectives improve recall for specialized query types (data mapping,
  error handling) without increasing the query budget.
- Intent vocabulary boost allows TF-IDF re-ranking to surface domain-relevant chunks even
  when the raw query uses generic language ("handle failures" → boosts "retry/fallback" chunks).
- `intent` is a keyword-only parameter with a `""` default — zero impact on existing callers.
- All three enhancements are independently testable and independently deployable.

**Negative / Trade-offs:**
- `_INTENT_VOCABULARY` adds ~350 chars to the TF-IDF query string when intent is set,
  consuming roughly 70–80 additional TF-IDF vocabulary slots (negligible vs `max_features=5000`).
- The 5 intent values are a curated enum. Adding a new intent requires updating three
  constants (`_INTENT_PERSPECTIVES`, `_INTENT_VOCABULARY`) and the docstring of `retrieve()`.
- Intent is currently not wired in `agent_service.py` — callers receive `""` by default.
  The improvement is available but not yet active. Wiring per-section intent is deferred
  (see Alt D above).

---

## Security Considerations

- No new external calls; no new data sent to external services.
- The tag normalization fix reduces the attack surface from KB pollution via specially crafted
  tag strings designed to produce false-positive matches (e.g., tags containing substrings
  of legitimate tags to hijack retrieval results).
- `intent` is an internal parameter; it is never directly populated from user input in the
  current wiring. If future callers expose `intent` to end users, it must be validated against
  the known intent enum before passing to `retrieve()`.

---

## Validation Plan

| Test class/function | Coverage |
|--------------------|---------|
| `test_tags_match_meta_no_substring_false_positive` | "PL" no longer matches "PLM,SAP" |
| `test_tags_match_meta_partial_prefix_no_match` | "SA" no longer matches "SAP" |
| `test_tags_match_meta_exact_token_still_matches` | "SAP" still matches "PLM,SAP" (regression) |
| `test_tags_match_meta_case_insensitive` | case-insensitive token match |
| `test_tags_match_meta_empty_tags_csv_returns_false` | empty CSV → False (not True) |
| `test_expand_queries_uses_intent_perspectives_data_mapping` | LLM prompt contains field-mapping perspectives |
| `test_expand_queries_unknown_intent_falls_back_to_default_perspectives` | unknown intent → default |
| `test_expand_queries_empty_intent_uses_default_perspectives` | empty intent → backward compat |
| `test_tfidf_rerank_intent_vocabulary_boosts_relevant_chunk` | vocabulary boost changes ranking |
| `test_tfidf_rerank_no_intent_unchanged_behavior` | empty intent → original behavior |
| `test_tfidf_rerank_unknown_intent_does_not_crash` | unknown intent → no exception |
| `test_retrieve_accepts_intent_keyword_argument` | `intent=` keyword accepted |
| `test_retrieve_with_no_intent_matches_original_behavior` | no-intent call unchanged |

Total new tests: 13 (added to `tests/test_retriever.py`).
All 24 pre-existing tests pass without modification.

---

## Rollback Strategy

1. **Instant rollback (no code change):** The `intent` parameter defaults to `""`, which
   restores pre-ADR-043 behavior for all three enhancements simultaneously. No config changes
   needed.

2. **Code rollback:** Revert `services/retriever.py` to the pre-ADR-043 commit.
   No schema or DB migrations required. `agent_service.py` is unchanged throughout — it
   requires no rollback.
