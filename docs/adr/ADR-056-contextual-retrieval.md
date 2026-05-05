# ADR-056 — Contextual Retrieval: Situating Annotations at Ingestion (ADR-X4)

**Status:** Accepted
**Date:** 2026-05-05
**Authors:** Emiliano Gritti (AI-assisted, Claude Code)
**Requires:** ADR-053 (Docling structured chunks), ADR-054 (8k-context embedder)
**Pattern source:** Anthropic, "Contextual Retrieval", September 2024

---

## Context

Semantic chunking (ADR-030) splits documents into coherent units, but each chunk loses its document-level context at embedding time. A chunk containing "The mapping is uppercase" carries no signal about *which* field, *which* system, or *which* document it belongs to — until a reader traces it back to the parent document.

Anthropic's Contextual Retrieval pattern addresses this by prepending a short LLM-generated "situating annotation" (50–100 tokens) to each chunk **before** embedding. The annotation answers: *"Where in the document does this chunk sit, and what is it about?"*

Anthropic reports:
- **+35% recall@20** with embeddings only
- **+49% recall@20** with BM25 + reranker (i.e. the post-ADR-055 stack)

ADR-054 (`nomic-embed-text-v1.5`, 8k context) is a hard prerequisite: the annotated chunk (original text + 50–100 token annotation) regularly exceeds 256 tokens, which would overflow `all-MiniLM-L6-v2`.

---

## Decision

### Annotation format

```xml
<situating>
This chunk is from "Field Mapping — PIM to PLM" of "PLM Integration
Best-Practice v3.2". It defines the canonical mapping for product_status
across both systems, and applies only to SKUs in "release" lifecycle stage.
</situating>

<original>
| pim_field       | plm_field            | transform  |
| product_status  | item.lifecycle_state | uppercase  |
...
</original>
```

XML tags structure the text unambiguously for both the embedder and the BM25 index.

### Provider selection

| Provider | When | Cost | Quality |
|---|---|---|---|
| Claude Haiku (default) | `ANTHROPIC_API_KEY` present | ~$0.05/doc with caching | Highest |
| Ollama `llama3.1:8b` (fallback) | No API key | $0 | Good |
| Passthrough | `CONTEXTUAL_RETRIEVAL_ENABLED=false` | $0 | Baseline |

**Prompt caching** is mandatory when using Claude: both the system prompt and the full document text are cached as `ephemeral` blocks (5-min TTL). Only the per-chunk user message varies across the loop.

Cost example — 30k-token KB document, 50 chunks:
- Without caching: 50 × 30k = 1.5 M input tokens → ~$1.20 (Haiku 4.5)
- **With caching**: 30k cached once + 50 × ~200 tokens → **~$0.05/doc** (95% reduction)

### Pipeline position

```
parse_with_docling()       →   DoclingChunks
  ↓
add_context_to_chunks()    →   annotated DoclingChunks   ← NEW (ADR-X4)
  ↓
OllamaEmbeddingFunction    →   768-dim vectors
  ↓
ChromaDB upsert
```

Applied at both ingestion entry points:
- `services/integration-agent/routers/kb.py` — document upload
- `services/ingestion-platform/routers/ingest.py` — OpenAPI and HTML ingestion

### New config vars

| Env var | Default | Effect |
|---|---|---|
| `CONTEXTUAL_RETRIEVAL_ENABLED` | `true` (`false` in tests) | Master switch |
| `CONTEXTUAL_PROVIDER` | `claude` | `claude` → auto-fallback to `ollama` if no key |
| `CONTEXTUAL_MODEL_CLAUDE` | `claude-haiku-4-5-20251001` | Claude model for annotation |
| `CONTEXTUAL_MODEL_OLLAMA` | `llama3.1:8b` | Ollama fallback model |
| `CONTEXTUAL_MAX_TOKENS` | `120` | Max annotation length |

### Files changed

| File | Change |
|---|---|
| `services/integration-agent/services/contextual_retrieval_service.py` | New module: `add_context_to_chunks(doc_text, chunks) → chunks` |
| `services/integration-agent/routers/kb.py` | Call `add_context_to_chunks()` between Docling parse and ChromaDB upsert |
| `services/integration-agent/config.py` | 5 new vars above |
| `services/ingestion-platform/services/contextual_retrieval_service.py` | Mirror of integration-agent, adapted for `CanonicalChunk` (Pydantic `model_copy`) |
| `services/ingestion-platform/routers/ingest.py` | Same wiring in `_run_openapi_ingestion` and `_run_html_ingestion` |
| `services/ingestion-platform/config.py` | Mirror of integration-agent config vars |

---

## Consequences

### Positive
- Expected +35–49% recall@20 improvement (Anthropic benchmark)
- Works offline (Ollama fallback) — no mandatory Claude dependency
- Prompt caching reduces cost to ~$0.05/doc — commercially negligible
- Graceful degradation: individual chunk failure → original chunk preserved
- Applied consistently across both ingestion pipelines (KB upload + ingestion-platform)

### Negative / Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Documents > 100k tokens exceed Haiku context | Medium | Split at macro-section level via `semantic_chunk()` recursively |
| Ephemeral cache expires (5-min TTL) → cost spike on slow ingestion | Low | Process chunks sequentially per document; avoid parallel doc ingestion |
| Without Claude key, Ollama fallback is lower quality | Low | Documented in HOW-TO; Ollama still meaningfully better than no annotation |
| **Compliance §1 (HIGH)**: chunk text sent to Claude API | **High** | Opt-in via `ANTHROPIC_API_KEY`; runtime warning log on every call; disabled in tests; HOW-TO explicit disclaimer — "use only with synthetic / public / Accenture-Internal data" |
| KB re-ingestion required (chunk text changes) | Medium (expected) | ChromaDB volume snapshot before deploy; full re-ingest documented in HOW-TO |

---

## Validation plan

- Unit: `test_contextual_retrieval_service.py::test_add_context_uses_claude_when_key_present`
- Unit: `test_contextual_retrieval_service.py::test_falls_back_to_ollama_when_claude_unavailable`
- Unit: `test_contextual_retrieval_service.py::test_disabled_via_env_returns_chunks_unchanged`
- Unit: assert `cache_control` present in every Claude call (caching mandatory, not optional)
- Unit (ingestion-platform): 6 tests covering `CanonicalChunk` annotation, graceful failure, metadata preservation (implemented, commit `8b81b19`)
- Eval harness: `recall@20` delta vs baseline — primary metric
- Full suite regression: `pytest tests/ -q`

---

## Rollback

```bash
# Instant rollback — no redeploy needed
# Next ingestion run will skip annotations; existing chunks unchanged
export CONTEXTUAL_RETRIEVAL_ENABLED=false
```

For full revert (remove annotations from existing chunks): restore ChromaDB volume snapshot from before merge + re-ingest.
Git tag `pre-adr-x4-merge` on `main` before merge.

---

## Compliance (CLAUDE.md)

- **§1 (Data boundary)**: chunk text reaches Claude API only when `ANTHROPIC_API_KEY` is explicitly provided. Warning emitted on every call: `[Ctx-Retrieval] sending chunk to Claude API — ensure only synthetic/public/internal data`. Feature disabled in CI tests.
- **§10 (Secure coding)**: Claude output wrapped in `<situating>` XML tags before storage; treated as untrusted; does not affect downstream logic, only embedding input
- **§11 (AI/Agentic Security)**: prompt injection surface mitigated by XML tag structure (`<document>`, `<chunk>`) per Anthropic guidance; LLM output is never executed
- **§2 (Responsible AI)**: annotation quality is a soft signal — retrieval still relies on dense + BM25 + cross-encoder; annotation failure degrades gracefully to original chunk
