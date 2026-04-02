# ADR-040 — AI-Assisted Section Improvement in HITL Approval Flow

**Status:** Accepted
**Date:** 2026-04-02
**Author:** Integration Mate Team
**Related:** ADR-023 (document lifecycle), ADR-032 (HITL approval flow), ADR-026 (backend decomposition)

---

## Context

The HITL approval page (ADR-023) allows a human reviewer to inspect and edit a generated Integration Spec before staging it. A section-level review modal was added (commit 45ab87e) to let the reviewer focus on individual markdown sections.

Reviewers frequently need to improve the quality of a specific section but lack the time or context to rewrite it from scratch. A targeted AI-assist capability — scoped strictly to a single section — would accelerate review without removing human control.

The key design challenge is keeping the human **in the loop at two gates**:
1. The reviewer must be able to see and edit the LLM improvement **prompt** before it is executed.
2. The reviewer must explicitly accept or reject the LLM suggestion before it touches the document.

---

## Decision

Introduce a two-phase AI-assist workflow within the existing section modal:

### Phase 1 — Prompt Preview (editable)
The backend generates a contextual improvement prompt from the section title + current content. The prompt is returned to the frontend **without executing it**. The reviewer reads, edits, and optionally adjusts the prompt before triggering the LLM.

### Phase 2 — Suggestion Review (accept/reject)
The frontend sends the (possibly edited) prompt + section context to a second endpoint that executes the LLM call and returns the improved section as raw markdown. The reviewer sees the suggestion in a separate read-only area and chooses to **accept** (overwrite the section) or **go back** (return to prompt editing without changing anything).

### API surface (two new stateless endpoints on `routers/approvals.py`)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/approvals/build-improvement-prompt` | Build improvement prompt from section context — no LLM call |
| `POST` | `/api/v1/approvals/run-improvement` | Execute LLM with provided prompt — returns suggested markdown |

Both endpoints are **stateless** (no approval ID, no DB writes). They operate purely on the section content passed in the request body.

---

## Alternatives Considered

### A — Single endpoint (build + execute in one call)
User never sees the prompt. Fast, but removes the prompt-editing gate. Rejected: violates CLAUDE.md §2 (keep human in the loop) and §11 (prompt injection surface is larger if the user cannot review/constrain the prompt before execution).

### B — Stream the LLM response
Lower latency UX. Adds complexity (SSE or chunked fetch, frontend streaming parser). Not needed at PoC stage. Can be added later.

### C — Reuse the existing `/agent/trigger` endpoint
Not applicable: that endpoint is bound to the full catalog-level generation pipeline, not section-level ad-hoc prompts.

---

## Consequences

**Positive:**
- Human remains in control at every gate (prompt edit + suggestion accept)
- Stateless design — no new DB collections, no state mutation until the user clicks Accept
- Endpoints are reusable for future section-level operations
- Graceful degradation: if LLM is unavailable the endpoint returns 503; UI shows error without losing the section content the user was editing

**Negative / Trade-offs:**
- Two round-trips to the backend (one per phase) instead of one
- LLM output is not sanitized through `output_guard.py` (not appropriate here — the reviewer is the final sanitizer; sanitization happens at `approve` time as today)

**Security:**
- LLM output treated as untrusted markdown (CLAUDE.md §11)
- The suggestion is displayed in a plain `<textarea>` — no innerHTML, no injection vector (ADR-017 compliant)
- No API key required for these endpoints (same policy as `/approvals/pending` — HITL UI is internal)

---

## Validation Plan
- Unit tests: `test_section_improvement.py` covering prompt-build and run-improvement endpoints
- Manual: full 3-phase flow (edit → prompt → suggestion → accept / back)
- Security: confirm suggestion rendered in textarea, not innerHTML

---

## Rollback Strategy
- Both endpoints are additive. Removing them requires deleting two route handlers and the two new schemas — no DB migration needed.
- Frontend modal state machine falls back to `edit` view if the feature is removed.
