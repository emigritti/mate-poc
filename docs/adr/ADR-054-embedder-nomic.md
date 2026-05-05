# ADR-054 — Embedder Upgrade: nomic-embed-text-v1.5 via Ollama (ADR-X2)

**Status:** Accepted
**Date:** 2026-05-05
**Authors:** Emiliano Gritti (AI-assisted, Claude Code)
**Supersedes:** replaces ChromaDB default `all-MiniLM-L6-v2` embedding function

---

## Context

The current embedding model is ChromaDB's built-in `all-MiniLM-L6-v2` (2020):

- **384 dimensions** — limits future flexibility (Matryoshka truncation, multi-vector)
- **256-token context window** — Docling semantic chunks routinely exceed this; overflow is silently truncated, degrading retrieval quality
- **English-only** — KB content includes Italian documentation
- No task-prefix support — ingestion and query embeddings are computed identically, losing retrieval signal

ADR-X4 (Contextual Retrieval) will prepend 50–100 token situating annotations to every chunk, pushing effective chunk length further beyond 256 tokens. The embedder upgrade is therefore a hard prerequisite for X4 to deliver its full benefit.

---

## Decision

### Embedder selected: `nomic-embed-text-v1.5`

| Model | Dim | Context | RAM CPU | Latency CPU / chunk | Notes |
|---|---|---|---|---|---|
| `all-MiniLM-L6-v2` (current) | 384 | **256 tokens** | ~100 MB | ~10 ms | 2020, English, tiny window |
| **`nomic-embed-text-v1.5`** ⭐ | 768 | **8192 tokens** | ~500 MB | ~80–150 ms | 2024, multilingual, top-CPU MTEB |
| `mxbai-embed-large` | 1024 | 512 | ~700 MB | ~150 ms | English-only |
| `bge-m3` | 1024 | 8192 | ~1.5 GB | ~400 ms | SOTA, too heavy for EC2 |

Decisive factors: 8k context (covers post-X4 contextual annotations), multilingual (IT+EN), Matryoshka representation learning (future-proof dimension truncation), already available via Ollama.

### Task-prefix requirement

`nomic-embed-text` requires task-specific prefixes per the model card:

| Call site | Prefix |
|---|---|
| Document ingestion | `search_document: ` + chunk text |
| Query retrieval | `search_query: ` + query text |

A custom `OllamaEmbeddingFunction` with `mode: "document" | "query"` is implemented in `embedding_function.py` (integration-agent and ingestion-platform). ChromaDB `collection.add()` uses `document` mode; `collection.query()` uses `query` mode.

### New config vars

| Env var | Default | Effect |
|---|---|---|
| `EMBEDDER_PROVIDER` | `ollama` | `ollama` → nomic; `default` → ChromaDB MiniLM |
| `EMBEDDER_MODEL_NAME` | `nomic-embed-text:v1.5` | Ollama model name |
| `EMBEDDER_DOC_PREFIX` | `search_document: ` | Ingestion prefix |
| `EMBEDDER_QUERY_PREFIX` | `search_query: ` | Retrieval prefix |

### Files changed

| File | Change |
|---|---|
| `services/integration-agent/embedding_function.py` | New `OllamaEmbeddingFunction(model, ollama_host, mode)` |
| `services/integration-agent/db.py` | Use `OllamaEmbeddingFunction` when `embedder_provider == "ollama"` |
| `services/integration-agent/services/retriever.py` | Pass `embedder_query_prefix` to query call; score formula unchanged (`1/(1+dist)`) |
| `services/integration-agent/config.py` | 4 new vars above |
| `services/ingestion-platform/embedding_function.py` | Mirror of integration-agent (same class) |
| `services/ingestion-platform/routers/ingest.py` | `_make_doc_embedder()` uses `OllamaEmbeddingFunction` |
| `services/ingestion-platform/config.py` | Mirror of integration-agent config vars |
| `docker-compose.yml` | `ollama-init` pulls `nomic-embed-text:v1.5` |

---

## Consequences

### Positive
- Full 8k token context — no silent truncation of long chunks
- Multilingual: Italian KB documents now embedded correctly
- Consistent ingestion/query signal via task prefixes
- Matryoshka support: future dimension reduction possible without re-ingestion

### Negative / Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Mandatory KB re-creation** — 384d and 768d collections are incompatible | High (expected) | Drop `knowledge_base` collection + full re-ingest; ChromaDB volume snapshot before merge |
| Ingestion latency ~10× per chunk (10 ms → 80–150 ms) | Low | One-shot; 5k-chunk KB ≈ 10 min full ingestion; acceptable |
| Forgetting task prefix → silent quality regression | Medium | Explicit in `OllamaEmbeddingFunction` constructor; unit-tested |
| EC2 p95 query latency > 250 ms | Low | Monitor post-deploy; fallback to `mxbai-embed-large` (similar quality, slightly faster) |

---

## Validation plan

- Unit: `tests/test_embedder.py` — mock httpx, assert model name, dim=768, correct prefix per mode
- Integration: create collection with nomic, add 3 chunks, query, assert non-empty results
- Eval harness: `recall@5` and `MRR` delta vs baseline — primary metric
- Full suite regression: `pytest tests/ -q`

---

## Rollback

```bash
# Revert to ChromaDB default (drops collections — re-ingest required)
export EMBEDDER_PROVIDER=default
```

Git tag `pre-adr-x2-merge` on `main` before merge.
ChromaDB volume snapshot recommended before and after merge.

---

## Compliance (CLAUDE.md)

- Embeddings computed locally via Ollama — no external API call → §1 data boundary satisfied
- `OllamaEmbeddingFunction` does not log chunk text — §10 (no sensitive data in logs)
- Both services (`integration-agent` and `ingestion-platform`) use identical config vars and collection settings — dimension consistency guaranteed
