# ADR-039 — Ingestion Sources UI: Gateway Route + Dashboard Page

**Status:** Accepted
**Date:** 2026-03-31
**Author:** Integration Mate Team
**Related:** ADR-022 (nginx gateway), ADR-036 (ingestion platform architecture), ADR-037 (Claude semantic extraction)
**OWASP:** A05:2021 Security Misconfiguration
**CLAUDE.md:** §4 (ADR mandatory), §10 (Security), §12 (DevSecOps)

---

## Context

The ingestion platform (`mate-ingestion-platform`, port 4006) was introduced in ADR-036 as a standalone service managing OpenAPI, HTML and MCP knowledge-base sources. It exposes a REST API for source CRUD, ingestion triggers, and run/snapshot audit — but:

1. **Not reachable via gateway.** The nginx gateway (ADR-022) proxied traffic only to the integration-agent, PLM mock, PIM mock, and n8n. No `/ingestion/` route existed, so the service was accessible only via direct port 4006 access, blocked by corporate firewalls and inconsistent with the single-origin architecture.

2. **No read endpoints for run/snapshot data.** The `GET /api/v1/runs/{run_id}` endpoint was referenced in n8n WF-02 for polling but never implemented. The `source_runs` and `source_snapshots` MongoDB collections were write-only from the UI perspective.

3. **No dashboard UI.** Operators had to use n8n or curl to register sources, trigger ingestion, and inspect results.

---

## Decision

### 1. Gateway: add `/ingestion/` nginx location block

Strip the `/ingestion/` prefix and forward to `http://mate-ingestion-platform:4006/`, following the same proxy pattern as the existing `/agent/` route. No extended timeout needed — ingest triggers return 202 immediately.

### 2. Backend: `routers/runs.py` — three read-only endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/runs/{run_id}` | Poll single run status (frontend + n8n WF-02) |
| `GET /api/v1/sources/{source_id}/runs` | Last 20 runs, sorted `started_at` desc |
| `GET /api/v1/sources/{source_id}/snapshots` | Last 10 snapshots, sorted `captured_at` desc |

All three are read-only, no auth required (consistent with PoC-level security posture).

### 3. Frontend: `IngestionSourcesPage.jsx`

New page wired into the "Knowledge Base" sidebar group with a dedicated `DatabaseZap` icon. Features:
- Stats bar (total, active, paused sources; last run timestamp)
- Source table with inline pause/activate toggle, trigger button, and two-step delete confirm
- Run history + snapshot panels (lazy-loaded, expand-on-demand per row)
- Register Source modal supporting OpenAPI, HTML, and MCP types with adaptive form labels
- Client-side polling loop (3s interval, 60s hard timeout) after trigger

### 4. Sidebar service health dot for ingestion platform

Added `Ingestion (4006)` to the services footer in the sidebar, checked via the existing `checkServices()` health-poll loop in `App.jsx`.

---

## Alternatives Considered

| Alternative | Reason rejected |
|---|---|
| Direct port 4006 browser access | Breaks same-origin policy, blocked by corporate firewalls, inconsistent with ADR-022 |
| n8n webhook relay for run polling | n8n is the orchestration layer, not a read gateway; adds unnecessary hop and n8n dependency for a UI concern |
| WebSocket for real-time run status | Over-engineered for PoC; 3s polling is sufficient and avoids WebSocket upgrade complexity in nginx |
| Embed n8n execution UI for logs | Unnecessary complexity; run errors displayed inline in run history panel covers the use case |

---

## Consequences

**Positive:**
- All ingestion management accessible via the single gateway port (8080) — consistent with ADR-022
- Dashboard operators can register, trigger, pause, and delete sources without touching n8n or curl
- Run history and snapshot diff summaries provide an audit trail for KB change tracking
- n8n WF-02 polling contract (`GET /api/v1/runs/{run_id}`) is now satisfied

**Negative:**
- Polling adds up to 3s visibility delay for run completion status
- Each expanded row in the source table triggers two MongoDB queries (runs + snapshots) — acceptable for PoC, not suitable for large source registries without pagination

---

## Security Considerations

- The `/ingestion/` gateway route does not require an API key (consistent with `/agent/`, `/plm/`, `/pim/` in PoC)
- Source deletion is irreversible — mitigated by the inline two-step confirm pattern (no accidental single-click delete)
- No PII in the source registry: only URLs, tags, and cron expressions
- LLM-generated `diff_summary` is rendered as plain text (`textContent`-safe via React JSX), not as `innerHTML` — no XSS risk

---

## Known Pre-existing Issue (out of scope)

`routers/ingest.py` uses `replace_one({"id": snap_id}, {"$set": {"is_current": False}})` when marking previous snapshots as non-current. This is incorrect — Motor's `replace_one` expects a replacement document, not an update operator. The `$set` key will be stored literally, corrupting the snapshot document. This bug pre-dates this ADR and does not block the UI implementation. It is documented here for awareness and must be fixed separately.

---

## Rollback

1. Remove the `/ingestion/` location block from `services/gateway/nginx.conf`
2. Remove `case 'ingestion-sources'` from `App.jsx` `renderPage()`

No database migration required. Source data and run history remain intact in MongoDB.

---

## Traceability

| Artifact | Location |
|---|---|
| nginx route | `services/gateway/nginx.conf` |
| Runs router | `services/ingestion-platform/routers/runs.py` |
| Main.py wiring | `services/ingestion-platform/main.py` |
| Frontend page | `services/web-dashboard/src/components/pages/IngestionSourcesPage.jsx` |
| API client | `services/web-dashboard/src/api.js` (ingestion namespace) |
| Sidebar | `services/web-dashboard/src/components/layout/Sidebar.jsx` |
| App routing | `services/web-dashboard/src/App.jsx` |
| Unit tests | `services/ingestion-platform/tests/test_runs_router.py` (17 tests) |
