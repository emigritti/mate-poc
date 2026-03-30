# ADR-038 — Two-Phase Document Generation: Technical Design after Functional Approval

**Status:** Accepted
**Date:** 2026-03-30
**Author:** Integration Mate Team

## Context

The Integration Mate PoC generates functional design documents via an LLM+RAG pipeline.
After functional HITL approval, architects need a technical design document.
The existing `Approval.doc_type` and `Document.doc_type` fields already support "technical".

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

- `CatalogEntry` gets a new optional field `technical_status` (backward-compatible: defaults None)
- `sanitize_llm_output()` gains a `doc_type` parameter (backward-compatible: defaults "functional")
- New endpoint added; existing endpoints unchanged
- 8+ new unit tests added

## Validation Plan

1. Unit tests cover all new functions (see implementation plan Task 11)
2. Manual E2E flow: approve functional → click button → approve technical → view spec
3. Reject+regenerate loop verified with feedback injection

## Rollback Strategy

- Remove `technical_status` field from `CatalogEntry` (Optional → ignored if absent in MongoDB)
- Remove new endpoint from `routers/agent.py`
- Remove new functions from `prompt_builder.py` and `agent_service.py`
- Zero impact on functional doc flow
