# ADR-051 — KB Export / Import

**Status:** Accepted
**Date:** 2026-04-27
**Authors:** Emiliano Gritti (AI-assisted, Claude Code)

---

## Context

The Knowledge Base (KB) is populated through several channels:
- Manual file uploads (`source_type = "file"`) processed via Docling + ChromaDB
- Registered URL links (`source_type = "url"`) stored in MongoDB, fetched live at generation time
- Automated ingestion sources (`source_type ∈ {openapi, html, mcp}`) indexed directly in ChromaDB by the ingestion-platform

Currently there is no mechanism to back up, restore, or migrate KB content between environments. Operators cannot:
- Export the KB as a portable snapshot before a maintenance operation
- Restore a known-good KB state after accidental deletion
- Seed a new environment with an existing KB

The feature must support **full export** (all source types) and **selective export/import** (user picks one or more source types).

---

## Decision

Implement a JSON-based export/import mechanism as two new endpoints on the integration-agent:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/kb/export` | GET | Download a JSON bundle of KB documents and chunks |
| `/api/v1/kb/import` | POST | Upload a JSON bundle and re-insert its contents |

### Export bundle format (`KBExportBundle`)

```json
{
  "export_version": "1.0",
  "exported_at": "<ISO-8601>",
  "source_types_included": ["file", "url", "openapi", "html", "mcp"],
  "kb_documents": [ ...KBDocument records (file + url only)... ],
  "chunks": [
    {
      "id": "<chunk-id>",
      "text": "<chunk text>",
      "metadata": { "document_id": "...", "source_type": "...", ... }
    }
  ]
}
```

**Source type mapping:**
- `file` / `url` → recorded in MongoDB `kb_documents` + state.kb_docs; `file` chunks also in ChromaDB
- `openapi` / `html` / `mcp` → chunks directly in ChromaDB (no KBDocument record)

### Import behaviour

- Chunks and documents are **upserted** (insert-or-overwrite by ID)
- The `overwrite` query parameter (default `false`) controls whether existing documents are replaced or skipped
- After import, the BM25 sparse index is rebuilt
- The caller may restrict which source types to import via the `source_types` query parameter

### Authentication

Both endpoints require the bearer token (`require_token`) to prevent unauthorized data exfiltration or injection.

---

## Alternatives Considered

| Option | Trade-off |
|---|---|
| Binary/ZIP with original files | Would require re-parsing on import (slow, large). JSON with extracted text avoids re-processing. |
| Full vector export (with embeddings) | Embeddings are model-specific and large. Re-embedding on import is cleaner and ensures consistency with the current model. |
| Separate backup service | Over-engineered for the current scale. Single endpoint is sufficient. |

---

## Consequences

**Positive:**
- Enables environment migration, disaster recovery, and KB seeding
- Selective source-type filtering keeps exports focused
- No re-parsing pipeline on import — text is preserved from original ingestion
- BM25 index rebuilt automatically after import

**Negative:**
- Exported chunks carry text content — treat export files as sensitive data artefacts
- Very large KBs (>10k chunks) produce large JSON bundles; no streaming is implemented (acceptable for current scale)
- Embeddings are recomputed on import (ChromaDB handles this transparently, but adds latency for large bundles)

---

## Validation Plan

1. Unit tests: export empty KB, export with filters, import valid bundle, import duplicate (skip/overwrite), import invalid format
2. Integration test: export → clear KB → import → verify document count and BM25 index
3. Security: verify endpoint rejects requests without auth token

---

## Rollback Strategy

The export/import endpoints are additive. Removing them requires only deleting the two router functions and their schemas — no migration needed.

---

## Traceability

- Implements gap identified in ADR-036 (ingestion platform) and ADR-048 (enrichment) analyses
- Security: OWASP A01 (access control via auth token), A03 (input validation on bundle format)
- Test Plan: `services/integration-agent/tests/test_kb_endpoints.py` (export/import section)
