# ADR-045 — UI Semantic Chunking for HTML Ingestion

**Status:** Accepted
**Date:** 2026-04-16
**Author:** Emiliano Gritti

---

## Context

The HTML ingestion pipeline (ADR-036, ADR-037) currently extracts generic `CanonicalCapability` objects
from HTML documentation pages using Claude Sonnet. The extraction treats each page as a flat list of
technical capabilities (endpoints, flows, guide steps) with a single `description` string and produces
**one `text` chunk per capability**.

This approach is insufficient for UI-rich documentation: application screens, backoffice pages, and
functional specifications carry structured UI semantics — input fields, CTAs, validation rules, actor
roles, and state machine transitions — that are lost when collapsed to narrative text.

**Problem:** When a functional user asks "what fields does the Product Publish screen show?" or
"what validation prevents publishing without a SKU?", the retriever cannot match these questions to
meaningful chunks because validation rules and state transitions are buried inside generic description
text, indistinguishable from prose.

**Goal:** Evolve the HTML extractor and chunker so that UI-semantic objects are extracted as first-class
structured data and indexed as **typed chunks** that can be retrieved with high precision.

---

## Decision

### 1. New `CapabilityKind.UI_SCREEN`

Add `UI_SCREEN = "ui_screen"` to `CapabilityKind`. A UI screen represents a complete application
screen or backoffice page with its associated actors, input fields, CTAs, validations, messages, and
state machine transitions.

### 2. Extended Claude extraction schema — `ui_context` field

Extend the JSON extraction schema accepted by `ClaudeService.extract_capabilities()` with an optional
`ui_context` block. When Claude identifies a screen/page in the documentation it populates:

```json
{
  "name": "Product Publish",
  "kind": "ui_screen",
  "description": "Screen for publishing products to the catalogue.",
  "confidence": 0.95,
  "source_trace": { "page_url": "...", "section": "Product Publish" },
  "ui_context": {
    "page": "Product Publish",
    "role": "Merchandiser",
    "fields": [
      { "name": "status", "type": "dropdown", "values": ["Draft", "Published"] }
    ],
    "actions": ["Save", "Publish"],
    "validations": ["SKU mandatory before publish"],
    "messages": ["Product published successfully"],
    "state_transitions": ["Draft -> Published"]
  }
}
```

Non-UI capabilities (endpoints, schemas, auth) continue to use the existing schema — `ui_context` is
always optional. Backward compatibility is fully preserved.

### 3. `HTMLNormalizer` stores `ui_context` in `CanonicalCapability.metadata`

`HTMLNormalizer._to_capability()` reads the `ui_context` dict from the raw extraction and stores it
unchanged in `CanonicalCapability.metadata["ui_context"]`. No other normalizer logic changes.

### 4. `CanonicalChunk.chunk_type` field — replaces hardcoded `"text"`

Add an explicit `chunk_type: str = "text"` field to `CanonicalChunk`.
`to_chroma_metadata()` uses `self.chunk_type` instead of the hardcoded literal `"text"`.

Three new `chunk_type` values are introduced for UI-semantic chunks:

| `chunk_type` | Content |
|---|---|
| `ui_flow_chunk` | Screen name, role, fields list, actions — the full page flow |
| `validation_rule_chunk` | One rule per chunk — highly retrievable for "what validates X?" queries |
| `state_transition_chunk` | One transition per chunk — highly retrievable for "what states does X have?" queries |

### 5. `HTMLChunker` generates typed multi-chunks per UI screen

For capabilities with `metadata["ui_context"]`:
- **1 `ui_flow_chunk`** — complete screen summary (page, role, fields, actions)
- **N `validation_rule_chunk`** — one per validation rule (may be 0)
- **N `state_transition_chunk`** — one per state transition (may be 0)

For all other capabilities: unchanged single `text` chunk.

Global chunk index is monotonically incremented across all capabilities and all sub-chunks, preserving
the `src_{source_code}-chunk-{index}` ID uniqueness contract.

---

## Alternatives Considered

### A. One capability per chunk type (flat list of atomic capabilities)
Extract validations, transitions, fields as separate `CanonicalCapability` objects from Claude.
**Rejected:** Requires major Claude schema redesign and produces many low-context micro-capabilities
whose association to the parent screen is lost. The `ui_context` block as metadata preserves the
parent-child relationship.

### B. Embed all UI context in a single rich text chunk
Keep 1:1 ratio but make chunk text richer (list every field, every validation, every transition).
**Rejected:** Retrieval precision degrades — "what validates SKU?" must score a 500-token chunk
containing unrelated fields and transitions. Typed chunks allow the retriever to surface the exact rule.

### C. Store UI context only in MongoDB, not in ChromaDB
**Rejected:** The integration-agent retriever reads from ChromaDB only. UI semantics must be in
ChromaDB to be retrievable at generation time.

---

## Consequences

**Positive:**
- Validation rules and state transitions become individually retrievable with high precision
- `chunk_type` metadata field enables future retriever filtering (e.g. "only return validation chunks")
- Fully backward-compatible: non-UI capabilities unchanged, new `ui_context` field optional
- Graceful degradation: `ui_context` absent → standard single `text` chunk (old behavior)
- No changes required in `integration-agent/services/retriever.py`

**Negative / Trade-offs:**
- One UI screen now generates 1 + N_validations + N_transitions chunks → larger index for UI-heavy sources
- Claude must recognise UI patterns in page text — quality depends on documentation clarity
- Added complexity in `HTMLChunker` (branching on `ui_context`)

---

## Validation Plan

1. Unit tests extended in `tests/test_html_collector.py`:
   - `TestHTMLChunker` — new cases: ui_flow_chunk generated, validation_rule_chunk per rule, state_transition_chunk per transition, text chunk for non-UI cap
   - `TestHTMLNormalizer` — ui_context stored in metadata
   - `CanonicalChunk.to_chroma_metadata()` uses `chunk_type` field
2. Regression: all existing 105+ ingestion-platform tests must pass
3. Manual end-to-end: ingest a UI-rich HTML page, verify chunk types in ChromaDB

---

## Rollback Strategy

Revert commits touching `capability.py`, `chunker.py`, `normalizer.py`, `claude_service.py`.
Existing ChromaDB data is unaffected (old chunks have `chunk_type: "text"` — still valid).
Re-ingest any affected sources to regenerate single-text chunks.

---

## Traceability

- Extends: ADR-036 (Ingestion Platform), ADR-037 (Claude semantic extraction)
- Affects: `services/ingestion-platform/models/capability.py`
- Affects: `services/ingestion-platform/services/claude_service.py`
- Affects: `services/ingestion-platform/collectors/html/normalizer.py`
- Affects: `services/ingestion-platform/collectors/html/chunker.py`
- Tests: `services/ingestion-platform/tests/test_html_collector.py`
