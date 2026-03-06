# ADR-013 — MongoDB Persistence with motor (Async Driver)

| Field       | Value                     |
|-------------|---------------------------|
| **Status**  | Accepted                  |
| **Date**    | 2026-03-06                |
| **Author**  | AI-assisted (Claude Code) |
| **Refs**    | CLAUDE.md §10, ADR-012    |

---

## Context

The integration-agent previously stored all state (requirements catalogue,
approval workflow, generated documents) only in memory.  This means:
- All data is lost on container restart
- No audit trail for approvals / rejections
- Cannot support multi-instance deployments

The PoC already includes a MongoDB container (`mate-mongodb`) that was unused
by the agent service.

---

## Decision

Introduce **motor** (`motor==3.5.0`) as the async MongoDB driver inside
`integration-agent`.

### Data model

Three collections in database `integration_mate`:

| Collection        | Purpose                                          | Key index         |
|-------------------|--------------------------------------------------|-------------------|
| `catalog_entries` | Requirements parsed from uploaded CSV            | `id` (unique)     |
| `approvals`       | Approval workflow records + generated markdown   | `req_id` (unique) |
| `documents`       | Finalized approved functional specifications     | `approval_id`     |

### Startup pattern

`db.init_db()` is called from the FastAPI `lifespan` function with a retry
loop (10 attempts, 3 s delay) so the agent gracefully waits for MongoDB to
become ready before serving traffic.

### Write-through cache

On startup, `catalog_entries` and `approvals` are seeded into in-memory dicts
for O(1) read access.  Writes always go to both in-memory dict and MongoDB
(`upsert=True`) to keep them consistent.

---

## Alternatives Considered

| Option              | Verdict    | Reason                                        |
|---------------------|------------|-----------------------------------------------|
| SQLite (sync)       | Rejected   | Blocks event loop; no native async driver     |
| PostgreSQL + asyncpg| Deferred   | Better for relational queries; overkill for PoC |
| Redis               | Rejected   | Not suitable as primary persistence store     |
| Motor without cache | Rejected   | Every endpoint would incur a DB round-trip    |

---

## Consequences

**Positive:**
- State survives container restarts
- Full audit trail of approval decisions
- Async driver keeps the event loop free

**Negative / Trade-offs:**
- In-memory cache becomes stale if multiple agent instances run simultaneously
  (not a concern for single-instance PoC; use Redis cache in production)
- `serverSelectionTimeoutMS=3000` means a slow MongoDB causes 3 s startup delay

---

## Validation Plan

- Unit tests mock `motor` collections with `AsyncMock` — no real DB required
- Integration test: restart integration-agent container and verify state survives

---

## Rollback Strategy

Remove `motor` from `requirements.txt`, restore in-memory-only data structures.
All persisted data will be lost on rollback.
