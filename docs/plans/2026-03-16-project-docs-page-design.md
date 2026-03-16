# Project Docs Page — Design Document

**Date:** 2026-03-16
**Status:** Approved

---

## Goal

Add a "Project Docs" page in the Admin section of the web dashboard that lets any team member browse and read the significant project documentation (ADRs, guides, checklists, test plans, mappings) without leaving the application.

---

## Decisions Made

| Question | Answer |
|----------|--------|
| Loading strategy | **Option A — Backend endpoint**: `GET /api/v1/admin/docs` + `GET /api/v1/admin/docs/{path}` |
| Docs scope | Exclude templates (`*-000-template.md`), obsolete files (`*-old.md`), and `plans/` folder |
| Descriptions | Hardcoded manifest in `main.py` (Python dict per entry) |
| Layout | Two-panel: left = grouped list with badges + description; right = ReactMarkdown viewer |
| Navigation | New route `project-docs` under Admin in Sidebar |

---

## Architecture

### Backend — 2 new endpoints (`main.py`)

```
GET /api/v1/admin/docs
→ { status: "success", data: [ { path, name, category, description }, ... ] }

GET /api/v1/admin/docs/{path:path}
→ { status: "success", data: { path, name, content } }
  or HTTP 400 / 404 on invalid / not found
```

**Security:** Path traversal protection via `pathlib.Path.resolve()` — reject any path that does not resolve inside `DOCS_ROOT`.

**`DOCS_ROOT`:** Configured via env var `DOCS_ROOT`, defaulting to `Path(__file__).parent / "docs_volume"`. In Docker, the host `./docs` folder is mounted read-only to `/app/docs` and `DOCS_ROOT=/app/docs` is injected via `docker-compose.yml`.

### Frontend — `ProjectDocsPage.jsx`

Same two-panel layout as `DocumentsPage.jsx`:
- **Left panel (w-72):** grouped list by category, each item shows title + description
- **Right panel:** ReactMarkdown viewer (reuse `remarkGfm` already in the project)

Category badge colours:
| Category | Badge colour |
|----------|-------------|
| ADR | blue |
| Guide | emerald |
| Checklist | amber |
| Test Plan | violet |
| Mapping | slate |

### `api.js` additions

```js
projectDocs: {
  list:    ()     => fetch(`${getBase()}/api/v1/admin/docs`),
  content: (path) => fetch(`${getBase()}/api/v1/admin/docs/${path}`),
},
```

---

## Doc Manifest (27 significant files → 18 shown)

### Guides
| Path | Name | Description |
|------|------|-------------|
| `README.md` | README | Overview of the project, quick-start instructions, and service map. |
| `AWS-DEPLOYMENT-GUIDE.md` | AWS Deployment Guide | Step-by-step instructions to deploy the full stack on AWS (ECS, RDS, managed services). |
| `architecture_specification.md` | Architecture Specification | Full technical architecture: service topology, data flows, and component responsibilities. |
| `functional-guide.md` | Functional Guide | End-to-end functional walkthrough of the integration generation workflow. |

### ADRs
| Path | Name | Description |
|------|------|-------------|
| `adr/ADR-001-011-decisions.md` | ADR-001…011 | Batch record of foundational decisions: tech stack, RAG design, HITL flow, initial security posture. |
| `adr/ADR-012-async-llm-client.md` | ADR-012 Async LLM Client | Decision to replace synchronous `requests` with `httpx.AsyncClient` for non-blocking Ollama calls. |
| `adr/ADR-013-mongodb-persistence.md` | ADR-013 MongoDB Persistence | Decision to add MongoDB as write-through cache for catalog, approvals, and documents. |
| `adr/ADR-014-prompt-builder.md` | ADR-014 Prompt Builder | Decision to extract prompt assembly into a dedicated module with a reusable meta-prompt template. |
| `adr/ADR-015-llm-output-guard.md` | ADR-015 LLM Output Guard | Decision to add an output sanitization layer validating and bleach-cleaning LLM responses. |
| `adr/ADR-016-secret-management.md` | ADR-016 Secret Management | Decision to move all config to `pydantic-settings` with env-var overrides, eliminating hardcoded secrets. |
| `adr/ADR-017-frontend-xss-mitigation.md` | ADR-017 Frontend XSS Mitigation | Decision to introduce `escapeHtml()` in the frontend to neutralize XSS from server-sourced `innerHTML`. |
| `adr/ADR-018-cors-standardization.md` | ADR-018 CORS Standardization | Decision to replace wildcard CORS with an env-var-driven allowlist. |
| `adr/ADR-019-rag-tag-filtering.md` | ADR-019 RAG Tag Filtering | Decision to filter ChromaDB queries by confirmed integration tags to improve context relevance. |
| `adr/ADR-020-tag-llm-tuning.md` | ADR-020 Tag LLM Tuning | Decision to introduce dedicated lightweight LLM settings for tag suggestion (20-token cap, 15 s timeout). |

### Checklists
| Path | Name | Description |
|------|------|-------------|
| `code-review/CODE-REVIEW-CHECKLIST.md` | Code Review Checklist | Structured checklist covering architecture, correctness, security, and testability gates. |
| `security-review/SECURITY-REVIEW-CHECKLIST.md` | Security Review Checklist | OWASP-aligned checklist applied at every PR to catch injection, auth, logging, and dependency risks. |
| `unit-test-review/UNIT-TEST-REVIEW-CHECKLIST.md` | Unit Test Review Checklist | Quality gate checklist for unit tests: determinism, isolation, readability, edge-case coverage. |

### Test Plans
| Path | Name | Description |
|------|------|-------------|
| `test-plan/TEST-PLAN-001-remediation.md` | TEST-PLAN-001 Remediation | v2.0 plan covering 50 unit tests, 10 integration tests, and 16 security tests from Phase 4. |

### Mappings
| Path | Name | Description |
|------|------|-------------|
| `mappings/UNIT-SECURITY-OWASP-MAPPING.md` | OWASP Unit-Test Mapping | Traceability matrix linking each unit test to its OWASP Top 10 / ASVS control. |

---

## Excluded Files

| File | Reason |
|------|--------|
| `adr/ADR-000-template.md` | Template |
| `test-plan/TEST-PLAN-000-template.md` | Template |
| `runbooks/RUNBOOK-000-template.md` | Template |
| `architecture-specification-old.md` | Obsolete |
| `plans/**` | Internal implementation plans, not governance docs |
