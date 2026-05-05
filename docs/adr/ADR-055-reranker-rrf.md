# ADR-055 — Retrieval Upgrade: RRF Fusion + Cross-Encoder Reranker (ADR-X3)

**Status:** Accepted
**Date:** 2026-05-05
**Authors:** Emiliano Gritti (AI-assisted, Claude Code)
**Enhances:** ADR-027 (BM25 hybrid retrieval), ADR-028 (multi-query expansion)

---

## Context

The current retrieval pipeline (ADR-027/028) fuses ChromaDB dense and BM25 results with a score-weighted merge (`_ensemble_merge`: 0.6 dense / 0.4 sparse) and reranks using TF-IDF cosine similarity (`_tfidf_rerank`).

Two structural weaknesses:

1. **Score-weighted merge** normalizes scores per-source (max-norm), then weights them. When one source has a uniform score distribution and the other has a sharp peak, the merge flattens signal. The approach requires per-source tuning and is fragile to scale heterogeneity.
2. **TF-IDF reranker** is keyword-overlap, not semantic. It does not understand paraphrase, negation, or intent. Cross-encoder models score chunk–query pairs jointly and are 1–2 orders of magnitude better on rerank benchmarks (BEIR, MTEB).

---

## Decision

### A — Replace `_ensemble_merge` with Reciprocal Rank Fusion (RRF)

```
RRF_score(d) = Σ_i  1 / (k + rank_i(d))     k = 60
```

RRF fuses by rank, not score — no normalization required, no weight tuning, future-proof for additional retrieval sources (ColBERT, SPLADE, etc.). Standard on BEIR benchmarks.

### B — Replace `_tfidf_rerank` with `bge-reranker-base` cross-encoder

| Reranker | Params | RAM | CPU latency (30 pairs) |
|---|---|---|---|
| TF-IDF cosine (current) | — | — | <50 ms |
| **`bge-reranker-base`** ⭐ | 278M | ~600 MB | 800–1500 ms |
| `bge-reranker-v2-m3` | 568M | ~1.2 GB | 2–4 s |
| `mxbai-rerank-base` | 184M | ~450 MB | 600–900 ms |

`bge-reranker-base` is the CPU sweet spot: multilingual, sub-2 s for 30 pairs, BAAI Apache-2.0.

Pipeline after change: `RRF(top-30) → cross-encoder → top-10 → (opt) LLM-judge → top-K`

### C — Claude Haiku LLM-judge (opt-in final gate)

When `LLM_JUDGE_ENABLED=true` AND `ANTHROPIC_API_KEY` present, the top-10 cross-encoder results are scored by Claude Haiku for relevance against the query. Uses prompt caching (system + chunks cached, ADR-037 pattern) for ~90% cost reduction.

This is a **soft signal** gate — never the sole ranking source. Cross-encoder remains the primary gate.

### New config vars

| Env var | Default | Effect |
|---|---|---|
| `RAG_USE_RRF` | `true` | RRF fusion; `false` → legacy weighted-merge |
| `RAG_RRF_K` | `60` | RRF constant |
| `RERANKER_ENABLED` | `true` (`false` in tests) | Cross-encoder; `false` → TF-IDF |
| `RERANKER_MODEL_NAME` | `BAAI/bge-reranker-base` | HuggingFace model ID |
| `RERANKER_TOP_N` | `30` | Candidates fed to cross-encoder |
| `LLM_JUDGE_ENABLED` | `false` | Opt-in Claude Haiku final reranker |
| `LLM_JUDGE_TOP_K` | `10` | Candidates fed to judge |
| `LLM_JUDGE_MODEL` | `claude-haiku-4-5-20251001` | Judge model |

### Files changed

| File | Change |
|---|---|
| `services/integration-agent/services/retriever.py` | `_ensemble_merge()` → `_rrf_merge()`; `_tfidf_rerank()` deprecated; new `_cross_encoder_rerank()`; new `_llm_judge_rerank()` |
| `services/integration-agent/services/reranker_service.py` | New module: `CrossEncoderReranker` wrapping `sentence_transformers.CrossEncoder`; lazy-loaded |
| `services/integration-agent/services/llm_judge_service.py` | New module: Claude Haiku judge with prompt caching |
| `services/integration-agent/config.py` | 7 new vars above |
| `services/integration-agent/requirements.txt` | `sentence-transformers>=3.0,<4.0` |
| `services/integration-agent/Dockerfile` | Pre-download `bge-reranker-base` via `HF_HOME` cache layer |

---

## Consequences

### Positive
- RRF eliminates score-normalization fragility; zero tuning overhead
- Cross-encoder: semantic understanding of paraphrase, negation, intent
- LLM judge: highest-quality optional final gate for production use cases
- All improvements stack: X3 benefits directly from X2 (better candidate pool)

### Negative / Risks

| Risk | Severity | Mitigation |
|---|---|---|
| `sentence-transformers` downloads ~600 MB on first startup | Medium | Docker image pre-pulls `HF_HOME` cached layer; `HF_HUB_DISABLE_TELEMETRY=1` |
| Cross-encoder p95 > 2 s under load | Low | Reduce `RERANKER_TOP_N` to 20; or use `mxbai-rerank-base` (similar quality, faster) |
| LLM judge cost without prompt caching | Low | Prompt caching mandatory; documented and tested |
| LLM judge bias (model prefers verbose chunks) | Low | Documented as soft signal; cross-encoder always runs first |

---

## Validation plan

- Unit: `test_reranker_service.py::test_cross_encoder_returns_expected_order` (mock `CrossEncoder.predict`)
- Unit: `test_retriever.py::test_rrf_merge_combines_ranks_not_scores` (verify RRF formula, regression vs `_ensemble_merge`)
- Unit: `test_retriever.py::test_llm_judge_disabled_when_key_absent` (graceful fallback)
- Eval harness: `MRR` and `NDCG@5` delta vs baseline — primary metrics
- Full suite regression: `pytest tests/ -q`

---

## Rollback

```bash
# Instant rollback — no redeploy needed
export RERANKER_ENABLED=false    # restores TF-IDF
export RAG_USE_RRF=false          # restores weighted-merge
```

Cross-encoder is lazy-loaded on first call — no startup cost when disabled.
Git tag `pre-adr-x3-merge` on `main` before merge.

---

## Compliance (CLAUDE.md)

- `sentence-transformers` runs locally — no external API call → §1 satisfied for reranker
- LLM judge (opt-in): chunk text sent to Claude API → §1 data boundary: only with synthetic/public/Accenture-Internal data; runtime warning log on every Claude call; fallback when key absent
- `HF_HUB_DISABLE_TELEMETRY=1` set in Dockerfile — §10 no implicit data exfiltration
- LLM judge output treated as untrusted (score only) — §11 agentic security
