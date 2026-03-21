# TEST-PLAN-001 — Integration Mate PoC: Remediation Test Plan

| Field            | Value                                                                                    |
|------------------|------------------------------------------------------------------------------------------|
| **Version**      | 4.0                                                                                      |
| **Date**         | 2026-03-21                                                                               |
| **Author**       | AI-assisted (Claude Code)                                                                |
| **Status**       | Active                                                                                   |
| **ADRs covered** | ADR-012 through ADR-024                                                                  |
| **CLAUDE.md ref**| §6 (Testing Strategy), §7 (Unit Tests), §10 (Security)                                  |

---

## Change Log

| Version | Date       | Changes |
|---------|------------|---------|
| 1.0     | 2026-03-06 | Initial test plan (Phase 1+3 remediation) |
| 2.0     | 2026-03-06 | Added Phase 4 (security review) findings: F-01..F-10 remediation tests; ADR-017 (XSS), ADR-018 (CORS); fixed SEC-003 reference; added SEC-011..SEC-015 |
| 3.0     | 2026-03-19 | Updated test count to 171 (added KB, RAG, tag, LLM settings, lifecycle test files); added IT-011 (KB URL happy path); added SEC-017 (SSRF guard); updated OWASP A10 mitigation; ADRs covered extended to ADR-024 |
| 4.0     | 2026-03-21 | Updated test count to 274 (Phase 4 polish: R4 sub-component decomposition tests, R18 agent progress tests, R19 event_logger tests); ADRs covered extended to ADR-033 |

---

## 1. Scope

This test plan covers:

- **Phase 1** (Correctness Foundation) and **Phase 3** (Security) remediation work
  applied to `services/integration-agent`.
- **Phase 4** (Security Review) findings F-01 through F-10 identified during
  CLAUDE.md-mandated security review (2026-03-06).

**Phase 4 findings covered:**

| ID    | Severity | Description |
|-------|----------|-------------|
| F-01  | CRITICAL | Test `test_missing_header_raises` had wrong assertion (preamble stripping is correct) |
| F-02  | CRITICAL | Test referenced `agent_main._collection` (correct: `agent_main.collection`) |
| F-03  | CRITICAL | Test used non-existent endpoint `/api/v1/agent/run` (correct: `/api/v1/agent/trigger`) |
| F-04  | CRITICAL | XSS in agent logs terminal via `innerHTML` without escaping |
| F-05  | CRITICAL | XSS in requirements table via `innerHTML` without escaping |
| F-06  | HIGH     | XSS in approval editor `<textarea>` injection |
| F-07  | HIGH     | PLM/PIM CORS: `allow_origins=["*"]` + `allow_credentials=True` (Fetch spec violation) |
| F-08  | HIGH     | Security middleware / DAM: CORS wildcard methods/headers |
| F-09  | MEDIUM   | `str.format()` in prompt_builder raises on malformed template or `{...}` in user input |
| F-10  | MEDIUM   | API key comparison not constant-time (timing attack surface) |

Out of scope: UI E2E automation tests, Ollama model quality evaluation, production load tests.

---

## 2. Test Layers

### 2.1 Unit Tests (Primary Quality Gate)

**Location:** `services/integration-agent/tests/`

**Run command:**
```bash
cd services/integration-agent
pip install -r requirements.txt
pytest tests/ -v
```

| File                            | Module under test                  | Tests | Priority |
|---------------------------------|------------------------------------|-------|----------|
| `test_config.py`                | `config.py`                        | 10    | HIGH     |
| `test_output_guard.py`          | `output_guard.py`                  | 14    | CRITICAL |
| `test_prompt_builder.py`        | `prompt_builder.py`                | 13    | HIGH     |
| `test_requirements_upload.py`   | `main.py` (upload endpoints)       | 10    | HIGH     |
| `test_agent_flow.py`            | `main.py` (agent flow + trigger)   | 23    | HIGH     |
| `test_document_parser.py`       | `document_parser.py`               | 22    | HIGH     |
| `test_kb_endpoints.py`          | `main.py` (KB endpoints)           | 10    | HIGH     |
| `test_confirm_tags.py`          | `main.py` (tag confirmation)       | 6     | HIGH     |
| `test_suggest_tags_endpoint.py` | `main.py` (tag suggestion)         | 4     | MEDIUM   |
| `test_tag_suggestion.py`        | `main.py` (LLM tag suggest)        | 9     | MEDIUM   |
| `test_rag_filtering.py`         | `main.py` (RAG tag filter)         | 6     | HIGH     |
| `test_llm_settings.py`          | `main.py` (LLM settings admin)     | 7     | MEDIUM   |
| `test_log_agent.py`             | `main.py` (agent logger)           | 16    | MEDIUM   |
| `test_log_schemas.py`           | `schemas.py` (log models)          | 4     | LOW      |
| `test_project_docs.py`          | `main.py` (admin docs endpoint)    | 7     | LOW      |
| `test_trigger_gate.py`          | `main.py` (trigger pre-conditions) | 2     | HIGH     |
| `test_upload_creates_catalog.py`| `main.py` (catalog creation)       | 2     | HIGH     |
| `test_schemas.py`               | `schemas.py`                       | 6     | MEDIUM   |

**Total: 171 unit test cases** (all passing as of 2026-03-19)

All tests must:
- Run without real infrastructure (MongoDB, ChromaDB, Ollama mocked)
- Complete in < 30 seconds total
- Be 100% deterministic (no random seeds, no time-dependent assertions)

---

### 2.2 Component / Endpoint Tests

`test_requirements_upload.py` and `test_agent_flow.py` use `fastapi.testclient.TestClient`
with mocked lifespan — **component-level tests** verifying full HTTP request/response
cycles without real infrastructure.

---

### 2.3 Integration Tests (Manual / CI-gated)

Require the full Docker Compose stack (`docker-compose up`).

| Test ID | Scenario | Expected Result |
|---------|----------|-----------------|
| IT-001  | Upload CSV → agent run → approve | Document status → APPROVED, stored in MongoDB |
| IT-002  | Restart integration-agent container | MongoDB-persisted approvals survive restart |
| IT-003  | Trigger agent twice concurrently | Second call returns 409 Conflict |
| IT-004  | Upload CSV with `<script>` in Description | Stored document contains no `<script>` tag |
| IT-005  | Call `/health` while LLM is generating | Returns 200 (event loop not blocked) |
| IT-006  | Catalog generator → integration-agent | `POST /api/v1/catalog/generate` accepted |
| IT-007  | Security middleware token flow | `POST /auth/token` → `GET /auth/validate` succeeds |
| IT-008  | MinIO with `S3_ACCESS_KEY` env override | MinIO starts with non-default credentials |
| IT-009  | Upload CSV with `<script>` in Description; view requirements page | Dashboard table shows literal `<script>` text, no alert |
| IT-010  | CORS preflight from `http://localhost:8080` to PLM mock | 200, explicit origin header returned (not wildcard) |
| IT-011  | Add KB URL `https://docs.example.com/api` with tag `salsify`; trigger generation with `salsify`-tagged integration | URL content appears in agent logs under `[KB-URL]`; generation completes successfully |

---

### 2.4 Security Tests

| Test ID | Threat | Verification Method | Status |
|---------|--------|---------------------|--------|
| SEC-001 | Stored XSS via LLM output (server-side) | Unit test: `test_script_tag_stripped` | ✅ |
| SEC-002 | XSS via human approval body (server-side) | Unit test: `test_xss_stripped_in_human_content` | ✅ |
| SEC-003 | LLM structural drift — preamble stripping | Unit test: `test_preamble_stripped_when_heading_found_in_body` | ✅ Fixed (was F-01) |
| SEC-003b| LLM output missing heading entirely | Unit test: `test_heading_absent_raises` | ✅ New |
| SEC-004 | S3 path traversal | Code review: `_safe_key()` in all s3_client.py | ✅ |
| SEC-005 | Secret exposure in VCS | `.gitignore` check: `.env` absent from git status | ✅ |
| SEC-006 | Oversized CSV upload DoS | Unit test: `test_oversized_csv_returns_413` | ✅ |
| SEC-007 | Non-CSV MIME spoofing | Unit test: `test_non_csv_mime_returns_415` | ✅ |
| SEC-008 | Invalid UTF-8 injection | Unit test: `test_invalid_utf8_returns_400` | ✅ |
| SEC-009 | JWT with expired token | Integration test IT-007 | ✅ |
| SEC-010 | Missing required secrets at startup | Unit test: `test_fails_without_ollama_host` | ✅ |
| SEC-011 | XSS via requirements table (frontend) | Integration test: IT-009; ADR-017 | ✅ Fixed (F-05) |
| SEC-012 | XSS via agent logs terminal (frontend) | Integration test: upload CSV with `<img onerror>`, run agent, inspect logs | ✅ Fixed (F-04) |
| SEC-013 | XSS via textarea injection `</textarea>` | Integration test: approve content with `</textarea>`, verify no breakout | ✅ Fixed (F-06) |
| SEC-014 | CORS wildcard + credentials (Fetch spec) | Code review: no `allow_origins=["*"]` + `allow_credentials=True` | ✅ Fixed (F-07) |
| SEC-015 | Template injection via `{...}` in system name | Unit test: `test_system_name_with_format_specifiers_does_not_raise` | ✅ Fixed (F-09) |
| SEC-016 | API key timing attack | Code review: `hmac.compare_digest()` used | ✅ Fixed (F-10) |
| SEC-017 | SSRF via KB URL registration | Unit/manual: `POST /api/v1/kb/add-url {"url":"http://127.0.0.1/admin"}` → expect 400; private ranges blocked before fetch | ✅ ADR-024 |

---

## 3. Acceptance Criteria

A phase is considered **DONE** only when all of the following pass:

- [ ] All unit tests pass (`pytest tests/ -v` exits 0) — **274 tests expected**
- [ ] No `CRITICAL` or `HIGH` security finding unmitigated
- [ ] All IT-00x integration tests pass on a fresh `docker-compose up --build`
- [ ] All SEC-00x security tests verified
- [ ] ADRs created for every architectural decision made
- [ ] No secrets committed to VCS (`.env` absent from `git status`)
- [ ] Code review checklist signed off

---

## 4. OWASP Top 10 Coverage Matrix

| OWASP ID | Category                         | Mitigated By                                                   |
|----------|----------------------------------|----------------------------------------------------------------|
| A01      | Broken Access Control            | `_require_token` auth guard; `_safe_key` S3; explicit CORS origins (ADR-018) |
| A02      | Cryptographic Failures           | ADR-016; `.env` gitignored; JWT HS256                          |
| A03      | Injection (XSS/HTML)             | ADR-015 `bleach` (server); ADR-017 `escapeHtml()` (frontend)  |
| A04      | Insecure Design                  | `asyncio.Lock` prevents resource exhaustion                    |
| A05      | Security Misconfiguration        | ADR-016 fail-fast; explicit CORS origins + methods (ADR-018)   |
| A06      | Vulnerable & Outdated Components | `requirements.txt` pinned versions                             |
| A07      | Auth & Session Failures          | JWT validation; `hmac.compare_digest()` constant-time (F-10)  |
| A08      | Software Integrity Failures      | Structural guard on LLM output; HITL approval gate            |
| A09      | Security Logging Failures        | `logger.warning` on auth failure, LLM error, guard rejection  |
| A10      | Server-Side Request Forgery      | KB URL add-url endpoint blocks private/loopback IP ranges (ADR-024); `http/https` scheme enforced |

---

## 5. Test Environment Requirements

| Component           | Version / Image                 | Port  |
|---------------------|---------------------------------|-------|
| MongoDB             | `mongo:7`                       | 27017 |
| ChromaDB            | `chromadb/chroma:latest`        | 8000  |
| Ollama              | `ollama/ollama` + llama3.1:8b   | 11434 |
| MinIO               | `minio/minio`                   | 9000  |
| integration-agent   | Local build                     | 4003  |
| security-middleware | Local build                     | 4000  |
| catalog-generator   | Local build                     | 4004  |
| dam-mock            | Local build                     | 4005  |
| Python              | 3.12                            | —     |
| pytest              | 8.2.2                           | —     |

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
pytest tests/test_output_guard.py tests/test_prompt_builder.py -v
```

### Full stack integration tests
```bash
# Start the stack (first run pulls images + builds)
docker-compose up --build -d

# Wait for all services to become healthy
docker-compose ps

# Run integration scenarios IT-001 through IT-010
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
4. Frontend XSS tests (SEC-011, SEC-012, SEC-013) are manual — no automated
   E2E test suite is in scope for this PoC.
5. The sequential `str.replace()` approach in `prompt_builder.py` (F-09) has
   a known limitation: if `source_system` contains `{target_system}` literally,
   that pattern will be expanded by the subsequent replace. This is documented
   and acceptable for the PoC; production should use a proper templating engine.

---

## 8. Traceability

| Requirement / Gap          | ADR     | Test File                      | Status   |
|----------------------------|---------|--------------------------------|----------|
| G-01 Async LLM             | ADR-012 | test_agent_flow.py             | ✅ Done  |
| G-02 MongoDB               | ADR-013 | test_requirements_upload.py    | ✅ Done  |
| G-03 Prompt build          | ADR-014 | test_prompt_builder.py         | ✅ Done  |
| G-04 LLM guard             | ADR-015 | test_output_guard.py           | ✅ Done  |
| G-05 Secrets               | ADR-016 | test_config.py                 | ✅ Done  |
| G-06 DAM service           | ADR-012 | (integration test IT-006)      | ✅ Done  |
| G-07 Security MW           | ADR-016 | (integration test IT-007)      | ✅ Done  |
| G-08 Catalog gen           | ADR-013 | (integration test IT-006)      | ✅ Done  |
| G-09 XSS guard (server)    | ADR-015 | test_output_guard.py           | ✅ Done  |
| G-10 Concurrency           | ADR-012 | test_agent_flow.py             | ✅ Done  |
| F-01 Test preamble         | ADR-015 | test_output_guard.py           | ✅ Fixed |
| F-02 Test var name         | —       | test_agent_flow.py             | ✅ Fixed |
| F-03 Test endpoint URL     | —       | test_agent_flow.py             | ✅ Fixed |
| F-04 XSS logs (frontend)   | ADR-017 | SEC-012 (manual)               | ✅ Fixed |
| F-05 XSS table (frontend)  | ADR-017 | SEC-011 (manual), IT-009       | ✅ Fixed |
| F-06 XSS textarea (frontend)| ADR-017 | SEC-013 (manual)              | ✅ Fixed |
| F-07 CORS wildcard PLM/PIM | ADR-018 | SEC-014, CORS-002              | ✅ Fixed |
| F-08 CORS methods/headers  | ADR-018 | SEC-014, CORS-004              | ✅ Fixed |
| F-09 Template injection    | ADR-014 | test_prompt_builder.py (SEC-015)| ✅ Fixed |
| F-10 Timing attack         | ADR-016 | SEC-016 (code review)          | ✅ Fixed |
| KB file import             | ADR-021 | test_document_parser.py, test_kb_endpoints.py | ✅ Done  |
| KB URL links               | ADR-024 | SEC-017 (manual + code review) | ✅ Done  |
| RAG tag filtering          | ADR-019 | test_rag_filtering.py, test_confirm_tags.py | ✅ Done  |
| Doc lifecycle (staged)     | ADR-023 | test_agent_flow.py             | ✅ Done  |
