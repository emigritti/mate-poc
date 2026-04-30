# RAG Pipeline Modernization — Design Document

- **Date:** 2026-04-30
- **Author:** Emiliano Gritti (with Claude as AI assistant)
- **Status:** Approved (pending implementation)
- **Related ADRs:** preceded by ADR-027/028/029/030/031/032/043/048/052 — all preserved
- **Approach:** γ ("Pragmatic Hybrid") — Phased multi-ADR with eval harness gating

---

## 1. Executive Summary

Modernize the integration-agent RAG pipeline (parsing + retrieval) via four sequential, independent ADRs. Each ADR is independently testable, rollback-able, and gated by a lightweight evaluation harness that produces empirical recall@k / MRR / NDCG / faithfulness metrics. The plan respects:

- Runtime constraint **B**: Ollama-local default + Claude API as opt-in premium (no GPU on EC2)
- KB recreation accepted (no zero-downtime requirement)
- CLAUDE.md compliance (Security > Architecture > Testability > Maintainability)

**Total effort:** ~3.5–4 sprints with disciplined ADR/test/eval cadence.

---

## 2. Why now (motivation)

Current pipeline weaknesses identified during code review:

1. **Embedder** — ChromaDB default `all-MiniLM-L6-v2` (2020, 384d, **256-token context**). Cannot fit Docling section chunks; English-leaning.
2. **Reranker** — TF-IDF cosine (`sklearn.TfidfVectorizer`) is keyword-overlap, not semantic. Cross-encoders are 1–2 orders of magnitude better on rerank benchmarks.
3. **Vision** — `llava:7b` is a generalist VLM (~14 GB RAM, 25–40 s/figure on CPU). Modern document-tuned small VLMs (Granite-Vision-3.2-2B, SmolVLM) are 3–5× faster and significantly stronger on tables/charts.
4. **PDF fallback** — text-only PyMuPDF discards layout. Modern parsers produce markdown directly suitable for LLMs.
5. **Ensemble fusion** — score-weighted merge requires per-source normalization and is fragile to scale heterogeneity. Reciprocal Rank Fusion (RRF) is the de-facto standard on BEIR/MTEB and needs no tuning.
6. **Chunking** — `RecursiveCharacterTextSplitter` is structurally aware but loses *document-level* context. Anthropic's Contextual Retrieval (Sept 2024) reports +35% recall@20 (embeddings only) and +49% recall@20 (with BM25 + reranker).

---

## 3. Target Architecture (end-state)

```
              ┌─────────────────────────────────────────────────────────┐
              │                       INGESTION                         │
              │  Upload (PDF/DOCX/XLSX/PPTX/MD/IMG)                     │
              │     │                                                   │
              │     ▼                                                   │
              │  Docling 2.5 + Granite-Vision/SmolVLM    ← ADR-X1       │
              │  (text + table + figure DoclingChunks)                  │
              │     │                                                   │
              │     ▼                                                   │
              │  semantic_chunk()  +  Contextual Retrieval ← ADR-X4     │
              │  (LLM prepends ~50–100 tokens of context to each chunk) │
              │     │                                                   │
              │     ▼                                                   │
              │  nomic-embed-text-v1.5 (Ollama)          ← ADR-X2       │
              │     │                                                   │
              │     ▼                                                   │
              │  ChromaDB kb_collection + BM25Plus index                │
              └─────────────────────────────────────────────────────────┘

              ┌─────────────────────────────────────────────────────────┐
              │                       RETRIEVAL                         │
              │  Query (intent-aware, 2 template + 2 LLM variants)      │
              │     │                                                   │
              │     ▼                                                   │
              │  ChromaDB dense + BM25Plus  (parallel, top-N each)      │
              │     │                                                   │
              │     ▼                                                   │
              │  Reciprocal Rank Fusion (RRF)            ← ADR-X3       │
              │     │                                                   │
              │     ▼                                                   │
              │  Cross-encoder bge-reranker-base (top-30 → top-10)      │
              │     │                                                   │
              │     ▼                                                   │
              │  [opt] Claude Haiku LLM-judge (top-10 → top-K final)    │
              │     │                                                   │
              │     ▼                                                   │
              │  Semantic v2 bonus (ADR-048) + Wiki Graph (ADR-052)     │
              │  (preserved unchanged)                                  │
              └─────────────────────────────────────────────────────────┘
```

### Components NOT changed (out of scope)

- ChromaDB 0.5.3 (no vector store migration)
- BM25Plus (sparse retrieval kept)
- Multi-query expansion 2+2 (ADR-028)
- Intent-aware vocabulary boost (ADR-043)
- Semantic v2 metadata (ADR-048)
- Wiki Graph RAG (ADR-052)
- RAPTOR-lite summaries (ADR-032)
- Doc generation prompt builder, output guard
- Claude API enrichment for "n/a" sections (ADR-037)

---

## 4. Sequencing

| # | ADR | Depends on | Re-ingest KB? | Effort |
|---|-----|------------|---------------|--------|
| 0 | **Eval harness** (prerequisite) | — | no | ½ day |
| 1 | **ADR-X1 Parser** (Docling 2.5 + VLM CPU) | — | yes (recommended) | ~1 sprint |
| 2 | **ADR-X2 Embedder** (nomic-embed-text-v1.5) | independent of X1 | yes (mandatory — embedding space changes) | ~½ sprint |
| 3 | **ADR-X3 Reranker + RRF** (bge-reranker-base + Claude opt) | benefits from X2 | no | ~½–1 sprint |
| 4 | **ADR-X4 Contextual Retrieval** | requires X1 (structured chunks) and X2 (8k context embedder) | yes | ~1 sprint |

**Merge order:** Eval harness → X1 → X2 → X3 → X4. X3 may swap with X4 if Claude API issues delay X4.

---

## 5. ADR-X1 — Parser (Docling 2.5 + Granite-Vision)

### Files touched

- `services/integration-agent/document_parser.py` — upgrade `parse_with_docling()`; image hand-off to Docling-native VLM pipeline
- `services/integration-agent/services/vision_service.py` — simplified to compatibility wrapper for standalone PNG/JPG uploads only
- `services/integration-agent/requirements.txt` — `docling>=2.5,<3.0` with `[vlm]` extras
- `services/integration-agent/config.py` — new `vlm_model_name` (default `granite3.2-vision:2b`), `vlm_fallback_model_name` (default `llava:7b`)

### VLM choice

**Default:** `granite3.2-vision:2b` (IBM, Apache-2.0). Tuned for enterprise documents (tables, diagrams, charts). 2B params, ~5 GB RAM, 8–15 s/figure CPU.
**Fallback (configurable):** `llava:7b` — current model, kept for env-var-driven fallback chain when Granite-Vision fails or is unavailable.

Fallback logic:
1. Primary: `vlm_model_name` (Granite-Vision)
2. On error / on `VLM_FORCE_FALLBACK=true` env: `vlm_fallback_model_name` (LLaVA)
3. On both failures: returns `"[FIGURE: no caption available]"` placeholder (current behavior preserved)

### Test plan

- Unit: `test_document_parser.py::test_parse_with_docling_uses_vlm` (mock Docling, verify VLM model name passed)
- Unit: `test_vision_service.py::test_falls_back_to_llava_on_granite_error`
- Eval: caption-quality delta on 5 figure-heavy PDFs (Claude judge opt-in)

### Rollback

- `VLM_MODEL_NAME=llava:7b` runtime switch
- Branch tag `pre-adr-x1` on `main`

### Risks

- **R1**: Granite-Vision availability on Ollama for dev (Mac/Windows) — verify in 30-min spike before merge.
- **R2**: KB re-ingestion lengthens setup — documented in `HOW-TO/`.

---

## 6. ADR-X2 — Embedder (`nomic-embed-text-v1.5`)

### Files touched

- `services/integration-agent/db.py` — new `OllamaEmbeddingFunction` (ChromaDB-compatible), replaces default
- `services/integration-agent/config.py` — `embedder_model_name` (default `nomic-embed-text:v1.5`), `embedder_provider` (default `ollama`)
- `services/integration-agent/services/retriever.py` — unchanged (score formula `1.0/(1.0+dist)` is metric-agnostic)
- `services/ingestion-platform/...` — same `EmbeddingFunction` change for collection-coherence

### Why nomic-embed-text-v1.5

| Embedder | Dim | Context | RAM CPU | Latency CPU (1 chunk) | Note |
|----------|-----|---------|---------|----------------------|------|
| all-MiniLM-L6-v2 (current) | 384 | **256 tokens** | ~100 MB | ~10 ms | 2020, English-only, tiny window |
| **nomic-embed-text-v1.5** ⭐ | 768 | **8192 tokens** | ~500 MB | ~80–150 ms | 2024, multilingual, top-CPU |
| mxbai-embed-large | 1024 | 512 | ~700 MB | ~150 ms | English |
| bge-m3 | 1024 | 8192 | ~1.5 GB | ~400 ms | SOTA but heavy CPU |

Decisive factors: 8k token context (covers full DoclingChunks + post-X4 contextual annotations), multilingual (IT + EN KB content), already on Ollama, Matryoshka representation learning for future dimension truncation.

### Critical implementation detail (R2 below)

`nomic-embed-text` requires task-specific prefixes:
- Ingestion: `"search_document: " + chunk_text`
- Retrieval: `"search_query: " + query_text`

`OllamaEmbeddingFunction` exposes a `mode` parameter (`"document"` | `"query"`) — ChromaDB collections use the `document` mode for `add()`, `query` mode for `query()`. This requires either two function instances or a single instance that switches mode based on call site.

### Test plan

- Unit: `tests/test_embedder.py` — mock httpx, verify model name + batch behavior + dim coherence (768) + correct prefix injection
- Integration: smoke test that the collection is created with the new embedder and an end-to-end query returns chunks
- Eval harness: **recall@5** and **MRR** delta — primary metric

### Rollback

- `EMBEDDER_MODEL_NAME=all-MiniLM-L6-v2` reverts to ChromaDB default
- ChromaDB volume snapshot before merge
- If p95 latency on EC2 > 250 ms/chunk → degraded path with `mxbai-embed-large` or revert

### Risks

- **R1 (low)**: Ingestion latency increases ~10× per chunk. For ~5k-chunk KB → ~10 min full ingestion (acceptable, one-shot).
- **R2 (medium)**: `nomic-embed-text` task prefix requirement (`search_document:` / `search_query:`). Easy to forget — explicit in `OllamaEmbeddingFunction` and tested.
- **R3 (low)**: Old/new collections incompatible — recreation mandatory (already accepted).

---

## 7. ADR-X3 — Reranker + RRF

### Files touched

- `services/integration-agent/services/retriever.py`:
  - `_ensemble_merge()` → replaced by `_rrf_merge()`
  - `_tfidf_rerank()` → deprecated; replaced by `_cross_encoder_rerank()`
  - New `_llm_judge_rerank()` (Claude Haiku) as opt-in final gate
- `services/integration-agent/services/reranker_service.py` — **new module** wrapping sentence-transformers `CrossEncoder`
- `services/integration-agent/config.py` — new vars:
  - `reranker_enabled` (default `True`)
  - `reranker_model_name` (default `BAAI/bge-reranker-base`)
  - `reranker_top_n` (default `30`)
  - `llm_judge_enabled` (default `False` — opt-in)
  - `llm_judge_top_k` (default `10`)
  - `rag_use_rrf` (default `True`; set to `False` to keep weighted-merge)
- `services/integration-agent/requirements.txt` — `sentence-transformers>=3.0,<4.0`

### RRF rationale

Current `_ensemble_merge` normalizes ChromaDB and BM25 scores separately (max-norm), then weights 0.6/0.4. This flattens signal when one source is uniform and the other is sharp.

**RRF** fuses by rank, not score:
```
RRF_score(d) = Σ_i  1 / (k + rank_i(d))     k = 60 (standard)
```
- Robust to heterogeneous score scales (future-proof for ColBERT, SPLADE, etc.)
- No weight tuning required
- ~20 LOC implementation, no new deps

### Cross-encoder choice

| Reranker | Param | RAM | CPU latency (30 pairs) |
|----------|-------|-----|------------------------|
| TF-IDF cosine (current) | — | — | <50 ms |
| **bge-reranker-base** ⭐ | 278M | ~600 MB | 800–1500 ms |
| bge-reranker-v2-m3 | 568M | ~1.2 GB | 2–4 s |
| mxbai-rerank-base | 184M | ~450 MB | 600–900 ms |

`bge-reranker-base` is the CPU sweet spot, multilingual, sub-2 s on 30 pairs.

### Pipeline

`RRF top-30 → cross-encoder → top-10 → (opt) Claude judge → top-K`

### Claude Haiku LLM-judge (opt-in)

When `llm_judge_enabled=true` AND `ANTHROPIC_API_KEY` present:
- Input: top-10 from cross-encoder
- Prompt: "Score chunk relevance to query (intent-aware), return JSON `[{idx, score}]`"
- Model: `claude-haiku-4-5` (~500 ms / 10 chunks)
- **Prompt caching mandatory** (system prompt + chunks → 5-min ephemeral cache → 90% cost reduction; reuses ADR-037 pattern)

### Test plan

- Unit:
  - `test_reranker_service.py::test_cross_encoder_returns_expected_order` (mock `CrossEncoder.predict`)
  - `test_retriever.py::test_rrf_merge_combines_ranks_not_scores` (regression vs `_ensemble_merge`)
  - `test_retriever.py::test_llm_judge_disabled_when_key_absent` (graceful fallback)
- Eval harness: **MRR delta** + **NDCG@5** — primary metrics
- Integration: smoke test with/without Claude key

### Rollback

- `RERANKER_ENABLED=false` → restores TF-IDF cosine
- `RAG_USE_RRF=false` → restores weighted-merge
- Cross-encoder lazy-loaded on first call → no startup cost when disabled

### Risks

- **R1 (medium)**: sentence-transformers downloads ~600 MB on first startup. Docker image must pre-pull (`HF_HOME` cached layer) to avoid cold-start on first query.
- **R2 (low)**: cross-encoder p95 over 30 pairs may breach doc-generate SLA → reduce top-N to 20 or use `mxbai-rerank-base`.
- **R3 (low)**: Claude judge without prompt caching = 5× cost. Mitigated by caching design (ADR-037 pattern).

---

## 8. ADR-X4 — Contextual Retrieval

### Pattern (Anthropic, Sept 2024)

For each chunk, before embedding, an LLM receives the full document + the specific chunk and produces a 50–100 token "situating annotation" prepended to the chunk:

```
<situating>
This chunk is from "Field Mapping — PIM to PLM" of "PLM Integration
Best-Practice v3.2". It defines the canonical mapping for product_status
across both systems, applies only to SKUs in "release" lifecycle stage.
</situating>

<original_chunk>
| pim_field        | plm_field             | transform   |
| product_status   | item.lifecycle_state  | uppercase   |
...
```

Anthropic reports **+35% recall@20** with embeddings only, **+49% recall@20** with BM25 + reranker (i.e. our post-X3 stack).

### Files touched

- `services/integration-agent/services/contextual_retrieval_service.py` — **new module**
- `services/integration-agent/routers/kb.py` — invoke `add_context_to_chunks()` before embedding
- `services/ingestion-platform/...` — same integration in ingestion flow
- `services/integration-agent/config.py` — new vars:
  - `contextual_retrieval_enabled` (default `True`)
  - `contextual_provider` (`claude` | `ollama`, default `claude` with auto-fallback)
  - `contextual_model_claude` (default `claude-haiku-4-5`)
  - `contextual_model_ollama` (default `llama3.1:8b`)

### Pseudocode (cost-aware)

```python
async def add_context_to_chunks(
    doc_text: str,
    chunks: list[DoclingChunk],
) -> list[DoclingChunk]:
    if not settings.contextual_retrieval_enabled:
        return chunks
    if claude_available():
        return await _contextualize_with_claude(doc_text, chunks)
    return await _contextualize_with_ollama(doc_text, chunks)
```

**Claude provider — aggressive prompt caching:**

```python
await client.messages.create(
    model="claude-haiku-4-5",
    system=[
        {"type": "text", "text": SITUATING_PROMPT,
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"<document>{doc_text}</document>",
         "cache_control": {"type": "ephemeral"}},
    ],
    messages=[{"role": "user", "content": f"<chunk>{chunk.text}</chunk>"}],
    max_tokens=120,
)
```

### Cost

Typical 30k-token KB doc, 50 chunks.
- Without caching: 50 × 30k = 1.5 M input tokens → ~$1.20 (Haiku 4.5)
- **With caching:** 30k cached + 50 × ~200 token (chunk + output) → **~$0.05/doc** (95% reduction)

### Test plan

- Unit:
  - `test_contextual_retrieval_service.py::test_add_context_uses_claude_when_key_present`
  - `test_contextual_retrieval_service.py::test_falls_back_to_ollama_when_claude_unavailable`
  - `test_contextual_retrieval_service.py::test_disabled_via_env_returns_chunks_unchanged`
  - **Explicit assertion**: `cache_control` present in every Claude call (caching mandatory)
- Integration: end-to-end ingestion with contextual retrieval on/off
- Eval harness: **recall@20 delta** vs baseline — primary expected metric

### Rollback

- `CONTEXTUAL_RETRIEVAL_ENABLED=false` → next ingestion skips the step
- ChromaDB pre-X4 volume snapshot

### Risks

- **R1 (medium)**: docs > 100k tokens exceed Haiku context. Mitigation: split doc at macro-section level using `semantic_chunk()` recursively.
- **R2 (low)**: ephemeral caching expires after 5 min — keep ingestion sequential per doc, not parallel across docs.
- **R3 (low)**: Without Claude key, Ollama fallback is degraded but functional. Documented in `HOW-TO/`.
- **R4 (compliance, HIGH)**: Doc passed to Claude API traverses public network → CLAUDE.md §1 forbids client/sensitive data on Claude → **opt-in required + runtime banner + explicit HOW-TO disclaimer ("use only with synthetic/internal/Accenture-classified data")**.

---

## 9. Eval Harness (prerequisite — merged before X1)

### Layout

```
tests/eval/
  ├── golden_questions.yaml          # 30–50 Integration-Spec queries with expected answers
  ├── run_rag_eval.py                # CLI runner — produces markdown report
  ├── metrics/
  │   ├── retrieval.py               # recall@k, MRR, NDCG@k
  │   └── faithfulness.py            # LLM-as-judge faithfulness (Claude opt-in)
  ├── fixtures/
  │   └── sample_kb_corpus/          # ~10 PDF/DOCX (synthetic, public)
  └── reports/
      └── 2026-04-30_baseline.md
```

### Golden question format

```yaml
- id: gq-001
  query: "What are the status mapping rules from PIM to PLM?"
  intent: data_mapping
  expected_chunk_keywords:
    - "product_status"
    - "lifecycle_state"
    - "uppercase"
  expected_doc_ids:
    - "KB-PLM-MAPPING-A1B2-chunk-3"
    - "KB-PLM-MAPPING-A1B2-chunk-4"
  expected_answer_must_contain:
    - "transform: uppercase"
```

### Metrics

| Metric | Measures | Primary for |
|--------|----------|-------------|
| recall@5 | % of golden queries with at least one expected chunk in top-5 | X2 (embedder) |
| recall@20 | as above for top-20 | X4 (contextual retrieval) |
| MRR | Mean Reciprocal Rank of first correct chunk | X3 (reranker) |
| NDCG@5 | rank-quality weighted | X3 secondary |
| caption-quality | LLM-judge on 5 figures (Claude opt-in) | X1 (parser/VLM) |
| faithfulness | final answer contains `expected_answer_must_contain` | end-to-end |
| latency p50/p95 | end-to-end `retrieve()` time | sanity for all |

### Workflow

```bash
# Baseline pre-ADR
python tests/eval/run_rag_eval.py --label baseline --output reports/2026-04-30_baseline.md

# After each ADR
python tests/eval/run_rag_eval.py --label adr-x1-parser --compare baseline
```

### CI placement

- Eval harness is **NOT mandatory CI** (slow, uses external LLMs)
- **Pre-merge mandatory** for every ADR-X* — reviewer triggers manually, attaches report to PR

### Effort

- Setup: ~½ day (script + 5 golden questions for format validation)
- 30–50 golden q: ~½ day distributed (use the system itself to generate eval data from existing Integration Specs)
- Per-ADR run: ~5 min execution + ~10 min report

### Risks

- **R1 (medium)**: poor-quality golden questions → misleading metrics. Mitigation: human pair-review of golden questions before trusting numbers (CLAUDE.md §2 human-in-the-loop).
- **R2 (low)**: 30–50 queries are statistically thin for production CI. Acceptable for PoC; expand later.
- **R3 (low)**: faithfulness LLM-judge introduces variance → run `n=3` and average for critical comparisons.

---

## 10. Cross-cutting concerns

### 10.1 Testing strategy

| Layer | Scope | Files | Per ADR |
|-------|-------|-------|---------|
| Unit | dispatch logic, fallback chains, config flags | `tests/test_*.py` per new module | all |
| Component | `OllamaEmbeddingFunction`, `cross_encoder_rerank`, `add_context_to_chunks` | mock httpx/anthropic/ollama | X2/X3/X4 |
| Integration | smoke end-to-end ingestion → query → top-K | `tests/integration/test_pipeline_smoke.py` (new) | X1+X2+X3+X4 |
| Eval | recall, MRR, NDCG, faithfulness | `tests/eval/` | all |
| Regression | all existing 329 tests remain green | `pytest tests/` | all |

**Backward-compat:** every new flag has a default consistent with current behavior when reasonable. ADR-X3 and X4 are the most invasive; old codepaths (TF-IDF, weighted-merge, no-context chunking) are kept under feature flag for two sprints post-merge.

### 10.2 Security review (CLAUDE.md §10–11)

| Concern | ADR | Mitigation |
|---------|-----|------------|
| Prompt injection in chunks passed to Claude | X4 | Wrap doc/chunk in XML tags (`<document>`, `<chunk>`) per Anthropic spec. Output-as-untrusted: generated context passes through `bleach.clean()` before ChromaDB storage |
| Data exfiltration to Claude | X3, X4 | Opt-in via `ANTHROPIC_API_KEY`. HOW-TO documents "use only with synthetic / public / Accenture-classified data". Runtime banner enforced |
| Models downloaded at runtime (sentence-transformers, Ollama pulls) | X1, X2, X3 | Pin versions in requirements + Dockerfile pre-pull. `HF_HUB_DISABLE_TELEMETRY=1` |
| LLM-as-judge bias (X3 opt-in) | X3 | Documented as soft signal, never sole ranking source. Cross-encoder remains primary gate |
| OWASP LLM Top-10 (LLM01 prompt injection, LLM06 sensitive disclosure) | X3, X4 | Covered by 1–2 above. Structured logging of prompt-injection attempts |

### 10.3 Rollback (consolidated)

All ADRs follow the same pattern:

1. Feature flag default-on but runtime-disablable via env var (instant rollback, no redeploy)
2. Old codepaths preserved 2 sprints post-merge
3. ChromaDB volume snapshot before X2 and X4 (changing embedding space)
4. Git tag `pre-adr-x{n}` on `main` before each merge

| ADR | Rollback flag |
|-----|--------------|
| X1 | `VLM_MODEL_NAME=llava:7b` |
| X2 | `EMBEDDER_MODEL_NAME=all-MiniLM-L6-v2` + volume restore |
| X3 | `RERANKER_ENABLED=false` + `RAG_USE_RRF=false` |
| X4 | `CONTEXTUAL_RETRIEVAL_ENABLED=false` + volume restore |

### 10.4 Global risks

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| G1 | End-to-end p95 latency exceeds SLA | Medium | Eval harness measures latency per ADR; if >2× baseline → tune top-N or downgrade model |
| G2 | Dependency conflict (sentence-transformers, docling 2.5, langchain) | Medium | `pip-compile` lockfile before X1; 30-min compatibility spike |
| G3 | Compliance §1 violated (Claude X4 used with client data) | **High** | Runtime banner + explicit documentation + warning log on every `ANTHROPIC_API_KEY` use |
| G4 | Existing tests (329) break for `ScoredChunk` shape changes | Low | `ScoredChunk` already has `semantic_type=""` default; new fields are additive |
| G5 | KB re-ingestion long in production (X2 + X4) | Low | Already accepted; HOW-TO with time estimates |

### 10.5 Definition of Done (CLAUDE.md §14)

For every ADR-X{n}, PR is mergeable only if:

- [ ] Feature plan checklist completed
- [ ] ADR `docs/adr/ADR-X{n}-{name}.md` created (template `ADR-000-template.md`)
- [ ] Unit tests written and green (target: ≥85% coverage of new module)
- [ ] Existing tests (329+) remain green
- [ ] Eval harness run produces report `tests/eval/reports/{date}_adr-x{n}.md` attached to PR
- [ ] Code review (Superpowers Plugin) executed + checklist disclosure
- [ ] Security review (Anthropic Security Guidance plugin if available) + OWASP-aligned
- [ ] `architecture_specification.md` updated
- [ ] `functional-guide.md` updated (HOW-TO if relevant)
- [ ] No restricted data used in eval harness fixtures

---

## 11. Approval Trail

| # | Section | Status |
|---|---------|--------|
| 1 | Target architecture + ADR sequence | Approved |
| 2 | ADR-X1 Parser (Granite-Vision + LLaVA fallback) | Approved |
| 3 | ADR-X2 Embedder (nomic-embed-text-v1.5) | Approved |
| 4 | ADR-X3 Reranker + RRF | Approved |
| 5 | ADR-X4 Contextual Retrieval | Approved |
| 6 | Eval harness | Approved |
| 7 | Testing/security/rollback/sequencing | Approved |

---

## 12. Next steps

1. Commit this design doc to `main`.
2. Invoke `superpowers:writing-plans` to produce a detailed implementation plan (`2026-04-30-rag-pipeline-modernization-plan.md`) with file-by-file changes, test cases, and step ordering.
3. Spike (30 min) on Granite-Vision Ollama availability before kicking off X1.
4. Compile initial 30–50 golden questions in `tests/eval/golden_questions.yaml` (½ day, can be parallelized).
5. Open ADR-X0 (eval harness) PR — first delivery.
