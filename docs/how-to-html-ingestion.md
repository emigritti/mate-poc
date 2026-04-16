# HOW-TO: HTML Source Ingestion

> **Audience:** Developers and operators using the Ingestion Platform to ingest HTML documentation pages into the Integration Mate Knowledge Base.
> **Service:** `ingestion-platform` — port 4006
> **ADR references:** ADR-036 (architecture), ADR-037 (Claude API extraction)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [Pipeline Stages](#3-pipeline-stages)
4. [Step-by-Step Guide](#4-step-by-step-guide)
   - [4.1 Register an HTML source](#41-register-an-html-source)
   - [4.2 Trigger ingestion manually](#42-trigger-ingestion-manually)
   - [4.3 Check the run status](#43-check-the-run-status)
   - [4.4 Verify chunks in ChromaDB](#44-verify-chunks-in-chromadb)
5. [Configuration Reference](#5-configuration-reference)
6. [Running Without ANTHROPIC_API_KEY (Offline Mode)](#6-running-without-anthropic_api_key-offline-mode)
7. [Scheduled Ingestion via n8n](#7-scheduled-ingestion-via-n8n)
8. [Source Lifecycle Operations](#8-source-lifecycle-operations)
9. [Understanding Extraction Output](#9-understanding-extraction-output)
10. [Troubleshooting](#10-troubleshooting)
11. [Security Notes](#11-security-notes)

---

## 1. Overview

The HTML ingestion pipeline crawls one or more public documentation URLs, cleans each page, uses Claude AI to extract structured capabilities (API endpoints, authentication flows, integration guides, schemas), deduplicates them across pages, and writes them into the shared ChromaDB `kb_collection` where the RAG pipeline can retrieve them.

```
Entrypoint URLs
    ↓
[HTMLCrawler]       BFS crawl — httpx, same-domain only, max N pages
    ↓
[HTMLCleaner]       Strip scripts, nav, footer, boilerplate → clean text
    ↓
[HTMLRelevanceFilter]  Claude Haiku — is this page technically relevant?
    ↓ (skip if not relevant)
[HTMLAgentExtractor]   Claude Sonnet — extract structured capabilities (JSON)
    ↓
[HTMLNormalizer]    Validate → CanonicalCapability objects
    ↓  (repeated for each page, results accumulated)
[HTMLReconciler]    Claude Sonnet — merge near-duplicates across pages
    ↓
[HTMLChunker]       One CanonicalChunk per capability
    ↓
[IndexingService]   Upsert into ChromaDB kb_collection
    ↓
RAG pipeline retrieves chunks automatically
```

All Claude AI calls degrade gracefully: if `ANTHROPIC_API_KEY` is absent or a call fails, the pipeline continues with safe defaults (pages treated as relevant, extraction returns empty, reconciliation is skipped). See [Section 6](#6-running-without-anthropic_api_key-offline-mode).

---

## 2. Prerequisites

| Requirement | Details |
|---|---|
| `ingestion-platform` running | Port 4006 on the EC2 host (`18.197.235.56`) |
| MongoDB | Shared instance — `integration_mate` database |
| ChromaDB | Shared instance — `kb_collection` collection |
| `ANTHROPIC_API_KEY` | Optional — enables Claude extraction; without it, the pipeline runs in offline mode |
| Target URLs | Must be **public** HTML pages (no auth, no PII, no confidential content — CLAUDE.md §1) |

Check service health:

```bash
curl http://18.197.235.56:4006/health
# Expected: {"status": "ok"}
```

---

## 3. Pipeline Stages

| Stage | Component | Model | Purpose |
|---|---|---|---|
| Crawl | `HTMLCrawler` | — | BFS fetch via httpx; stays within same domain |
| Clean | `HTMLCleaner` | — | Remove scripts, nav, ads → readable text |
| Filter | `HTMLRelevanceFilter` | Claude Haiku | Binary: is this page technically relevant? |
| Extract | `HTMLAgentExtractor` | Claude Sonnet | Extract capabilities as schema-constrained JSON |
| Normalize | `HTMLNormalizer` | — | Validate → `CanonicalCapability` |
| Reconcile | `HTMLReconciler` | Claude Sonnet | Merge near-duplicates across all pages |
| Chunk | `HTMLChunker` | — | One `CanonicalChunk` per capability |
| Index | `IndexingService` | — | Upsert into ChromaDB |

**Chunk ID format:** `src_{source_code}-chunk-{index}`
This prefix never collides with integration-agent manual upload IDs (`{doc_id}-chunk-{n}`).

---

## 4. Step-by-Step Guide

### 4.1 Register an HTML source

A source must be registered once before it can be ingested. Use the `POST /api/v1/sources` endpoint.

**Request:**

```bash
curl -X POST http://18.197.235.56:4006/api/v1/sources \
  -H "Content-Type: application/json" \
  -d '{
    "code": "payment_api_docs",
    "source_type": "html",
    "entrypoints": [
      "https://docs.example.com/api/payments"
    ],
    "tags": ["payments", "api"],
    "refresh_cron": "0 */6 * * *",
    "description": "Payment API public documentation"
  }'
```

**Fields:**

| Field | Required | Description |
|---|---|---|
| `code` | Yes | Unique slug — used as ChromaDB chunk prefix (`src_{code}-chunk-*`). Lowercase, no spaces. |
| `source_type` | Yes | Must be `"html"` for HTML sources |
| `entrypoints` | Yes | List of starting URLs — at least one. The crawler starts BFS from each. |
| `tags` | Yes | At least one tag — inherited by all chunks for RAG tag-filtering |
| `refresh_cron` | No | Cron expression for scheduled refresh (default: every 6 hours) |
| `description` | No | Human-readable note |

**Response (201 Created):**

```json
{
  "id": "src_a1b2c3d4",
  "code": "payment_api_docs",
  "source_type": "html",
  "entrypoints": ["https://docs.example.com/api/payments"],
  "tags": ["payments", "api"],
  "refresh_cron": "0 */6 * * *",
  "description": "Payment API public documentation",
  "status": {
    "state": "active",
    "last_run_at": null,
    "last_success_at": null,
    "last_error": null
  },
  "created_at": "2026-04-16T10:00:00"
}
```

> **Choosing entrypoints:** Point to the top-level page of the documentation section you want. The crawler will follow links within the same domain up to `max_html_pages_per_crawl` (default: 20). If the documentation has multiple separate sections, list each section's root URL as an entrypoint.

---

### 4.2 Trigger ingestion manually

Use the source `id` returned in step 4.1.

```bash
curl -X POST http://18.197.235.56:4006/api/v1/ingest/html/src_a1b2c3d4
```

**Response (202 Accepted):**

```json
{
  "run_id": "run_20260416100523_src_a1b2",
  "status": "accepted",
  "source_id": "src_a1b2c3d4"
}
```

The ingestion runs asynchronously in the background. Use the `run_id` to check status.

---

### 4.3 Check the run status

Ingestion runs are persisted in MongoDB (`source_runs` collection). Query them via the sources endpoint:

```bash
# List all runs for a source
curl http://18.197.235.56:4006/api/v1/sources/src_a1b2c3d4

# Check run details directly in MongoDB (admin)
# db.source_runs.findOne({"id": "run_20260416100523_src_a1b2"})
```

**Run status values:**

| Status | Meaning |
|---|---|
| `running` | Background task still executing |
| `success` | Completed — check `chunks_created` and `changed` fields |
| `partial` | Some pages failed, others succeeded |
| `failed` | All attempts failed — see `errors` array |

**Key fields in a completed run:**

```json
{
  "id": "run_20260416100523_src_a1b2",
  "status": "success",
  "chunks_created": 24,
  "changed": true,
  "errors": [],
  "started_at": "2026-04-16T10:05:23",
  "finished_at": "2026-04-16T10:05:41"
}
```

**`changed: false` with `chunks_created: 0`** means the content hash matched the previous snapshot — nothing changed since the last run, so re-indexing was skipped.

---

### 4.4 Verify chunks in ChromaDB

After a successful run, chunks from this source appear in the shared `kb_collection`:

```python
import chromadb

client = chromadb.HttpClient(host="18.197.235.56", port=8000)
col = client.get_collection("kb_collection")

# Retrieve all chunks from this source
results = col.get(where={"source_code": "payment_api_docs"})
print(f"Chunks: {len(results['ids'])}")
print(results['documents'][0])   # first chunk text
print(results['metadatas'][0])   # first chunk metadata
```

**Chunk metadata fields:**

```json
{
  "document_id": "src_payment_api_docs",
  "chunk_index": 0,
  "tags_csv": "payments,api",
  "section_header": "create_payment",
  "chunk_type": "text",
  "page_num": 0,
  "source_type": "html",
  "source_code": "payment_api_docs",
  "snapshot_id": "run_20260416100523_src_a1b2",
  "capability_kind": "endpoint",
  "low_confidence": false
}
```

`low_confidence: true` means Claude assigned confidence < 0.7 — the chunk is present but flagged.

---

## 5. Configuration Reference

Set these as environment variables (or in `.env`) for the `ingestion-platform` service:

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(absent)* | Enables Claude extraction. Without it, pipeline runs in offline mode. |
| `CLAUDE_EXTRACTION_MODEL` | `claude-sonnet-4-6` | Model for semantic extraction and cross-page reconciliation |
| `CLAUDE_FILTER_MODEL` | `claude-haiku-4-5-20251001` | Model for relevance filtering and diff summaries |
| `MAX_HTML_PAGES_PER_CRAWL` | `20` | Hard upper bound on pages fetched per source run |
| `CAPABILITY_CONFIDENCE_THRESHOLD` | `0.7` | Below this, chunks are stored with `low_confidence=true` |
| `INTEGRATION_AGENT_URL` | `http://mate-integration-agent:3003` | URL for BM25 rebuild notification after indexing |
| `MONGO_URI` | *(required)* | MongoDB connection string |
| `CHROMA_HOST` | `mate-chromadb` | ChromaDB hostname |
| `CHROMA_PORT` | `8000` | ChromaDB port |

**Tuning `MAX_HTML_PAGES_PER_CRAWL`:**
- Large documentation sites (e.g., Swagger UI, full API reference): use 50–100
- Focused single-topic guides: use 5–10 to reduce Claude API cost
- Cost estimate: ~$0.006 per page (Haiku filter + Sonnet extraction)

---

## 6. Running Without ANTHROPIC_API_KEY (Offline Mode)

If `ANTHROPIC_API_KEY` is not set, the pipeline degrades gracefully at each stage:

| Stage | Behavior without API key |
|---|---|
| `HTMLRelevanceFilter` | Returns `True` for every page (all pages treated as relevant) |
| `HTMLAgentExtractor` | Returns `[]` — no capabilities extracted |
| `HTMLReconciler` | Passthrough — returns input unchanged |
| `DiffService.summarize()` | Returns plain-text fallback summary |

**Effect:** In offline mode, the crawl completes but produces **zero chunks** (no capabilities extracted). The run status is `success` with `chunks_created: 0` and `changed: true`.

This is intentional — the service stays stable and the pipeline can be tested end-to-end without API costs.

---

## 7. Scheduled Ingestion via n8n

n8n workflow **WF-03** handles scheduled HTML refresh.

**Import:** Load `workflows/n8n/WF-03-html-refresh.json` into n8n (port 5678).

**Manual trigger from n8n:**
1. Open n8n at `http://18.197.235.56:5678`
2. Navigate to WF-03
3. Click **Execute Workflow**
4. Pass payload: `{"source_id": "src_a1b2c3d4"}`

**n8n calls:** `POST /api/v1/ingest/html/{source_id}`

**WF-01 (stale source dispatcher, runs hourly)** automatically dispatches all active sources whose `refresh_cron` window has elapsed — no manual intervention needed for ongoing refresh.

---

## 8. Source Lifecycle Operations

**List all sources:**
```bash
curl http://18.197.235.56:4006/api/v1/sources
```

**Get one source:**
```bash
curl http://18.197.235.56:4006/api/v1/sources/src_a1b2c3d4
```

**Pause a source** (stops scheduled refresh, does not delete chunks):
```bash
curl -X PUT http://18.197.235.56:4006/api/v1/sources/src_a1b2c3d4/pause
```

**Reactivate a paused source:**
```bash
curl -X PUT http://18.197.235.56:4006/api/v1/sources/src_a1b2c3d4/activate
```

**Delete a source** (removes the registry entry; does NOT delete ChromaDB chunks automatically):
```bash
curl -X DELETE http://18.197.235.56:4006/api/v1/sources/src_a1b2c3d4
```

> To also remove the chunks from ChromaDB before deleting, call `IndexingService.delete_source_chunks("payment_api_docs")` or trigger a re-run with an empty result first.

---

## 9. Understanding Extraction Output

### Capability kinds

Claude extracts capabilities classified into these kinds:

| Kind | Example |
|---|---|
| `endpoint` | `POST /payments — Creates a new payment` |
| `auth` | `Bearer token authentication via /auth/token` |
| `schema` | `PaymentRequest object with amount, currency, metadata` |
| `integration_flow` | `Webhook notification flow for payment state changes` |
| `guide_step` | `Step 3: Configure callback URL in merchant settings` |
| `resource` | `Payment resource with CRUD operations` |
| `tool` | MCP tool (for MCP sources — not used in HTML) |
| `event` | `payment.completed event with payload schema` |

### Chunk text format

Each chunk stored in ChromaDB has this text structure:

```
[ENDPOINT] create_payment
POST /payments — Creates a new payment transaction. Accepts amount, currency, and metadata.
Source: https://docs.example.com/api/payments
Section: Create Payment
```

This format ensures the RAG retriever can match both keyword and semantic queries about the capability.

### Cross-page reconciliation

When the same operation is described across multiple documentation pages (e.g., a brief mention on an overview page and detailed docs on a reference page), `HTMLReconciler` uses Claude Sonnet to merge them into one canonical entry with a combined description and the highest confidence score.

Example: 5 pages with 3 near-duplicate `create_payment` entries → reconciled to 1 entry with merged description.

---

## 10. Troubleshooting

**Run status: `failed` with error "No pages fetched from entrypoints"**
- The entrypoint URL returned a non-200 response or non-HTML content type
- Check the URL is publicly accessible: `curl -I <entrypoint_url>`
- Verify it returns `Content-Type: text/html`

**`chunks_created: 0` with `changed: true` and no errors**
- All fetched pages were filtered as not relevant by Claude Haiku
- Review the entrypoints — they should point to technical API documentation, not marketing pages
- If running without `ANTHROPIC_API_KEY`, extraction is disabled — see [Section 6](#6-running-without-anthropic_api_key-offline-mode)

**`chunks_created: 0` with `changed: false`**
- Content hash matches the previous snapshot — the documentation has not changed since the last successful run
- This is expected behaviour; no action needed

**Chunks appear in ChromaDB but RAG does not retrieve them**
- The BM25 rebuild notification to integration-agent may have failed (logged at WARNING level)
- Trigger manually: `POST http://18.197.235.56:4003/api/v1/kb/rebuild-bm25`
- Verify chunk tags match the project tags used in RAG queries

**`low_confidence: true` chunks appearing in results**
- Claude assigned confidence < 0.7 for these capabilities
- Review the source documentation quality — sparse or ambiguous pages produce low-confidence extractions
- Low-confidence chunks are indexed but can be filtered in the retriever with `where={"low_confidence": False}`

**ChromaDB chunk ID collisions**
- Impossible by design: ingestion-platform uses `src_{source_code}-chunk-{n}`, integration-agent uses `{doc_id}-chunk-{n}`
- If you see unexpected overwrites, check that `source_code` values across sources are unique

---

## 11. Security Notes

> All rules from CLAUDE.md §1 (Data Usage) and §11 (Agentic AI Security) apply.

- **Only public documentation** may be registered as HTML sources. No client data, PII, or internal confidential content.
- HTML content is sent to the Anthropic Claude API for extraction — confirm data classification before registering a source.
- The system prompt for extraction explicitly instructs Claude to **ignore any instructions found in the HTML content** (prompt injection protection).
- Claude never writes to ChromaDB or MongoDB directly — all writes go through `IndexingService` after Pydantic schema validation.
- All capability outputs are validated against a strict JSON schema before being stored.
