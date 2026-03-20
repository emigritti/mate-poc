# ADR-032 — Feedback Loop: Regenerate Rejected Documents

| Field        | Value                                                        |
|--------------|--------------------------------------------------------------|
| **Status**   | Accepted                                                     |
| **Date**     | 2026-03-20                                                   |
| **Tags**     | hitl, feedback-loop, regenerate, approvals, prompt, phase3   |

## Context
When a HITL reviewer rejects a generated document, the rejection feedback (stored in
`Approval.feedback`) is unused. There is no mechanism to incorporate reviewer corrections
into a new generation attempt. Rejected documents are dead-ends: the reviewer must
manually edit the document or wait for a full re-run of the agentic flow.

## Decision
Add `POST /api/v1/approvals/{id}/regenerate` endpoint in `routers/approvals.py`.

The endpoint:
1. Validates the approval exists, is `REJECTED`, and has non-empty `feedback`
2. Looks up the catalog entry and associated requirements from state
3. Calls `generate_integration_doc(entry, requirements, reviewer_feedback=feedback)`
4. Creates a new `PENDING` Approval with the regenerated content
5. Returns `{ new_approval_id, previous_approval_id }` so the UI can navigate to it

The reviewer feedback is injected into the prompt via `build_prompt(reviewer_feedback=...)`.
A `## PREVIOUS REJECTION FEEDBACK` block is prepended to the RAG context so the LLM
sees it before any retrieved examples.

The generation logic is extracted to `services/agent_service.py::generate_integration_doc()`
to avoid circular imports between `routers/agent.py` and `routers/approvals.py`.

## Alternatives Considered
- **Auto-retry on reject**: automatically trigger regeneration when reviewer clicks Reject — removes HITL timing control; reviewer may want to write detailed feedback before retrying
- **Stored-procedure replay**: re-run the entire agentic flow for a single entry — heavyweight; clears in-progress state for other entries
- **Edit-in-place**: allow reviewers to edit the document directly — already supported via the Approve flow with `final_markdown`; regenerate targets cases where the doc needs a full LLM rewrite

## Validation Plan
- Unit tests: `tests/test_approvals_regenerate.py` — 6 tests: 404 unknown, 409 pending, 409 approved, 409 no feedback, creates new PENDING approval, passes feedback to generator
- Unit tests: `tests/test_prompt_builder.py` — 3 tests: feedback present, feedback absent, whitespace-only feedback

## Rollback
Remove `regenerate_doc` endpoint from `routers/approvals.py`. Remove `reviewer_feedback` param from `build_prompt()`. No data migration needed.
