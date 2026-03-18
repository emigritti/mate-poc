# KB Unified Document List — Design

**Date:** 2026-03-18
**Feature:** Unified Knowledge Base document list with text search
**Status:** Approved

---

## Goal

Add a unified document list section to the Knowledge Base page that displays both manually uploaded KB documents and promoted integration specs, with a single client-side text search box (name / tag) and the existing semantic search panel left unchanged.

---

## Approach

**Approach A — Client-side merge (two parallel API calls)**

At component mount, fetch both collections in parallel:

```js
Promise.all([API.kb.list(), API.documents.list()])
```

Filter `documents` to only those with `kb_status === "promoted"`, then normalize both arrays into a common `UnifiedDoc` shape. Client-side filter on name/tag with 200ms debounce. No backend changes required.

---

## Unified Document Schema

```js
{
  id: string,
  name: string,                        // filename or "{integration_id}-{doc_type}"
  tags: string[],
  uploadedAt: string,                  // ISO date
  source: "uploaded" | "integration", // determines badge color
  // optional fields
  fileType?: string,      // uploaded only
  fileSize?: number,      // uploaded only (bytes)
  chunkCount?: number,    // uploaded only
  docType?: string,       // integration only: "functional" | "technical"
  integrationId?: string  // integration only
}
```

---

## UI Layout

```
┌─────────────────────────────────────┐
│  Stats bar (unchanged)              │
├─────────────────────────────────────┤
│  Upload zone (unchanged)            │
├─────────────────────────────────────┤
│  ★ NEW SECTION                      │
│  [ 🔍 Cerca per nome o tag... ]     │
│  Unified table (uploaded+promoted)  │
├─────────────────────────────────────┤
│  Semantic search panel (unchanged)  │
└─────────────────────────────────────┘
```

---

## Table Columns

| Column  | Source |
|---------|--------|
| Nome    | `filename` (uploaded) / `{integration_id}-{doc_type}` (integration) |
| Tipo    | Badge "📤 Caricato" (grey) / "⚙️ Integrazione" (blue) |
| Tag     | Pill list |
| Data    | `uploaded_at` / `generated_at` |
| Azioni  | Delete (uploaded only), Preview (both) |

---

## Search Behavior

- Input: free text, case-insensitive
- Matches: `doc.name.includes(query)` OR `doc.tags.some(t => t.includes(query))`
- Debounce: 200ms
- Scope: entire unified list (both sources)

---

## Files to Modify

| File | Change |
|------|--------|
| `services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx` | Add unified list section, search box, normalizer + filter functions |
| `services/web-dashboard/src/api.js` | Already has `API.documents.list()` — no change needed |

## Files to Create / Update (tests)

| File | Change |
|------|--------|
| `services/integration-agent/tests/test_kb_endpoints.py` | Optionally extend with promoted-doc listing; mainly frontend logic is tested in-component |

---

## Testing Plan

- Unit: `normalizeKBDocs(kbList, docList)` returns correct unified array, excludes staged docs
- Unit: `filterDocs(docs, query)` — name match, tag match, case-insensitivity, empty query returns all
- Manual: verify badge colors, delete action visible only for uploaded docs, preview works for both

---

## Trade-offs

| Concern | Decision |
|---------|----------|
| Two API calls | Parallel via Promise.all — negligible latency for PoC scale |
| No backend changes | Accepted: YAGNI, reuses existing endpoints |
| Staged docs excluded | Filter `kb_status === "promoted"` client-side |
