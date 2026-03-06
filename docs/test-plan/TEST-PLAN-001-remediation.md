# TEST-PLAN-001 — Integration Mate PoC: Phase 1+3 Remediation Test Plan

| Field            | Value                                          |
|------------------|------------------------------------------------|
| **Version**      | 1.0                                            |
| **Date**         | 2026-03-06                                     |
| **Author**       | AI-assisted (Claude Code)                      |
| **Status**       | Active                                         |
| **ADRs covered** | ADR-012, ADR-013, ADR-014, ADR-015, ADR-016    |
| **CLAUDE.md ref**| §6 (Testing Strategy), §7 (Unit Tests)         |

---

## 1. Scope

This test plan covers the **Phase 1 (Correctness Foundation)** and
**Phase 3 (Security)** remediation work applied to the
`services/integration-agent` service and associated infrastructure changes
(docker-compose.yml, PLM/PIM/DAM mock APIs, secret management).

Out of scope: UI tests, Ollama model quality evaluation, production load tests.

---

## 2. Test Layers

### 2.1 Unit Tests (Primary Quality Gate)

Location: `services/integration-agent/tests/`

Run command:
```bash
cd services/integration-agent
pip install -r requirements.txt
pytest tests/ -v
```

| File                        | Module under test       | Test count | Priority |
|-----------------------------|-------------------------|------------|----------|
| `test_config.py`            | `config.py`             | 5          | HIGH     |
| `test_output_guard.py`      | `output_guard.py`       | 13         | CRITICAL |
| `test_prompt_builder.py`    | `prompt_builder.py`     | 9          | HIGH     |
| `test_requirements_upload.py`| `main.py` (endpoints)  | 10         | HIGH     |
| `test_agent_flow.py`        | `main.py` (flow logic)  | 12         | HIGH     |

**Total: ~49 unit test cases**

All tests must:
- Run without real infrastructure (MongoDB, ChromaDB, Ollama mocked)
- Complete in < 30 seconds total
- Be 100% deterministic (no random seeds, no time-dependent assertions)

---

### 2.2 Component / Endpoint Tests

The `test_requirements_upload.py` and `test_agent_flow.py` files use
`fastapi.testclient.TestClient` with mocked lifespan — these are
**component-level tests** that verify full HTTP request/response cycles
without real infrastructure.

---

### 2.3 Integration Tests (Manual / CI-gated)

These require the full Docker Compose stack (`docker-compose up`).

| Test ID | Scenario | Expected Result |
|---------|----------|-----------------|
| IT-001  | Upload CSV → agent run → approve | Document status → APPROVED, stored in MongoDB |
| IT-002  | Restart integration-agent container | MongoDB-persisted approvals survive restart |
| IT-003  | Trigger agent twice concurrently | Second call returns 409 Conflict |
| IT-004  | Upload CSV with `<script>` in description | Stored document contains no `<script>` tag |
| IT-005  | Call `/health` while LLM is generating | Returns 200 (event loop not blocked) |
| IT-006  | Catalog generator → integration-agent | `POST /api/v1/catalog/generate` accepted |
| IT-007  | Security middleware token flow | `POST /auth/token` → `GET /auth/validate` succeeds |
| IT-008  | MinIO with `S3_ACCESS_KEY` env override | MinIO starts with non-default credentials |

---

### 2.4 Security Tests

| Test ID | Threat | Verification Method |
|---------|--------|---------------------|
| SEC-001 | Stored XSS via LLM output | Unit test: `test_script_tag_stripped` |
| SEC-002 | XSS via human approval body | Unit test: `test_xss_stripped_in_human_content` |
| SEC-003 | LLM structural drift | Unit test: `test_missing_header_raises` |
| SEC-004 | S3 path traversal | Code review: `_safe_key()` in all s3_client.py files |
| SEC-005 | Secret exposure in VCS | `.gitignore` check: `.env` present |
| SEC-006 | Oversized CSV upload DoS | Unit test: `test_oversized_csv_returns_413` |
| SEC-007 | Non-CSV MIME spoofing | Unit test: `test_non_csv_mime_returns_415` |
| SEC-008 | Invalid UTF-8 injection | Unit test: `test_invalid_utf8_returns_400` |
| SEC-009 | JWT with expired token | Unit test (security-middleware): expired token → valid=False |
| SEC-010 | Missing required secrets at startup | Unit test: `test_fails_without_ollama_host` |

---

## 3. Acceptance Criteria

A phase is considered **DONE** only when all of the following pass:

- [ ] All unit tests pass (`pytest tests/ -v` exits 0)
- [ ] No `CRITICAL` or `HIGH` security finding unmitigated
- [ ] All IT-00x integration tests pass on a fresh `docker-compose up --build`
- [ ] All SEC-00x security tests verified
- [ ] ADRs created for every architectural decision made
- [ ] No secrets committed to VCS (`.env` absent from `git status`)
- [ ] Code review checklist signed off

---

## 4. OWASP Top 10 Coverage Matrix

| OWASP ID | Category                         | Mitigated By                                    |
|----------|----------------------------------|-------------------------------------------------|
| A01      | Broken Access Control            | `_require_token` auth guard; `_safe_key` S3     |
| A02      | Cryptographic Failures           | ADR-016; `.env` gitignored; JWT HS256            |
| A03      | Injection (XSS/HTML)             | ADR-015; `bleach` allowlist                     |
| A04      | Insecure Design                  | `asyncio.Lock` prevents resource exhaustion     |
| A05      | Security Misconfiguration        | ADR-016 fail-fast; explicit CORS origins         |
| A06      | Vulnerable & Outdated Components | `requirements.txt` pinned versions              |
| A07      | Auth & Session Failures          | JWT validation in security-middleware           |
| A08      | Software Integrity Failures      | Structural guard on LLM output                  |
| A09      | Security Logging Failures        | `logger.warning` on auth failure, LLM error    |
| A10      | Server-Side Request Forgery      | No user-controlled URLs in LLM calls            |

---

## 5. Test Environment Requirements

| Component          | Version / Image                 | Port  |
|--------------------|---------------------------------|-------|
| MongoDB            | `mongo:7`                       | 27017 |
| ChromaDB           | `chromadb/chroma:latest`        | 8000  |
| Ollama             | `ollama/ollama` + llama3.1:8b   | 11434 |
| MinIO              | `minio/minio`                   | 9000  |
| integration-agent  | Local build                     | 4003  |
| security-middleware| Local build                     | 4000  |
| catalog-generator  | Local build                     | 4004  |
| dam-mock           | Local build                     | 4005  |
| Python             | 3.12                            | —     |
| pytest             | 8.2.2                           | —     |

---

## 6. Test Execution Instructions

### Unit tests (no Docker required)
```bash
# From repo root
cd services/integration-agent

# Install test dependencies
pip install -r requirements.txt

# Run all unit tests with verbose output
pytest tests/ -v --tb=short

# Run only security-critical tests
pytest tests/test_output_guard.py -v
```

### Full stack integration tests
```bash
# Start the stack (first run pulls images + builds)
docker-compose up --build -d

# Wait for all services to become healthy
docker-compose ps

# Run integration scenarios IT-001 through IT-008 (manual or via Postman collection)
# Check logs for errors
docker-compose logs integration-agent --tail=50
```

### Cleanup
```bash
docker-compose down -v --rmi local
```

---

## 7. Known Limitations

1. `bleach` is in maintenance mode — should be replaced with `nh3` or
   `html-sanitizer` before production hardening.
2. The `asyncio.Lock` approach prevents concurrent agent runs globally —
   a job-queue (Celery/ARQ) is needed for multi-tenant production use.
3. ChromaDB `upsert` requires `ids` to be strings; numeric IDs from future
   CSV formats must be converted.
4. Unit tests for `test_agent_flow.py` rely on accessing `main._agent_lock`
   and `main._collection` directly — this is acceptable for PoC but should
   be refactored to proper dependency injection in production.

---

## 8. Traceability

| Requirement / Gap | ADR       | Test File                    | Status   |
|-------------------|-----------|------------------------------|----------|
| G-01 Async LLM    | ADR-012   | test_agent_flow.py           | ✅ Done  |
| G-02 MongoDB      | ADR-013   | test_requirements_upload.py  | ✅ Done  |
| G-03 Prompt build | ADR-014   | test_prompt_builder.py       | ✅ Done  |
| G-04 LLM guard    | ADR-015   | test_output_guard.py         | ✅ Done  |
| G-05 Secrets      | ADR-016   | test_config.py               | ✅ Done  |
| G-06 DAM service  | ADR-012   | (integration test IT-006)    | ✅ Done  |
| G-07 Security MW  | ADR-016   | (integration test IT-007)    | ✅ Done  |
| G-08 Catalog gen  | ADR-013   | (integration test IT-006)    | ✅ Done  |
| G-09 XSS guard    | ADR-015   | test_output_guard.py         | ✅ Done  |
| G-10 Concurrency  | ADR-012   | test_agent_flow.py           | ✅ Done  |
