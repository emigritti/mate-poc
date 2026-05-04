# How To — Modernized RAG Pipeline (ADR-X1 → ADR-X4)

This guide summarizes the runtime behavior, configuration knobs, and rollback
flags introduced by the RAG pipeline modernization programme.

**Reference design:** [docs/plans/2026-04-30-rag-pipeline-modernization-design.md](../docs/plans/2026-04-30-rag-pipeline-modernization-design.md)
**Eval harness:** [HOW-TO/how-to-rag-eval.md](how-to-rag-eval.md)
**Branch:** `rag-modernization` (pre-merge)

---

## Pipeline at a glance

```
INGESTION
  Docling 2.5 + VLM (granite3.2-vision:2b ⤵︎ llava:7b fallback)   ← ADR-X1
       │
       ▼
  semantic_chunk + Contextual Retrieval (Claude ⤵︎ Ollama fallback) ← ADR-X4
       │
       ▼
  nomic-embed-text-v1.5 via Ollama (search_document: prefix)        ← ADR-X2
       │
       ▼
  ChromaDB kb_collection + BM25Plus index

RETRIEVAL
  Multi-query (2 template + 2 LLM variants, ADR-028)
       │
       ▼
  ChromaDB dense (search_query: prefix) + BM25Plus (parallel)
       │
       ▼
  Reciprocal Rank Fusion (k=60)                                    ← ADR-X3
       │
       ▼
  Cross-encoder bge-reranker-base (top-30 → top-10)                 ← ADR-X3
       │
       ▼
  [opt] Claude Haiku LLM-judge (top-10 → top-K)                     ← ADR-X3
       │
       ▼
  Semantic v2 bonus (ADR-048) + Wiki Graph RAG (ADR-052) [unchanged]
```

---

## Configuration knobs (env vars / `config.py`)

### ADR-X1 — Vision

| Flag | Default | Effect |
|------|---------|--------|
| `VLM_MODEL_NAME` | `granite3.2-vision:2b` | Primary VLM for image captioning |
| `VLM_FALLBACK_MODEL_NAME` | `llava:7b` | Used when primary fails |
| `VLM_FORCE_FALLBACK` | `false` | Skip primary, use fallback only |
| `VISION_CAPTIONING_ENABLED` | `true` | Master switch |

### ADR-X2 — Embedder

| Flag | Default | Effect |
|------|---------|--------|
| `EMBEDDER_PROVIDER` | `ollama` | Set to `default` to use ChromaDB MiniLM |
| `EMBEDDER_MODEL_NAME` | `nomic-embed-text:v1.5` | — |
| `EMBEDDER_DOC_PREFIX` | `search_document: ` | nomic ingestion prefix |
| `EMBEDDER_QUERY_PREFIX` | `search_query: ` | nomic retrieval prefix |

### ADR-X3 — Reranker / Fusion

| Flag | Default | Effect |
|------|---------|--------|
| `RAG_USE_RRF` | `true` | RRF fusion (false → legacy weighted-merge) |
| `RAG_RRF_K` | `60` | RRF constant |
| `RERANKER_ENABLED` | `true` (false in tests) | Cross-encoder reranker (false → TF-IDF) |
| `RERANKER_MODEL_NAME` | `BAAI/bge-reranker-base` | — |
| `RERANKER_TOP_N` | `30` | Candidates fed to cross-encoder |
| `LLM_JUDGE_ENABLED` | `false` | Opt-in Claude Haiku final reranker |
| `LLM_JUDGE_TOP_K` | `10` | Candidates fed to judge |
| `LLM_JUDGE_MODEL` | `claude-haiku-4-5` | — |

### ADR-X4 — Contextual Retrieval

| Flag | Default | Effect |
|------|---------|--------|
| `CONTEXTUAL_RETRIEVAL_ENABLED` | `true` (false in tests) | Master switch |
| `CONTEXTUAL_PROVIDER` | `claude` | `claude` → fallback `ollama` automatically |
| `CONTEXTUAL_MODEL_CLAUDE` | `claude-haiku-4-5` | — |
| `CONTEXTUAL_MODEL_OLLAMA` | `llama3.1:8b` | Used when no `ANTHROPIC_API_KEY` |
| `CONTEXTUAL_MAX_TOKENS` | `120` | Cap on situating annotation length |

---

## Rollback (per ADR)

Each ADR is reversible at runtime by a single env var:

```bash
# ADR-X1: revert to LLaVA-only
export VLM_FORCE_FALLBACK=true

# ADR-X2: revert to ChromaDB default MiniLM (DROPS COLLECTIONS — re-ingest required)
export EMBEDDER_PROVIDER=default

# ADR-X3: revert reranker (TF-IDF) and/or fusion (weighted-merge)
export RERANKER_ENABLED=false
export RAG_USE_RRF=false

# ADR-X4: skip situating annotations on next ingestion (existing chunks unchanged)
export CONTEXTUAL_RETRIEVAL_ENABLED=false
```

ChromaDB volume snapshots before X2 and X4 merges are recommended (the embedding
space changes with X2; the chunk text changes with X4).

---

## Compliance — CLAUDE.md §1 (data classification)

ADR-X3 (LLM-judge) and ADR-X4 (Contextual Retrieval) send chunks to the Claude
API. Keep them disabled — or use only synthetic / public / Accenture-Internal
data — when uploading client material.

The runtime emits a warning log on every Claude call. Both features fall back to
Ollama-only operation when `ANTHROPIC_API_KEY` is absent.

---

## Setup checklist

```bash
# 1. Pull the new models on Ollama
ollama pull granite3.2-vision:2b
ollama pull nomic-embed-text:v1.5
ollama pull llama3.1:8b   # already present on most stacks

# 2. (optional) Pull LLaVA fallback if you want VLM redundancy
ollama pull llava:7b
export VLM_PULL_FALLBACK=true

# 3. Drop old kb_collection / kb_summaries / approved_integrations
#    (X2 changes the embedding space — old vectors are incompatible)
#    Use the UI admin button or drop+recreate via chromadb client.

# 4. Re-ingest the KB through the UI (or scripted batch upload)

# 5. Run the eval harness baseline + per-ADR delta
cd services/integration-agent
python -m tests.eval.run_rag_eval --label baseline
# … then per ADR
```

---

## Test counts (as of branch `rag-modernization` HEAD)

| Component | Tests |
|-----------|-------|
| Eval harness (Phase 0) | 22 (recall metrics 10 + faithfulness 8 + run_rag_eval 3 + runner 1) |
| ADR-X1 vision_service | 6 |
| ADR-X2 embedder + wiring | 3 + 2 |
| ADR-X2 ingestion-platform | 2 |
| ADR-X3 RRF / cross-encoder / LLM-judge | 3 + 3 + 5 |
| ADR-X4 contextual retrieval + KB wire | 5 + 1 |
| **Total new tests** | **51** |
| **Full suite passing** | **879** (11 pre-existing failures unrelated to this work) |
