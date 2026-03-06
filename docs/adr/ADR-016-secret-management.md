# ADR-016 — Secret Management: Environment Variables + Fail-Fast Validation

| Field       | Value                        |
|-------------|------------------------------|
| **Status**  | Accepted                     |
| **Date**    | 2026-03-06                   |
| **Author**  | AI-assisted (Claude Code)    |
| **Refs**    | CLAUDE.md §10; OWASP A02, A05; 12-Factor App §III |

---

## Context

The original codebase contained **hardcoded secrets** in multiple places:

| Location                     | Secret                        | Risk |
|------------------------------|-------------------------------|------|
| `docker-compose.yml` MinIO   | `minioadmin` / `minioadmin`   | Credential exposure in VCS |
| `plm-mock-api/s3_client.py`  | `os.getenv(..., "minioadmin")` | Default leaks into production |
| `pim-mock-api/s3_client.py`  | Same                          | Same |
| `main.py` (original)         | No auth at all                | Unauthenticated mutating endpoints |

This violates:
- OWASP A02:2021 – Cryptographic Failures (secrets in VCS)
- OWASP A05:2021 – Security Misconfiguration
- 12-Factor App §III – Config (store config in the environment)

---

## Decision

### 1. `pydantic-settings` for the integration-agent

`config.py` uses `pydantic_settings.BaseSettings` which:
- Reads values from environment variables (uppercase mapping automatic)
- Reads from `.env` file if present
- **Raises `ValidationError` at startup** for any missing required field
  (`ollama_host`, `mongo_uri` — both declared without defaults)

This is the **fail-fast** pattern: if a required secret is absent, the service
refuses to start rather than running in a misconfigured state.

### 2. `os.environ["KEY"]` (not `os.getenv`) for S3 clients

All three S3 clients (PLM, PIM, DAM) use `os.environ["S3_ENDPOINT"]` (raises
`KeyError` if absent) instead of `os.getenv("S3_ENDPOINT", "fallback")`.

### 3. `:-default` syntax in docker-compose.yml for PoC convenience

MinIO, PLM, PIM, DAM, security-middleware all use `${S3_ACCESS_KEY:-minioadmin}`
syntax so the stack starts without a `.env` file in PoC / local dev mode while
making the variable name explicit.  The `minioadmin` default is documented as
**PoC only** in the compose file comments.

### 4. `.env.example` checked into VCS; `.env` gitignored

`.env.example` contains placeholder values.  The actual `.env` is listed in
`.gitignore` and must never be committed.

### 5. JWT_SECRET for security-middleware

`JWT_SECRET` defaults to `"dev-only-change-in-production"` with a startup
warning logged when the default is in use.  This must be overridden via `.env`
before any non-development deployment.

---

## Alternatives Considered

| Option                          | Verdict    | Reason                                      |
|---------------------------------|------------|---------------------------------------------|
| HashiCorp Vault integration     | Deferred   | Correct for production; overkill for PoC    |
| AWS Secrets Manager             | Deferred   | Cloud-specific; PoC is cloud-agnostic       |
| Docker Swarm secrets            | Deferred   | Requires Swarm mode; Compose PoC uses bridge |
| Keep hardcoded fallbacks        | Rejected   | OWASP A02/A05 violation                     |

---

## Consequences

**Positive:**
- No secrets in VCS (`.env` gitignored)
- Fail-fast prevents misconfigured deployments running silently
- Explicit variable names in docker-compose make the config surface visible

**Negative / Trade-offs:**
- `:-default` in compose means MinIO still starts with weak credentials if
  `.env` is absent — this is intentional for PoC convenience but must be
  called out in onboarding documentation
- Rotating secrets requires container restart (no live reload)

---

## Validation Plan

`tests/test_config.py` covers:
- `Settings()` raises `ValidationError` if `OLLAMA_HOST` absent
- `Settings()` raises `ValidationError` if `MONGO_URI` absent
- `API_KEY` defaults to `None` (no auth in unauthenticated PoC mode)

---

## Rollback Strategy

Restore hardcoded values in `docker-compose.yml` and `s3_client.py`.
VCS secret exposure risk reintroduced; mark all previously committed
credentials as compromised and rotate immediately.
