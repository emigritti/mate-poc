# ADR-052 — LLM Wiki / Graph RAG

**Status:** Accepted
**Date:** 2026-04-27
**Authors:** Emiliano Gritti (AI-assisted, Claude Code)

---

## Context

The Knowledge Base (KB) is a flat vector store (ChromaDB) enriched with v2 semantic metadata per chunk (ADR-048): `entity_names`, `system_names`, `state_transitions`, `business_terms`, `field_names`, `semantic_type`, etc.

While BM25 + dense hybrid retrieval (ADR-027) and multi-query expansion (ADR-028) work well for direct similarity lookups, they have two blind spots:

1. **No cross-document relationship traversal** — if document A defines "OrderStatus" and document B describes the transition rules, a query about order flows may only retrieve one of them unless both are explicitly mentioned.
2. **No navigable knowledge map** — operators cannot explore the corpus as a structured graph; knowledge stays trapped in individual chunk embeddings.

The goal of ADR-052 is to add an **additive graph layer** that:
- Extracts entities and typed relationships from existing v2 metadata (no re-parse)
- Stores them in MongoDB as `wiki_entities` and `wiki_relationships` collections
- Exposes a Graph RAG retrieval step that traverses entity relationships to surface additional relevant chunks
- Provides an LLM Wiki UI where operators can browse entities, relationships, and the graph visually

ChromaDB and all existing retrieval pipelines remain **unchanged**.

---

## Decision

### Architecture

| Component | Technology | Motivation |
|---|---|---|
| Graph store | MongoDB `wiki_entities` + `wiki_relationships` | No new service; `$graphLookup` is native, zero-cost |
| Entity extraction | Rule-based from v2 chunk metadata | Deterministic; v2 fields already contain structured entity data |
| Relationship extraction | Rule-based (semantic_type patterns) + optional LLM enrichment | Reliable baseline; LLM upgrades ambiguous `RELATED_TO` edges |
| LLM enrichment model | `tag_model` (qwen3:8b, Ollama) | Already available; structured JSON output |
| Graph RAG step | Step 8 in `retriever.py` after semantic bonus | Additive; gated by `wiki_graph_retrieval_enabled` config |
| Wiki UI | `@xyflow/react` (React Flow) | React-native, Tailwind-friendly, no additional service |

### Data Model

#### `wiki_entities`
```json
{
  "entity_id":        "ENT-OrderStatus",
  "name":             "OrderStatus",
  "entity_type":      "state",
  "aliases":          ["order_status"],
  "doc_ids":          ["KB-A1B2"],
  "chunk_ids":        ["KB-A1B2-chunk-3"],
  "semantic_types":   ["state_model"],
  "tags_csv":         "Order,SAP",
  "chunk_count":      14,
  "source_modalities": ["pdf"],
  "first_seen_at":    "ISODate",
  "updated_at":       "ISODate"
}
```

#### `wiki_relationships`
```json
{
  "rel_id":             "REL-aa1bb2cc3d4e",
  "from_entity_id":     "ENT-OrderStatus",
  "to_entity_id":       "ENT-ShippedStatus",
  "rel_type":           "TRANSITIONS_TO",
  "label":              "transitions to",
  "weight":             0.8,
  "evidence_chunk_ids": ["KB-A1B2-chunk-3"],
  "extraction_method":  "rule_based",
  "doc_ids":            ["KB-A1B2"],
  "created_at":         "ISODate"
}
```

### Entity Type Mapping (from v2 metadata)

| v2 metadata field | `entity_type` |
|---|---|
| `system_names` | `system` |
| `entity_names` + `semantic_type ∈ {entity_definition}` | `api_entity` |
| `business_terms` | `business_term` |
| Nodes of `state_transitions` ("A -> B") | `state` |
| `entity_names` + `semantic_type == business_rule` | `rule` |
| `field_names` (≥3 fields in chunk) | `field` |
| `entity_names` + `semantic_type ∈ {integration_flow}` | `process` |
| fallback | `generic` |

### Relationship Types

| `rel_type` | Extraction trigger |
|---|---|
| `TRANSITIONS_TO` | `state_transitions` pairs "A -> B" |
| `MAPS_TO` | `data_mapping_candidate` + ≥2 entity_names |
| `CALLS` | `api_contract` + ≥2 system_names |
| `GOVERNS` | `business_rule` + entity_name |
| `TRIGGERS` | `event_definition` + entity_name |
| `HANDLES_ERROR` | `error_handling` + entity_name |
| `DEFINED_BY` | `field_definition` + entity_name + system_name |
| `RELATED_TO` | Co-occurrence of ≥2 entities in same chunk (generic fallback) |

### Graph RAG Retrieval (Step 8)

After `_apply_semantic_bonus()`, before top-K slice:

1. Collect `chunk_ids` from top-5 primary results
2. Find entities in `wiki_entities` where `chunk_ids: {$in: seed_ids}`
3. `$graphLookup` traversal on `wiki_relationships` up to `wiki_graph_max_depth` hops
4. If `wiki_graph_typed_edges_only=True`, filter `RELATED_TO` when typed edge exists for same pair
5. Collect `chunk_ids` from reachable entities (cap 2 per entity)
6. Fetch chunks from ChromaDB, wrap as `ScoredChunk` with `score=wiki_graph_score_bonus` (0.05)
7. Merge + re-sort with primary results; slice to `rag_top_k_chunks`

### Context Assembly Extension

`ContextAssembler.assemble()` accepts optional `wiki_chunks` parameter and appends:

```
## KNOWLEDGE GRAPH CONTEXT (related concepts from LLM Wiki):
### Source: wiki_graph · entity: OrderStatus · type: state_model
[chunk text]
```

Total wiki context capped at `wiki_rag_max_chars` (default 1500).

### Wiki UI (3 tabs)

- **Entities** — paginated table with live search, `entity_type` and tag filters, click → Detail
- **Entity Detail** — name/type header, outgoing/incoming edges with `RelTypeBadge`, chunk previews
- **Graph View** — React Flow canvas seeded by selected entity or full graph (≤50 nodes)

### Migration

Two paths:
- **CLI** (`scripts/build_wiki_graph.py`) — standalone script for CI/deploy; `--force`, `--llm-assist`, `--doc-id` flags
- **REST** (`POST /api/v1/wiki/rebuild`) — async job trigger from UI; polling via `GET /api/v1/wiki/rebuild/{job_id}`
- **Auto-build** — KB upload triggers background `WikiGraphBuilder.build_for_document()` when `wiki_auto_build_on_upload=True`

---

## New Configuration Settings

| Setting | Default | Env var |
|---|---|---|
| `wiki_graph_retrieval_enabled` | `True` | `WIKI_GRAPH_RETRIEVAL_ENABLED` |
| `wiki_graph_max_depth` | `2` | `WIKI_GRAPH_MAX_DEPTH` |
| `wiki_graph_max_neighbours` | `10` | `WIKI_GRAPH_MAX_NEIGHBOURS` |
| `wiki_graph_score_bonus` | `0.05` | `WIKI_GRAPH_SCORE_BONUS` |
| `wiki_llm_relation_extraction` | `False` | `WIKI_LLM_RELATION_EXTRACTION` |
| `wiki_rag_max_chars` | `1500` | `WIKI_RAG_MAX_CHARS` |
| `wiki_graph_typed_edges_only` | `True` | `WIKI_GRAPH_TYPED_EDGES_ONLY` |
| `wiki_auto_build_on_upload` | `True` | `WIKI_AUTO_BUILD_ON_UPLOAD` |

---

## New API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/wiki/entities` | List entities (q, entity_type, tags, limit, offset) |
| `GET` | `/api/v1/wiki/entities/{entity_id}` | Entity detail + edges + chunk previews |
| `GET` | `/api/v1/wiki/graph` | Graph data for React Flow (nodes + edges) |
| `GET` | `/api/v1/wiki/stats` | Entity/relationship counts + type breakdown |
| `GET` | `/api/v1/wiki/search` | Full-text search over name + aliases |
| `POST` | `/api/v1/wiki/rebuild` | Trigger async graph rebuild [token required] |
| `GET` | `/api/v1/wiki/rebuild/{job_id}` | Poll rebuild job status |
| `DELETE` | `/api/v1/wiki/entities/{entity_id}` | Delete entity + cascade edges [token required] |

---

## Alternatives Considered

| Alternative | Rejected because |
|---|---|
| Dedicated graph DB (Neo4j, ArangoDB) | New service = higher operational complexity; MongoDB `$graphLookup` is sufficient for depth ≤3 |
| LangChain GraphRAG or LlamaIndex KG | External framework adds dependency; our v2 metadata is already structured — pure extraction is simpler and more controllable |
| Full re-parse for relation extraction | Expensive; v2 metadata (ADR-048) already captures the needed structured fields |
| Real-time graph build on query | Latency too high; pre-built graph with async refresh is the right trade-off |

---

## Validation Plan

1. `docker compose run integration-agent python scripts/build_wiki_graph.py --force`
2. `GET /agent/api/v1/wiki/stats` → `total_entities > 0`
3. `GET /agent/api/v1/wiki/entities?limit=5` → pick entity_id
4. `GET /agent/api/v1/wiki/entities/{id}` → verify edges populated
5. `GET /agent/api/v1/wiki/graph?entity_id={id}&depth=2` → nodes + edges JSON
6. Agent trigger with entity-touching query → verify `wiki_graph chunks injected: N` in log
7. UI: navigate "LLM Wiki" → verify Entity List, Detail, Graph Canvas
8. `pytest tests/test_wiki_*.py tests/test_graph_retrieval.py -v` (68 tests, all passing)
9. Double-run CLI → `total_entities` unchanged (idempotency)

---

## Rollback Strategy

The wiki layer is strictly additive:

- **Config**: set `wiki_graph_retrieval_enabled=False` → step 8 becomes a no-op immediately, no restart needed if env var is changed
- **Data**: drop `wiki_entities` and `wiki_relationships` MongoDB collections; existing ChromaDB and retrieval are unaffected
- **Frontend**: revert `App.jsx`, `Sidebar.jsx` sidebar entry; the `WikiPage` component is a standalone route
- **API**: remove `wiki_router` from `main.py`; no shared state with other routers
- **KB hooks**: set `wiki_auto_build_on_upload=False` to stop background builds without code change

No changes to ChromaDB schema, existing MongoDB collections, or retrieval logic outside of the additive step 8.

---

## Files Changed

### Created
- `services/integration-agent/services/wiki_extractor.py`
- `services/integration-agent/services/wiki_graph_builder.py`
- `services/integration-agent/routers/wiki.py`
- `scripts/build_wiki_graph.py`
- `services/web-dashboard/src/components/pages/WikiPage.jsx`
- `services/web-dashboard/src/components/wiki/EntityList.jsx`
- `services/web-dashboard/src/components/wiki/EntityDetail.jsx`
- `services/web-dashboard/src/components/wiki/GraphCanvas.jsx`
- `services/web-dashboard/src/components/wiki/EntityTypeBadge.jsx`
- `services/web-dashboard/src/components/wiki/RelTypeBadge.jsx`
- `services/web-dashboard/src/components/wiki/WikiSearchBar.jsx`
- `services/integration-agent/tests/test_wiki_extractor.py`
- `services/integration-agent/tests/test_wiki_graph_builder.py`
- `services/integration-agent/tests/test_wiki_router.py`
- `services/integration-agent/tests/test_graph_retrieval.py`

### Modified
- `services/integration-agent/db.py` — 2 new collections + 11 indexes
- `services/integration-agent/state.py` — `wiki_build_jobs` dict
- `services/integration-agent/config.py` — 8 new `wiki_*` settings
- `services/integration-agent/main.py` — `wiki_router` registration
- `services/integration-agent/services/retriever.py` — step 8 graph traversal
- `services/integration-agent/services/rag_service.py` — `wiki_chunks` in `assemble()`
- `services/integration-agent/routers/kb.py` — auto-build + delete cleanup hooks
- `services/web-dashboard/src/api.js` — `wiki:` API section
- `services/web-dashboard/src/components/layout/Sidebar.jsx` — LLM Wiki nav item
- `services/web-dashboard/src/App.jsx` — `WikiPage` route + PAGE_META entry
- `services/web-dashboard/package.json` — `@xyflow/react` dependency
