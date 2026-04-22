# ADR-050 — Multi-Client Requirements Persistence and Global Project Selector

| Metadata   |                                                        |
|------------|--------------------------------------------------------|
| Status     | Accepted                                               |
| Date       | 2026-04-22                                             |
| Deciders   | Emiliano Gritti                                        |
| Tags       | Persistence, Multi-client, State, Frontend, MongoDB    |

---

## Context

The system had the `Project` model (prefix, client_name, domain) and `CatalogEntry.project_id` FK since ADR-025, but three gaps remained:

1. **Ephemeral requirements** — `state.parsed_requirements` lived only in memory. A container restart wiped all parsed requirements before they could be finalized. Users had to re-upload files after each restart.
2. **No global client selector in the UI** — the TopBar showed a mock static user dropdown. There was no way to switch between clients and see filtered catalog/documents/requirements without re-running the full upload+finalize flow.
3. **Agent trigger processed all projects** — `run_agentic_rag_flow` iterated over every `TAG_CONFIRMED` entry regardless of which project the user was working on.

---

## Decision

### Backend (FASE 1)

Add a `requirements` MongoDB collection to persist `Requirement` objects across restarts:

- `Requirement` schema extended with two optional fields: `upload_id` (UUID per upload session) and `project_id` (set on finalize).
- On `POST /requirements/upload`: generate `upload_id`, persist each parsed requirement to `requirements_col` with that ID, store `upload_id` in `state.current_upload_id`.
- On `POST /requirements/finalize`: set `project_id` on each requirement in MongoDB, clear `state.current_upload_id`.
- On `PATCH /requirements/{req_id}`: sync `mandatory` flag to MongoDB.
- `GET /requirements?project_id=X`: returns persisted requirements for a finalized project (queries MongoDB); without param returns in-memory session (backward-compatible).
- At startup in `lifespan`: reload the last unfinalized session (requirements with `project_id = null`) back into `state.parsed_requirements`.

### Frontend (FASE 2–4)

- New `ProjectContext` React context (with localStorage persistence of `active_project_id`).
- `App.jsx` wrapped with `<ProjectProvider>`.
- `TopBar.jsx`: replace mock static USERS selector with a live project dropdown powered by `API.projects.list()`.
- After requirements finalize (`ProjectModal.jsx`): auto-switch to the newly created/selected project.
- `CatalogPage`, `DocumentsPage`, `RequirementsPage`: re-fetch data whenever `activeProjectId` changes; pass `project_id` query param to `API.catalog.list()`.
- `AgentWorkspacePage`: pass `activeProjectId` to `API.agent.trigger()`.
- Backend `TriggerRequest` extended with optional `project_id`; `run_agentic_rag_flow` filters `TAG_CONFIRMED` entries (and the PENDING_TAG_REVIEW gate) by project when provided.

---

## Alternatives Considered

| Alternative | Why rejected |
|-------------|-------------|
| Per-project KB isolation (add `project_id` to KBDocument + ChromaDB filtering) | Scope too large; shared KB is acceptable for a single-user system and avoids ChromaDB schema migration |
| URL-based project routing (`/projects/:id/catalog`) | SPA with in-page navigation has no URL router; localStorage persistence is simpler and sufficient |
| Session-level project lock (one active project per browser session only) | Prevents multi-project workflow; dropdown with "All Projects" option is more flexible |
| Upload history UI panel | Single user, no operational need for audit UI; requirements are persisted for restart recovery, not reporting |

---

## Consequences

**Positive:**
- Requirements survive container restarts (operator no longer needs to re-upload after deploy).
- Project selector filters all downstream pages consistently.
- Agent trigger is scoped to active project, preventing accidental processing of other clients' entries.
- Fully backward-compatible: no `project_id` in trigger body → processes all entries (existing behavior).

**Negative / Trade-offs:**
- One new MongoDB collection (`requirements`) with two indexes.
- `Requirement` schema has two new optional fields; all existing code that constructs `Requirement` without them continues to work (default `None`).
- KB remains global — no per-client KB isolation (intentional constraint for this phase).

---

## Validation

See `docs/test-plan/` — five new test files:
- `test_requirements_persistence.py`
- `test_requirements_finalize_persistence.py`
- `test_requirements_patch_persistence.py`
- `test_get_requirements_by_project.py`
- `test_agent_trigger_project_scope.py`

End-to-end: restart integration-agent container → verify `state.parsed_requirements` repopulated; switch project in TopBar → verify CatalogPage and DocumentsPage filter accordingly.

---

## Rollback

1. `db.requirements.drop()` — drops the new collection; no other collections affected.
2. Revert 4 backend files: `schemas.py`, `db.py`, `state.py`, `routers/requirements.py`, `main.py`, `routers/agent.py`, `services/agent_service.py`.
3. Revert 5 frontend files: `ProjectContext.jsx` (delete), `App.jsx`, `TopBar.jsx`, `ProjectModal.jsx`, `api.js`, `CatalogPage.jsx`, `DocumentsPage.jsx`, `RequirementsPage.jsx`, `AgentWorkspacePage.jsx`.
4. `catalog_entries`, `approvals`, `documents`, `projects` collections are untouched.
