# RAG Tag-Filtering Design

**Date:** 2026-03-13
**Status:** Approved
**Author:** AI-assisted (Claude Sonnet 4.6) — human-in-the-loop validated

---

## Problem

The current RAG implementation queries ChromaDB with pure vector similarity and no metadata filtering.
Full approved documents (~4800 chars each) are injected as context, causing LLM timeouts on CPU instances (EC2 t3.2xlarge).
A char-truncation workaround (`ollama_rag_max_chars=1500`) was added as a temporary fix but degrades RAG quality.

The root issue is **relevance**: retrieved examples may be structurally similar by embedding but belong to completely different integration categories, providing low-value context that wastes tokens.

---

## Goal

Improve RAG precision by filtering ChromaDB results on confirmed integration tags, validated by the HITL reviewer before generation starts.

**PoC constraints accepted:** slightly lower document quality is acceptable; reliability and no-timeout are the priority.

---

## Approach Selected

**Approach 1 — Tag-gate as pre-generation state** (approved over 2 alternatives).

Tags are proposed automatically (from requirement categories + LLM), confirmed by the user via UI, and stored on `CatalogEntry` before generation is triggered.

---

## Section 1: State Machine & Data Model

### CatalogEntry status transitions

```
[upload requirements]
        ↓
PENDING_TAG_REVIEW   ← initial state after parsing
        ↓  POST /confirm-tags
   TAG_CONFIRMED     ← tags confirmed, ready for generation
        ↓  POST /trigger
   PROCESSING        ← LLM generation in progress
        ↓
     DONE            ← all documents generated
```

The trigger endpoint returns `409` if `status ≠ TAG_CONFIRMED`.

### Schema changes (`schemas.py`)

```python
class CatalogEntry(BaseModel):
    id: str
    name: str
    type: str
    source: Dict[str, str]
    target: Dict[str, str]
    requirements: List[str]
    status: str          # now includes PENDING_TAG_REVIEW, TAG_CONFIRMED
    tags: List[str] = [] # confirmed tags (max 5 = 2 auto + 3 user)
    created_at: str
```

### ChromaDB metadata (at approval time)

```python
metadatas=[{
    "integration_id": ...,
    "type": ...,
    "tags_csv": ",".join(confirmed_tags),  # new field
}]
```

---

## Section 2: New Endpoints

### GET `/api/v1/catalog/integrations/{id}/suggest-tags`

Returns proposed tags for an integration before confirmation.

**Logic:**
1. Extract unique `category` values from the integration's requirements (deterministic)
2. Call LLM with a lightweight dedicated prompt → up to 2 additional tags
3. Deduplicate + merge, max 5 suggested total

**LLM prompt (tag suggestion):**
```
Given this integration between {source} and {target} with these requirements:
{req_descriptions_truncated_500_chars}
Suggest up to 2 short tags (1-3 words each) that best categorize this integration.
Reply with a JSON array only. Example: ["Data Sync", "Real-time"]
```

~100 prompt tokens, ~20 response tokens → ~5s on CPU.

**Response:**
```json
{
  "integration_id": "erp-plm-001",
  "suggested_tags": ["Enrichment INIT", "Product Collection", "PLM"],
  "source": {
    "from_categories": ["Enrichment INIT", "Product Collection"],
    "from_llm": ["PLM"]
  }
}
```

---

### POST `/api/v1/catalog/integrations/{id}/confirm-tags`

Stores confirmed tags and transitions status to `TAG_CONFIRMED`.

**Request body:**
```json
{
  "tags": ["Enrichment INIT", "PLM", "my-custom-tag"]
}
```

**Validation:**
- `tags`: list of strings, min 1 element, max 5 elements
- Each tag: max 50 chars, whitespace stripped, blank tags discarded
- `status` must be `PENDING_TAG_REVIEW` → else `409`

**Effect:**
- `CatalogEntry.tags = confirmed_tags`
- `CatalogEntry.status = "TAG_CONFIRMED"`
- Persisted to MongoDB

**Response:**
```json
{
  "status": "success",
  "integration_id": "erp-plm-001",
  "confirmed_tags": ["Enrichment INIT", "PLM", "my-custom-tag"]
}
```

---

## Section 3: RAG Filtering Logic

### Query strategy: primary tag → similarity fallback → warning

```python
async def _query_rag_with_tags(query_text: str, tags: list[str]) -> tuple[str, str]:
    """
    Returns (rag_context, source_label).
    source_label: "tag_filtered" | "similarity_fallback" | "none"
    """
    if not collection:
        return "", "none"

    # Step 1: tag-filtered query (primary tag = first confirmed tag)
    if tags:
        results = collection.query(
            query_texts=[query_text],
            n_results=2,
            where={"tags_csv": {"$contains": tags[0]}}
        )
        docs = (results or {}).get("documents", [[]])[0]
        if docs:
            return _build_rag_context(docs), "tag_filtered"

    # Step 2: fallback to similarity search, no tag filter
    log_agent(f"[RAG] No tagged examples for {tags} — fallback to similarity search.")
    results = collection.query(query_texts=[query_text], n_results=2)
    docs = (results or {}).get("documents", [[]])[0]
    if docs:
        return _build_rag_context(docs), "similarity_fallback"

    return "", "none"


def _build_rag_context(docs: list[str]) -> str:
    """Truncate RAG context to prevent prompt overflow (reuses existing logic)."""
    raw = "\n---\n".join(docs)
    max_chars = settings.ollama_rag_max_chars
    if len(raw) > max_chars:
        log_agent(f"[RAG] Context truncated to {max_chars} chars (was {len(raw)}).")
        return raw[:max_chars]
    return raw
```

**Log in main flow:**
```python
rag_context, rag_source = await _query_rag_with_tags(query_text, entry.tags)
log_agent(f"[RAG] Source: {rag_source} | chars: {len(rag_context)}")
```

---

## Section 4: UI Changes

### New tag-confirmation step

After parsing and before generation, a confirmation panel is shown for each integration in `PENDING_TAG_REVIEW`:

```
┌─────────────────────────────────────────────────────────┐
│ ERP → PLM Integration                                   │
│                                                         │
│ Suggested tags:                                         │
│  [✓ Enrichment INIT]  [✓ Product Collection]  [✓ PLM]  │
│  (click to deselect)                                    │
│                                                         │
│ Add custom tag (max 3):  [___________] [+ Add]          │
│                                                         │
│                              [Confirm Tags →]           │
└─────────────────────────────────────────────────────────┘
```

### `app.js` changes

1. After parsing, call `GET /suggest-tags` for each integration → render confirmation panel
2. "Confirm Tags" → `POST /confirm-tags` → update UI chip to green "Tags confirmed ✓"
3. "Generate" button enabled only when `allIntegrations.every(i => i.status === "TAG_CONFIRMED")`
4. All rendered values use `escapeHtml()` (ADR-017 compliance)

No new frontend dependencies — vanilla JS + existing CSS.

---

## Section 5: Testing Plan

### New unit test files

**`test_tag_suggestion.py`**

| Test | What it verifies |
|------|-----------------|
| `test_suggest_tags_from_categories` | Extracts unique categories from requirements |
| `test_suggest_tags_dedup` | No duplicates between category-tags and LLM-tags |
| `test_suggest_tags_llm_parse_valid` | LLM returns valid JSON array → parsed correctly |
| `test_suggest_tags_llm_parse_invalid` | LLM returns malformed text → fallback to category-tags only |
| `test_suggest_tags_max_5` | Never returns more than 5 tags |

**`test_confirm_tags.py`**

| Test | What it verifies |
|------|-----------------|
| `test_confirm_tags_ok` | Status → TAG_CONFIRMED, tags persisted |
| `test_confirm_tags_max_exceeded` | List > 5 tags → 422 |
| `test_confirm_tags_wrong_status` | Status ≠ PENDING_TAG_REVIEW → 409 |
| `test_confirm_tags_empty_tag_stripped` | Whitespace-only tags discarded |

**`test_rag_filtering.py`**

| Test | What it verifies |
|------|-----------------|
| `test_rag_tag_filtered_hit` | Tag match → source="tag_filtered" |
| `test_rag_tag_filtered_miss_fallback` | No match → fallback + warning logged |
| `test_rag_no_collection` | ChromaDB unavailable → ("", "none") |
| `test_build_rag_context_truncation` | Text > max_chars → truncated |

**`test_trigger_gate.py`**

| Test | What it verifies |
|------|-----------------|
| `test_trigger_blocked_if_pending_tag_review` | Status PENDING_TAG_REVIEW → 409 |
| `test_trigger_allowed_if_tag_confirmed` | Status TAG_CONFIRMED → flow starts |

### Existing tests

50/50 current tests expected to remain green. `test_agent_flow.py` may require seed status update from `"PROCESSING"` to `"TAG_CONFIRMED"`.

---

## ADR Required

A new ADR is required (ADR-019) covering:
- Introduction of tag-gated HITL step before generation
- ChromaDB metadata schema change (`tags_csv`)
- State machine extension on `CatalogEntry`

---

## Rollback

- Tags are additive metadata — removing them reverts ChromaDB queries to similarity-only
- Status machine change is backward compatible: existing `PROCESSING`/`DONE` entries unaffected
- Feature flag option: `OLLAMA_RAG_TAG_FILTER_ENABLED=false` skips tag filtering, uses similarity fallback only
