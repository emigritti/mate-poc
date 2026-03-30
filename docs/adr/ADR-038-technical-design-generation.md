# ADR-038 — Two-Phase Document Generation: Technical Design after Functional Approval

**Status:** Accepted
**Date:** 2026-03-30
**Author:** Integration Mate Team

## Context

The Integration Mate PoC generates functional design documents via an LLM+RAG pipeline.
After functional HITL approval, architects need a technical design document.
The existing `Approval.doc_type` and `Document.doc_type` fields already support "technical".
Builds on the document lifecycle defined in ADR-023 (staged promotion) — `Document.doc_type` and `Approval.doc_type` already accept `"technical"`.

## Decision

Add a second generation phase triggered semi-automatically after functional approval:
- `CatalogEntry.technical_status` field tracks the technical doc lifecycle independently
- A new `POST /api/v1/agent/trigger-technical/{integration_id}` endpoint runs the pipeline
- The same HITL approve/reject+feedback loop reused (doc_type="technical")
- A separate meta-prompt file (`reusable-meta-prompt-technical.md`) drives the technical LLM call
- The approved functional spec is injected as primary context alongside KB RAG

## Alternatives Considered

- **Separate pipeline/models**: More isolation, too much duplication. Rejected.
- **Generic doc-type abstraction**: Extensible but over-engineering for current need. Rejected.
- **Automatic trigger on functional approval**: No explicit user control. Rejected.

## Consequences

### Positive
- `CatalogEntry` gets a new optional field `technical_status` (backward-compatible: defaults None)
- `sanitize_llm_output()` gains a `doc_type` parameter (backward-compatible: defaults "functional")
- New endpoint added; existing endpoints unchanged
- 8+ new unit tests added

### Negative / Risks
- `technical_status` field adds schema complexity (mitigated: Optional with default None — backward-compatible with existing MongoDB documents)

`technical_status` lifecycle:
```
None → TECH_PENDING → TECH_GENERATING → TECH_REVIEW → TECH_DONE
```
- `None`: functional doc not yet approved
- `TECH_PENDING`: functional approved, waiting for user to trigger
- `TECH_GENERATING`: generation in progress
- `TECH_REVIEW`: pending HITL approval
- `TECH_DONE`: technical doc approved

## Validation Plan

1. Unit tests cover all new functions (see `tests/test_technical_doc_generation.py`)
2. Manual E2E flow: approve functional → click button → approve technical → view spec
3. Reject+regenerate loop verified with feedback injection

## Rollback Strategy

- Remove `technical_status` field from `CatalogEntry` (Optional → ignored if absent in MongoDB)
- Remove new endpoint from `routers/agent.py`
- Remove new functions from `prompt_builder.py` and `agent_service.py`
- Zero impact on functional doc flow

## Security Considerations

- `{functional_spec}` injects LLM-generated content back into a new LLM call — a prompt injection surface. The approved functional spec is sanitized by `sanitize_human_content()` before storage (via the approval flow). Only sanitized content is injected as `{functional_spec}`.
- `doc_type` routing in `output_guard.py` uses a dict lookup with a known-safe key set (`"functional"` | `"technical"`); unknown values fall back to functional guard — no injection risk.
- Data classification: approved functional specs are "Internal" (CLAUDE.md §1). Do not inject confidential or client-sensitive data.
- Aligned with CLAUDE.md §11 (Agentic AI Security): LLM output is always treated as untrusted input; `sanitize_llm_output(doc_type="technical")` validates output structurally.
