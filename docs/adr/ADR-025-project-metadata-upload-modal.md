# ADR-025 — Project Metadata & Upload Modal: Client-Scoped Integration Catalog

| Field        | Value                                              |
|--------------|----------------------------------------------------|
| **Status**   | Accepted                                           |
| **Date**     | 2026-03-19                                         |
| **Deciders** | Integration Mate PoC team                          |
| **Tags**     | catalog, upload, project, prefix, mongodb, frontend |

## Context

The platform treated every CSV upload as a standalone, anonymous batch of integrations.
Integration IDs used a generic `INT-` prefix with no business meaning, and there was no
way to filter the Integration Catalog by client or domain.

As the tool evolved beyond PoC into a professional delivery instrument, each upload needed
to be explicitly tied to a named client project so that:

- Documents are identifiable by client (`ACM-4F2A1B` instead of `INT-4F2A1B`)
- Multiple uploads for the same client accumulate under one project
- The Catalog can be filtered by client, domain, and Accenture reference
- Data is traceable back to a named engagement

## Decision

Introduce a `Project` as a first-class entity using **Approach A: separate `projects` collection**.

Every `CatalogEntry` acquires a `project_id` field. The upload flow is split into two
steps: parse-only upload → Project Modal → finalize (creates catalog entries with prefix IDs).

### 1. Data Model

**`Project` schema (new MongoDB collection `projects`):**

```python
class Project(BaseModel):
    prefix: str                        # natural PK — ^[A-Z0-9]{1,3}$
    client_name: str                   # mandatory
    domain: str                        # mandatory, free text
    description: Optional[str] = None  # max 500 chars
    accenture_ref: Optional[str] = None  # free text, max 100 chars
    created_at: str                    # ISO timestamp
```

Unique index on `prefix`. In-memory cache `projects: dict[str, Project]` with write-through
(consistent with existing `catalog`, `documents`, `kb_docs` pattern — ADR-013).

**`CatalogEntry` extension:**

```python
project_id: str = "LEGACY"  # backward-compatible default for pre-migration entries
```

Entry IDs change from `INT-{6hex}` to `{prefix}-{6hex}` (e.g., `ACM-4F2A1B`).

### 2. Prefix Auto-Generation Rule

| Input          | Rule                           | Result |
|----------------|-------------------------------|--------|
| "Acme Corp"    | First letter of each word      | `AC`   |
| "Global Fashion Group" | First letter of each word | `GFG` |
| "Salsify"      | Single word → first 3 letters  | `SAL`  |
| "AB"           | Short word → use as-is         | `AB`   |

Result is uppercased and stripped of non-alphanumeric characters. User can always override.

### 3. Upload Flow (Revised)

**Before:**
```
Upload CSV → parse → create CatalogEntries (INT-xxx) → tag confirmation
```

**After:**
```
Upload CSV → parse only → Project Modal → create/find Project
           → finalize (create CatalogEntries with prefix IDs) → tag confirmation
```

### 4. New API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/projects` | Token | Create project. Idempotent: same prefix + same client_name → 200. Same prefix + different client → 409. |
| `GET` | `/api/v1/projects` | — | List all projects (for filter dropdowns) |
| `GET` | `/api/v1/projects/{prefix}` | — | Get project by prefix (uniqueness check from modal) |
| `POST` | `/api/v1/requirements/finalize` | — | Create CatalogEntries for current parsed_requirements with given project_id |

### 5. Modified Endpoints

| Endpoint | Change |
|----------|--------|
| `POST /api/v1/requirements/upload` | Parse-only. No longer creates CatalogEntries. Returns `{status: "parsed", total_parsed, preview: [{source, target}]}`. |
| `GET /api/v1/catalog/integrations` | New optional query params: `?project_id=`, `?domain=`, `?accenture_ref=`. Case-insensitive partial matching for domain and accenture_ref. Response entries include `_project: {client_name, domain, accenture_ref}` or `null` for LEGACY entries. |

### 6. Project Modal (Frontend)

Displayed automatically after a successful upload parse. Fields:
- Nome Cliente (mandatory)
- Dominio (mandatory)
- Prefisso (auto-generated, editable, 1–3 uppercase alphanumeric chars)
- Descrizione (optional)
- Riferimento Accenture (optional)

Prefix uniqueness check: debounced `GET /api/v1/projects/{prefix}` at 400ms.
- Same client → green banner, reuse project
- Different client → red banner, Confirm disabled

**Debounce sentinel pattern**: `_resolvedProjectId` uses three distinct states:
- `undefined` → check in-flight (button disabled)
- `null` → prefix free (button enabled if all fields filled)
- `false` → clash (button disabled)
- `string` → existing project matched (button enabled)

### 7. Catalog Filter Bar (Frontend)

New filter bar above the integration grid:
- Cliente dropdown (populated from `GET /api/v1/projects`)
- Dominio text input (partial match, debounced 300ms)
- Riferimento Accenture text input (partial match, debounced 300ms)
- Reset button

### 8. Security

| Risk | Mitigation | OWASP |
|------|-----------|-------|
| Prefix injection | `pattern=r"^[A-Z0-9]{1,3}$"` on `ProjectCreateRequest.prefix`; server normalizes with `.upper()` | A03 |
| XSS in client_name / domain | `escapeHtml()` applied to all catalog card innerHTML (ADR-017) | A03 |
| Unauthenticated project creation | `POST /api/v1/projects` requires Bearer token | A01 |
| `finalize` with no parsed requirements | Backend checks `len(parsed_requirements) > 0` → 400 | A04 |
| `finalize` with non-existent project_id | Backend checks `projects.get(project_id)` → 404 | A04 |
| Prefix uniqueness bypass (fast confirm) | `_resolvedProjectId = undefined` sentinel disables confirm during debounce window | A04 |
| Prefix uppercase bypass | `prefix.upper().strip()` enforced server-side before persistence | A03 |

## Alternatives Considered

| Option | Rejected Because |
|--------|-----------------|
| **Embed fields in CatalogEntry** | Data duplication across all entries of same client; updating client name requires touching all entries |
| **Hierarchical Catalog UI** | Valid long-term vision but requires full Catalog page rewrite — out of scope |
| **Migration of existing INT-xxx entries** | Risky for PoC; backward-compatible `project_id="LEGACY"` default is safer |

## Consequences

- Integration IDs are now business-meaningful (`ACM-4F2A1B` vs `INT-4F2A1B`)
- Catalog is filterable by client, domain, and Accenture reference
- Upload flow gains one mandatory interaction step (Project Modal) — mitigated by auto-prefix generation
- Existing `INT-xxx` entries are preserved as `LEGACY` entries with `_project=null`
- **Rollback**: re-add CatalogEntry creation in upload endpoint; remove finalize endpoint; `project_id` defaults to `"LEGACY"` for all entries

## Validation

| File | Scope | Tests |
|------|-------|-------|
| `test_projects.py` | POST create (new, idempotent, 409 clash, 422 validation), GET list, GET by prefix | 11 |
| `test_finalize_requirements.py` | POST finalize (ok, prefix in IDs, no INT- prefix, 400 no reqs, 404 missing project) | 5 |
| `test_catalog_filter.py` | GET catalog with project_id, domain, accenture_ref filters, `_project` enrichment, LEGACY entries | 8 |
| `test_upload_creates_catalog.py` | Updated: two-step flow (parse → preview, finalize → prefix IDs) | 2 (rewritten) |
| `test_trigger_gate.py` | Updated: `_upload_and_finalize()` helper replaces `_upload_csv()` | updated |

**Total: 195 tests** (was 171 before this feature).

## References

- ADR-013: MongoDB Persistence (write-through cache pattern)
- ADR-017: Frontend XSS Mitigation (`escapeHtml()`)
- ADR-018: CORS Standardization
- Design doc: `docs/plans/2026-03-19-project-metadata-upload-modal-design.md`
- Implementation plan: `docs/plans/2026-03-19-project-metadata-upload-modal.md`
