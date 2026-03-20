# ADR-027 — BM25 Hybrid Retrieval: Dense + Sparse Ensemble

| Field        | Value                                          |
|--------------|------------------------------------------------|
| **Status**   | Accepted                                       |
| **Date**     | 2026-03-20                                     |
| **Tags**     | rag, retrieval, bm25, chromadb, phase2         |

## Context
Pure dense retrieval (ChromaDB embeddings) underperforms on exact technical terms
(e.g. "SAP IDOC", "REST webhook", "SFTP batch"). BM25 sparse retrieval is strong
on keyword matching but weak on semantic similarity. Combining both addresses both failure modes.

## Decision
Introduce `rank_bm25` (BM25Plus) alongside ChromaDB. Scores are normalised within each
retriever and merged with weights 0.6 (dense) / 0.4 (sparse), configurable via
`RAG_BM25_WEIGHT`. Distance-to-score conversion uses `1/(1+d)` (metric-agnostic formula
that works correctly for both L2 and cosine ChromaDB metrics). The BM25 index is built
in-memory from KB chunk texts at startup and rebuilt after every KB upload/delete.

## Alternatives Considered
- **Dense only** (current): misses keyword-heavy queries. Rejected.
- **Cross-encoder re-ranker**: too slow for CPU instances; deferred to Phase 2b.
- **ElasticSearch/OpenSearch**: operational overhead not justified for PoC scale. Rejected.

## Validation Plan
- Unit tests: `tests/test_retriever.py` — 16 tests covering all pipeline stages
- Integration: existing KB upload/delete tests verify BM25 rebuild is called

## Rollback
Remove `services/retriever.py` and revert `routers/agent.py` to use `query_rag_with_tags`.
No data migration required.
