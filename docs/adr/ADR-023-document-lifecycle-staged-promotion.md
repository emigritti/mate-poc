# ADR-023 — Document Lifecycle: Staged Approval & Explicit KB Promotion

| Field          | Value                                                                 |
|----------------|-----------------------------------------------------------------------|
| **Status**     | Accepted                                                              |
| **Date**       | 2026-03-18                                                            |
| **Deciders**   | Integration Mate Team                                                 |
| **Tags**       | document-lifecycle, hitl, rag, chroma, kb-promotion                  |
| **CLAUDE.md**  | §2 (Responsible AI), §4 (ADR), §11 (AI/Agentic Security)             |

---

## Context

HITL-approved documents were immediately written to ChromaDB (`approved_integrations`),
entering the RAG pool without explicit human intent. The `approve_doc()` function combined
two distinct actions in a single operation:

1. Recording the human approval decision in MongoDB.
2. Promoting the document into the vector store that influences all future LLM generation runs.

This coupling reduces human control over the RAG knowledge pool. A reviewer approving
document correctness may not intend — or may not be aware — that the approval immediately
and irrevocably affects RAG context for every subsequent generation run. This is
inconsistent with the Responsible AI principle of keeping a human-in-the-loop for
decisions that shape AI behaviour (CLAUDE.md §2).

---

## Decision

Decouple HITL approval from ChromaDB RAG promotion into two explicit, separately
triggered operations:

1. **Approval** (`POST /api/v1/documents/{doc_id}/approve`) — validates the document
   content and saves it to MongoDB with `kb_status="staged"`. No ChromaDB write occurs.

2. **KB Promotion** (`POST /api/v1/documents/{doc_id}/promote-to-kb`) — on explicit user
   action, writes the document to ChromaDB (`approved_integrations`) and updates
   MongoDB `kb_status` to `"promoted"`. Returns HTTP 409 if the document has already
   been promoted.

### Schema change

A new field `kb_status` is added to the `Document` model:

| Value        | Meaning                                                  |
|--------------|----------------------------------------------------------|
| `"staged"`   | HITL-approved; awaiting explicit KB promotion (default)  |
| `"promoted"` | Present in ChromaDB `approved_integrations` RAG pool     |

The field is backward-compatible: existing documents in MongoDB without `kb_status`
are treated as `"staged"` at read time.

### Affected components

| Component                    | Change                                                          |
|------------------------------|-----------------------------------------------------------------|
| `schemas.py`                 | Add `kb_status: str = "staged"` to `Document` model            |
| `main.py` — `approve_doc()`  | Remove ChromaDB write; set `kb_status="staged"`                 |
| `main.py`                    | Add `POST /api/v1/documents/{doc_id}/promote-to-kb` endpoint    |
| Frontend — Documents page    | Add "Promote to KB" button for staged documents                 |

---

## Alternatives Considered

| Alternative | Reason Rejected |
|-------------|-----------------|
| **Separate `staged_documents` MongoDB collection** | Increases migration complexity; requires dual-collection queries in list/search endpoints; no functional benefit over a status field on the existing collection |
| **Remove ChromaDB write without adding `kb_status`** | Leaves no state visibility — UI cannot distinguish documents pending promotion from those already promoted; no way to prevent duplicate promotion |
| **Keep current behaviour (immediate promotion on approval)** | Violates Responsible AI principle: human approves content correctness, not necessarily RAG pool inclusion; implicit side effect on LLM generation is not transparent |
| **Soft-delete pattern (tombstone in ChromaDB)** | Adds complexity without benefit; the goal is to delay the write, not to undo it after the fact |

---

## Consequences

### Positive

- Documents never enter the RAG pool without an explicit, deliberate human action.
- `kb_status` field provides clear UI state differentiation (staged vs. promoted),
  improving transparency of the document lifecycle.
- No breaking changes to existing API contracts — `approve_doc()` endpoint URL and
  response shape are unchanged.
- The schema change is backward-compatible (default `"staged"`) — no data migration
  required for existing MongoDB documents.
- HTTP 409 guard on `promote-to-kb` prevents accidental duplicate ChromaDB writes.

### Negative

- Users must perform an extra step after approval to make a document available to RAG
  (acceptable — explicit intent is the goal; the action is one click from the Documents page).
- Existing documents in MongoDB that were already promoted to ChromaDB will show
  `kb_status="staged"` until updated. A one-time migration or manual re-promotion may
  be needed for those documents (low risk for the PoC; documented in rollback section).

---

## Validation Plan

| Test ID  | Scenario                                                      | Expected                                      |
|----------|---------------------------------------------------------------|-----------------------------------------------|
| DL-001   | Call `approve_doc()` on a valid pending document              | MongoDB `kb_status="staged"`; ChromaDB empty  |
| DL-002   | Call `promote-to-kb` on a staged document                     | MongoDB `kb_status="promoted"`; document present in ChromaDB `approved_integrations` |
| DL-003   | Call `promote-to-kb` on an already-promoted document          | HTTP 409 returned; no duplicate ChromaDB write |
| DL-004   | Call `promote-to-kb` on a non-existent document ID            | HTTP 404 returned                             |
| DL-005   | Run RAG flow after approval but before promotion              | ChromaDB query returns no result for that document |
| DL-006   | Run RAG flow after promotion                                  | ChromaDB query returns the promoted document as context |
| DL-007   | Existing MongoDB document without `kb_status` field           | Read as `"staged"` (default); no error        |

Unit tests: `test_agent_flow.py` — assert `kb_status="staged"` after approve; assert
`kb_status="promoted"` and ChromaDB write called after promote-to-kb.

---

## Rollback Strategy

1. Revert `schemas.py` — remove `kb_status` field from the `Document` model.
2. Restore the ChromaDB write block inside `approve_doc()` in `main.py`.
3. Remove the `POST /api/v1/documents/{doc_id}/promote-to-kb` endpoint from `main.py`.
4. Revert frontend Documents page — remove the "Promote to KB" button and `kb_status`
   column.
5. For any documents that are now in MongoDB with `kb_status="staged"` but were intended
   to be in ChromaDB, manually trigger approval again after rollback (or run a one-time
   migration script to re-write them to ChromaDB).

Estimated rollback time: < 10 minutes. Risk: **LOW** — changes are confined to schema
definition, one endpoint addition, and frontend UI; no irreversible data operations.

---

## OWASP Mapping

| Risk | Mitigation |
|------|------------|
| A01 — Broken Access Control | `promote-to-kb` endpoint requires API key authentication (same guard as `approve_doc()`); unauthorized callers cannot inject documents into the RAG pool |
| A04 — Insecure Design | Explicit two-step lifecycle prevents implicit, unintended data flow from approval into AI generation context; aligns with Responsible AI transparency requirement |
| A10 — Server-Side Request Forgery (SSRF via RAG poisoning) | Decoupling approval from promotion adds a human gate before untrusted content can influence LLM generation, reducing the attack surface for adversarial document injection |

---

## Related ADRs

- **ADR-013** — MongoDB Persistence: `Document` model and `documents` collection that
  `kb_status` field extends.
- **ADR-019** — RAG Tag-Filtering with HITL Tag Confirmation Gate: the `approved_integrations`
  ChromaDB collection that `promote-to-kb` writes to.
- **ADR-021** — Best Practice Flow / KB Import: companion lifecycle for the `knowledge_base`
  ChromaDB collection (separate from `approved_integrations`).
- **ADR-022** — Nginx Gateway: all new endpoint traffic routes through the gateway on port 8080.
