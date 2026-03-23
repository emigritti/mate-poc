# ADR-036: Ingestion Platform Architecture — n8n + Multi-Source Collectors

**Status**: Accepted
**Date**: 2026-03-23
**Deciders**: Project team

---

## Context

The current KB ingestion is limited to manual single-file uploads and URL registration (live-fetched at generation time). To strengthen the KB with automatically updated content from structured (OpenAPI/Swagger), semi-structured (HTML documentation pages), and agentic (MCP server capabilities) sources, a dedicated ingestion platform is required.

Design input: `docs/ingestion_documentation_system_architettura v3.md`

---

## Decision

Implement a new **`services/ingestion-platform/`** FastAPI service (port 4006) alongside the existing `integration-agent`. n8n (port 5678) orchestrates scheduled and manual ingestion workflows.

### Architecture

```
n8n (WF-01..WF-06)
  ↓ HTTP trigger
ingestion-platform (port 4006)
  ├── routers/sources.py       — Source Registry CRUD
  ├── routers/ingest.py        — trigger endpoints
  ├── collectors/
  │   ├── openapi/             — deterministic spec parsing
  │   ├── html/                — Playwright + Claude API semantic extraction
  │   └── mcp/                 — Python MCP SDK introspection
  └── services/
      ├── indexing_service.py  — ChromaDB writer
      ├── diff_service.py      — hash comparison + change summary
      └── claude_service.py    — Anthropic SDK wrapper
        ↓ upsert
ChromaDB kb_collection (shared with integration-agent)
        ↓ read
integration-agent RAG pipeline (unchanged)
```

### ChromaDB Integration

Chunks from ingestion-platform are written to the **same `kb_collection`** as manually uploaded files. Distinction via metadata:

```python
chunk_id = f"src_{source_code}-chunk-{index}"  # never collides with "{doc_id}-chunk-{n}"
metadata["source_type"] = "openapi" | "mcp" | "html"  # new field
metadata["source_code"] = "payment_api_v3"             # new field
# Existing fields preserved: tags_csv, section_header, chunk_type, page_num
```

**Zero changes to `integration-agent/services/retriever.py`.**

### MongoDB (3 new collections, non-conflicting)

- `sources` — source registry
- `source_runs` — execution audit log
- `source_snapshots` — lite versioning (current + previous snapshot per source)

### n8n Workflows

| ID | Trigger | Action |
|---|---|---|
| WF-01 | Cron (1h) | Dispatch stale sources |
| WF-02 | HTTP | OpenAPI refresh |
| WF-03 | HTTP | HTML refresh |
| WF-04 | HTTP | MCP refresh |
| WF-05 | Webhook | Manual UI refresh |
| WF-06 | Cron (daily) | Breaking change notification log |

---

## Alternatives Considered

### Option B — Extend integration-agent directly
Add collectors inside integration-agent routers. Simpler deployment but violates separation of concerns; integration-agent becomes too large.
**Rejected**: poor scalability and testability.

### Option C — Full v3 with 12 separate microservices
Exact literal implementation of v3 architecture document. Maximum fidelity but months of effort.
**Rejected**: disproportionate for PoC; Option A implements the same architecture with pragmatic service consolidation.

---

## Consequences

### Positive
- KB unified in a single ChromaDB collection — RAG pipeline needs zero changes
- Collectors independently testable and deployable
- n8n provides visual workflow debugging and retry logic
- Source versioning enables change detection (hash-based diff + Claude summary)

### Negative
- Two services write to the same ChromaDB collection — requires strict ID naming convention
- ANTHROPIC_API_KEY required for HTML collector (Phase 4)
- n8n adds a new infrastructure dependency

---

## Security Considerations (CLAUDE.md §10, §11)
- Claude API outputs are always validated against Pydantic schemas before DB write
- Claude never writes to DB directly — `IndexingService` is the sole writer
- Source trace citation mandatory per HTML chunk (`page_url`, `section`)
- `ANTHROPIC_API_KEY` stored as environment variable, never hardcoded
- n8n webhook endpoints validate source_id before dispatching

---

## Validation Plan
1. Unit tests: `services/ingestion-platform/tests/` (models, router, indexing_service)
2. Integration test: register PetStore OpenAPI spec → ingest → verify chunks in ChromaDB → RAG search returns results
3. n8n smoke test: import WF-02, execute manually, verify `source_runs` entry in MongoDB

---

## Rollback Strategy
- Remove `ingestion-platform` and `n8n` containers from docker-compose.yml
- Integration-agent is completely independent — no code changes required to roll back
- ChromaDB chunks from ingestion-platform can be bulk-deleted via `IndexingService.delete_source_chunks()`
