# ADR-026 — Backend Decomposition (R15): Modular Routers, Services, and Shared State

| Field        | Value                                                |
|--------------|------------------------------------------------------|
| **Status**   | Accepted                                             |
| **Date**     | 2026-03-20                                           |
| **Deciders** | Integration Mate PoC team                            |
| **Tags**     | architecture, refactoring, routers, services, state  |

## Context

The `integration-agent` service began as a proof of concept. All business logic, HTTP routing,
LLM calls, RAG queries, and state management lived in a single 2065-line `main.py`. This
worked for rapid prototyping but made the codebase:

- Hard to navigate (scrolling hundreds of lines to find any endpoint)
- Difficult to unit-test in isolation (LLM calls, RAG, and HTTP handlers tightly coupled)
- Fragile under change (a bug in one domain could silently affect others)
- Non-compliant with CLAUDE.md §8 (clarity, small composable units, no hidden side effects)

The architecture analysis (R15) identified backend decomposition as a Phase 1 priority.

## Decision

Decompose `main.py` into a layered modular architecture:

### Layer 1 — Routers (`routers/`)
Eight domain-focused `APIRouter` modules, one per business domain:

| Module | Domain |
|--------|--------|
| `agent.py` | Agentic RAG flow (trigger, cancel, logs) |
| `requirements.py` | CSV upload and finalize |
| `projects.py` | Project CRUD (ADR-025) |
| `catalog.py` | Integration catalog queries |
| `approvals.py` | HITL approve/reject |
| `documents.py` | Final documents + KB promotion |
| `kb.py` | Knowledge Base management |
| `admin.py` | Reset, LLM settings, project docs |

Each router imports only what it needs. No router imports from another router.

### Layer 2 — Services (`services/`)
Three reusable business logic modules:

| Module | Responsibility |
|--------|---------------|
| `llm_service.py` | Ollama client with exponential-backoff retry (R13) |
| `rag_service.py` | ChromaDB tag-filtered + similarity queries; KB context assembly |
| `tag_service.py` | Category tag extraction; LLM tag suggestion |

Services are router-independent and directly unit-testable.

### Layer 3 — Shared State (`state.py`)
All in-memory globals consolidated into one module. Routers and services import from
`state` rather than from `main`, breaking the monolith coupling.

### Utilities (`utils.py`)
Small helpers shared across routers (e.g., `_now_iso()`), extracted to eliminate duplication.

### App Factory (`main.py`)
Reduced to ~213 lines: FastAPI app creation, lifespan (ChromaDB + MongoDB init), router
registration, and a backward-compatibility re-export block so existing tests require no modification.

## Alternatives Considered

### A. Keep the monolith, add comments and regions
- Rejected: does not improve testability or isolation; violates CLAUDE.md §8.

### B. Separate Python packages / microservices
- Rejected: over-engineering for current scale; adds deployment complexity without proportional benefit.

### C. Use FastAPI `include_router` with versioned prefixes
- Accepted as the approach: `APIRouter` modules are simple, idiomatic FastAPI, and support
  versioning when needed without structural changes.

## Validation Plan

- Run full test suite: `cd services/integration-agent && python -m pytest tests/ -v`
- Expected: all tests pass (backward-compatible re-exports in `main.py` ensure zero test changes)
- New dedicated unit tests required for each service module per CLAUDE.md §7

## Rollback Strategy

The decomposition is committed as a single atomic commit on `main-refactor`. To rollback:

1. `git revert 007932e` — reverts the decomposition commit
2. Alternatively, restore `main.py` from the `f019ed6` base commit

The backward-compatible re-exports in `main.py` mean any partial rollback (reverting only
selected routers) is also feasible without breaking tests.

## Trade-offs

| Benefit | Cost |
|---------|------|
| Each module <330 lines, easy to navigate | Total line count increases (distributed code is more verbose) |
| Services are independently unit-testable | Need to maintain import paths across 13+ new files |
| Router boundaries enforce domain isolation | `state.py` globals are still shared — no true DI yet |
| Backward-compat re-exports smooth migration | Re-export block must be maintained until tests are updated |

## Traceability

- Architecture analysis: R15 (Backend Decomposition)
- R13 (LLM Retry): implemented in `services/llm_service.py`
- Related ADRs: ADR-012 (httpx AsyncClient), ADR-022 (LLM overrides), ADR-025 (Projects)
- Test plan: `docs/test-plan/TEST-PLAN-001-remediation.md`
