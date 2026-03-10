# ADR-018 — CORS Standardization Across All Services

| Field          | Value                                               |
|----------------|-----------------------------------------------------|
| **Status**     | Accepted                                            |
| **Date**       | 2026-03-06                                          |
| **Author**     | AI-assisted (Claude Code)                           |
| **Supersedes** | —                                                   |
| **OWASP**      | A05:2021 — Security Misconfiguration                |
| **CLAUDE.md**  | §10 (Security & Secure Coding), §12 (DevSecOps)     |

---

## Context

CORS configuration was inconsistent across services, with two confirmed violations of
the Fetch specification and browser security model:

### Violation 1 — `allow_origins=["*"]` + `allow_credentials=True` (PLM, PIM)

```python
# BEFORE — plm-mock-api/main.py, pim-mock-api/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # wildcard
    allow_credentials=True,   # credentials allowed
    ...
)
```

Per the [Fetch specification §3.2.2](https://fetch.spec.whatwg.org/#cors-protocol-and-credentials):
> "If request's credentials mode is 'include' ... and the response's [Access-Control-Allow-Origin]
> is `*`, return a network error."

This means browsers **reject** the CORS response for credentialed requests, making the
intended CORS policy non-functional.  Starlette also logs a warning about this combination.

### Violation 2 — Wildcard methods/headers (Security Middleware, DAM)

```python
# BEFORE — security-middleware/main.py, dam-mock-api/main.py
allow_methods=["*"],    # exposes DELETE, PATCH, OPTIONS unnecessarily
allow_headers=["*"],    # exposes any header the caller sends
```

Wildcard methods/headers violate the principle of least privilege (CLAUDE.md §10).

### Prior Art: DAM and Integration Agent

The DAM mock and Integration Agent already use the correct pattern:
- Origins from env var `CORS_ORIGINS` (comma-separated allowlist)
- Explicit method lists
- Explicit header lists

---

## Decision

**Standardize all services to the pattern already established in DAM and Integration Agent:**

1. **Origins**: read from `CORS_ORIGINS` env var with a safe local default; never use `["*"]`.
2. **Methods**: explicit allowlist (`GET`, `POST`, and per-service needs only).
3. **Headers**: `["Authorization", "Content-Type"]` for all services.
4. **Credentials**: `allow_credentials=True` is safe only with an explicit origins list.

### Per-service CORS Matrix

| Service | Before | After |
|---------|--------|-------|
| `integration-agent` | ✅ Already correct (explicit origins, explicit methods/headers) | No change |
| `security-middleware` | ✅ Origins correct; ❌ methods=`["*"]`, headers=`["*"]` | Restrict methods to `["GET", "POST", "OPTIONS"]`, headers to `["Authorization", "Content-Type"]` |
| `plm-mock-api` | ❌ `allow_origins=["*"]` + credentials | Origins from env var; methods `["GET", "POST", "OPTIONS"]`; headers explicit |
| `pim-mock-api` | ❌ `allow_origins=["*"]` + credentials | Origins from env var; methods `["GET", "POST", "OPTIONS"]`; headers explicit |
| `dam-mock-api` | ✅ Origins correct; ❌ methods=`["*"]`, headers=`["*"]` | Restrict methods to `["GET", "POST", "PATCH", "DELETE", "OPTIONS"]`, headers explicit |

---

## Alternatives Considered

| Alternative | Reason Rejected |
|------------|-----------------|
| **Wildcard origins in all services** | Violates CORS spec when combined with credentials; violates CLAUDE.md §10 (least privilege) |
| **Remove CORS middleware from mock APIs** | Mock APIs need CORS for Swagger UI cross-origin requests |
| **Environment-specific config** | Adds complexity; a single CORS_ORIGINS env var already provides runtime configurability |

---

## Consequences

### Positive
- All services comply with the Fetch specification
- Consistent, auditable CORS policy across the platform
- Least-privilege method/header exposure
- Mock APIs can be tested from any localhost port by adjusting `CORS_ORIGINS`

### Negative
- Local dev setups that access mock APIs from non-standard ports must add those origins
  to `CORS_ORIGINS` (or use the docker-compose defaults which cover `:8080` and `:3000`)

---

## Validation Plan

| Test ID | Scenario | Expected |
|---------|----------|----------|
| CORS-001 | Browser XHR to `/health` from `http://localhost:8080` | 200, `Access-Control-Allow-Origin: http://localhost:8080` |
| CORS-002 | Browser XHR to `/health` from `http://evil.com` | Browser blocks request (CORS error) |
| CORS-003 | `POST /auth/token` with `Content-Type: application/json` | 200 OK |
| CORS-004 | `DELETE /api/v1/admin/reset/all` on security-middleware | 405 Method Not Allowed (DELETE not in allowlist) |

Manual verification via browser DevTools Network tab.

---

## Rollback Strategy

Revert the changed `main.py` files to the prior commit.  No data migrations or
downtime required.  Risk: LOW (configuration change only).

---

## OWASP Mapping

| Risk | Mitigation |
|------|-----------|
| A05 — Security Misconfiguration (CORS wildcard) | Explicit origin allowlist via `CORS_ORIGINS` env var |
| A01 — Broken Access Control (wildcard methods) | Explicit method/header allowlists per service |
