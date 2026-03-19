# Design: Project Metadata & Upload Modal

| Field        | Value                              |
|--------------|------------------------------------|
| **Date**     | 2026-03-19                         |
| **Author**   | AI-assisted (Claude Code)          |
| **Status**   | Approved                           |
| **ADR**      | ADR-025 (to be created)            |

---

## 1. Problem Statement

The platform currently treats every CSV upload as a standalone set of integrations with
no concept of client, project, or domain ownership. Integration IDs use a generic `INT-`
prefix with no business meaning. There is no way to filter the Integration Catalog by
client or domain.

As the tool matures beyond PoC into a professional delivery instrument, each upload must
be explicitly tied to a named client project so that:
- Documents are identifiable by client (prefix in IDs: `ACM-4F2A1B`)
- Multiple uploads for the same client accumulate under one project
- The Catalog can be filtered by client, domain, and Accenture reference

---

## 2. Chosen Approach: Separate `projects` Collection (Approach A)

A `Project` is a first-class entity with `prefix` as its natural unique key.
Every `CatalogEntry` acquires a `project_id` field pointing to its parent project.

**Rejected alternatives:**
- **Embed fields in CatalogEntry**: data duplication across all entries of the same
  client; updating client name requires touching all entries.
- **Hierarchical Catalog UI**: valid long-term vision but out of scope — requires full
  Catalog page rewrite.

---

## 3. Data Model

### 3.1 New `Project` schema

```python
class Project(BaseModel):
    prefix: str                        # "ACM" — natural PK, 1-3 chars, ^[A-Z0-9]{1,3}$
    client_name: str                   # "Acme Corp" — mandatory
    domain: str                        # "Fashion Retail" — mandatory, free text
    description: Optional[str] = None # max 500 chars
    accenture_ref: Optional[str] = None  # free text, max 100 chars
    created_at: str                    # ISO timestamp
```

MongoDB collection: `projects`
Index: unique on `prefix`
In-memory: `projects: dict[str, Project]` (write-through pattern, consistent with
existing `catalog`, `documents`, `kb_docs`)

### 3.2 `CatalogEntry` changes

```python
class CatalogEntry(BaseModel):
    id: str           # WAS "INT-4F2A1B" → NOW "{prefix}-{6hex}" e.g. "ACM-4F2A1B"
    project_id: str   # NEW — FK to Project.prefix
    # all other existing fields unchanged
```

### 3.3 Prefix auto-generation rule

| Client name            | Rule                           | Result |
|------------------------|-------------------------------|--------|
| "Acme Corp"            | First letter of each word      | `AC`   |
| "Global Fashion Group" | First letter of each word      | `GFG`  |
| "Salsify"              | Single word → first 3 letters  | `SAL`  |
| "AB"                   | Short word → use as-is          | `AB`   |

Result is uppercased and stripped of non-alphanumeric characters.
The user can always override the auto-generated prefix in the modal.

---

## 4. Upload Flow (Revised)

### Before
```
Upload CSV → parse → create CatalogEntries (INT-xxx) → tag confirmation
```

### After
```
Upload CSV → parse only → Project Modal → create/find Project
           → finalize (create CatalogEntries with prefix IDs) → tag confirmation
```

### Detailed step-by-step

```
1. User selects CSV → clicks "Upload"

2. POST /api/v1/requirements/upload  [MODIFIED]
   - Validates file (MIME, size, UTF-8) — unchanged
   - Parses CSV into parsed_requirements — unchanged
   - Stores parsed_requirements in memory — unchanged
   - *** Does NOT create CatalogEntries anymore ***
   - Returns: { status: "parsed", total_parsed: N,
                preview: [{source, target}, ...] }

3. Frontend opens Project Modal displaying the preview

4. User fills the modal:
   ┌────────────────────────────────────────────────────┐
   │  📋 Informazioni Progetto                           │
   │  "Trovati 7 requisiti · 2 integrazioni rilevate"   │
   │                                                    │
   │  Nome Cliente *  [Acme Corp          ]             │
   │  Dominio *       [Fashion Retail     ]             │
   │  Prefisso        [ACM] (auto, editabile)           │
   │  Descrizione     [                   ]             │
   │  Ref. Accenture  [                   ]             │
   │                                                    │
   │              [Annulla]  [Conferma →]               │
   └────────────────────────────────────────────────────┘

   - Prefix auto-generates as the user types the client name (debounce 300ms)
   - On prefix change: GET /api/v1/projects/{prefix} (debounce 400ms)

5. Uniqueness check responses:
   a) Prefix free → no banner shown
   b) Prefix taken, same client_name →
      ✅ green banner: "Acme Corp esiste già. I documenti saranno
         aggiunti al progetto ACM."
      Confirm button remains enabled.
   c) Prefix taken, different client →
      ❌ red banner: "Prefisso già utilizzato da GlobalFashion.
         Modifica il prefisso."
      Confirm button disabled until prefix is unique.

6. User clicks "Conferma →":
   a) If new project: POST /api/v1/projects  { prefix, client_name, domain, ... }
      → 201 Created
   b) If existing (case b above): skip POST, reuse found project
   c) POST /api/v1/requirements/finalize  { project_id: "ACM" }
      → creates CatalogEntries with IDs "{prefix}-{6hex}"
      → returns { integrations_created: N }

7. Tag confirmation flow → unchanged (fetchAndShowTagConfirmation)
```

---

## 5. API Changes

### 5.1 New endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/projects` | Token | Create project. Idempotent: if prefix exists and client_name matches → 200 + existing. If prefix exists and client_name differs → 409. |
| `GET` | `/api/v1/projects` | — | List all projects (for filter dropdowns) |
| `GET` | `/api/v1/projects/{prefix}` | — | Get project by prefix (uniqueness check from modal) |
| `POST` | `/api/v1/requirements/finalize` | — | Create CatalogEntries for current parsed_requirements with given project_id |

### 5.2 Modified endpoints

| Endpoint | Change |
|----------|--------|
| `POST /api/v1/requirements/upload` | Removes CatalogEntry creation. Returns `preview: [{source, target}]` instead of `integrations_created`. |
| `GET /api/v1/catalog/integrations` | New optional query params: `?project_id=`, `?domain=`, `?accenture_ref=`. Server-side $regex case-insensitive filtering via MongoDB. |

### 5.3 New Pydantic models

```python
class ProjectCreateRequest(BaseModel):
    prefix: str = Field(..., pattern=r"^[A-Z0-9]{1,3}$")
    client_name: str = Field(..., min_length=1, max_length=100)
    domain: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    accenture_ref: Optional[str] = Field(None, max_length=100)

class FinalizeRequirementsRequest(BaseModel):
    project_id: str = Field(..., pattern=r"^[A-Z0-9]{1,3}$")

class UploadPreviewResponse(BaseModel):
    status: str
    total_parsed: int
    preview: List[Dict[str, str]]   # [{source, target}, ...]
```

---

## 6. Integration Catalog UI

### 6.1 Filter bar (new, above the grid)

```
┌─────────────────────────────────────────────────────────┐
│  🏢 Cliente   [dropdown: Tutti i clienti ▼]             │
│  🏷️  Dominio  [text input partial match   ]             │
│  👤 Accenture [text input partial match   ]             │
│                                        [Reset filtri]   │
└─────────────────────────────────────────────────────────┘
```

- **Cliente dropdown**: populated from `GET /api/v1/projects` on page load.
  Shows `{prefix} · {client_name}`. On change → sets `?project_id=` param.
- **Dominio / Accenture**: debounced text inputs (300ms) → server-side `$regex`.
- **Reset**: clears all filters and reloads.
- Filter state is preserved in component-level JS variables (consistent with
  existing `_cachedLogs` / `_logsOffset` pattern).

### 6.2 Catalog card — updated layout

```
┌──────────────────────────────────────────────┐
│  [ACM]  ACM-4F2A1B         [TAG_CONFIRMED]   │
│  ERP → Salsify                               │
│  ─────────────────────────────────────────   │
│  🏢 Acme Corp  •  Fashion Retail             │
│  👤 Mario Rossi (Accenture)                  │
│  tags: [product] [pricing]                   │
└──────────────────────────────────────────────┘
```

- Prefix badge (`[ACM]`) styled as a small colored chip in the card header.
- Client name + domain on one line, Accenture ref below.
- Accenture ref row hidden if empty.

---

## 7. Security

| Risk | Mitigation | OWASP |
|------|-----------|-------|
| Prefix injection (`../`, spaces, specials) | `pattern=r"^[A-Z0-9]{1,3}$"` on `ProjectCreateRequest.prefix` | A03 |
| XSS via client_name / domain in catalog cards | `escapeHtml()` already applied to all server-sourced innerHTML (ADR-017) | A03 |
| Unauthenticated project creation | `POST /api/v1/projects` requires Bearer token | A01 |
| `finalize` with no parsed requirements | Backend checks `len(parsed_requirements) > 0` → 400 | A04 |
| `finalize` with non-existent project_id | Backend checks `projects.get(project_id)` → 404 | A04 |
| Client name enumeration via uniqueness check | `GET /projects/{prefix}` returns full project info — acceptable for internal PoC | A01 |
| Prefix uppercase bypass | `prefix.upper().strip()` enforced server-side before persistence | A03 |

---

## 8. Testing

| File | Scope | Estimated tests |
|------|-------|----------------|
| `test_projects.py` | POST create (new, idempotent, 409 clash), GET list, GET by prefix | 8 |
| `test_finalize_requirements.py` | POST finalize (ok, 404 missing project, 400 no parsed reqs) | 5 |
| `test_catalog_filter.py` | GET catalog with project_id, domain, accenture_ref filters | 6 |
| `test_requirements_upload.py` | Updated: upload no longer returns integrations_created; returns preview | 3 updated |

**Regression risk**: `test_requirements_upload.py` and `test_agent_flow.py` assert on
`integrations_created` and catalog state after upload — these must be updated to call
`finalize` explicitly in test setup.

---

## 9. Rollback

The only breaking change is splitting upload into upload + finalize. To rollback:
1. Re-add CatalogEntry creation inside the upload endpoint.
2. Remove the `finalize` endpoint (or keep it as a no-op).
3. `project_id` on `CatalogEntry` can default to `"LEGACY"` for pre-migration entries.

---

## 10. Out of Scope

- Editing project metadata after creation (client name, domain) — future iteration.
- Deleting a project (and its associated integrations) — future iteration.
- Project-level dashboard / analytics view — future iteration.
- Migration of existing `INT-xxx` entries to a default project — future iteration.
