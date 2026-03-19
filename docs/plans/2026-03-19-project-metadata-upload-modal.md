# Project Metadata & Upload Modal — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `Project` entity (client, domain, prefix) to every CSV upload so that integration IDs use the client prefix (`ACM-4F2A1B`), documents are grouped by project, and the Catalog page can be filtered by client/domain/Accenture ref.

**Architecture:** New `projects` MongoDB collection + in-memory dict (write-through, same pattern as `catalog`). Upload is split into parse-only + `/finalize` (which needs a project_id). Project modal in frontend shows after upload parse, before tag confirmation.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic-settings / Motor (backend) · Vanilla JS + CSS variables (frontend, no framework)

**Design doc:** `docs/plans/2026-03-19-project-metadata-upload-modal-design.md`

---

## Task 1: schemas.py — Project model + CatalogEntry.project_id + request models

**Files:**
- Modify: `services/integration-agent/schemas.py`

**Step 1: Add `Project`, `ProjectCreateRequest`, `FinalizeRequirementsRequest` and update `CatalogEntry`**

Open `services/integration-agent/schemas.py`. Make these changes:

1a. Add `project_id: str` to `CatalogEntry` (after the `tags` field):

```python
class CatalogEntry(BaseModel):
    id: str
    name: str
    type: str
    source: Dict[str, str]
    target: Dict[str, str]
    requirements: List[str]
    status: str
    tags: List[str] = []
    project_id: str = "LEGACY"    # ← NEW: default "LEGACY" for backward compat
    created_at: str
```

1b. Add the three new models at the end of the file (before the KB models section is fine, or at the very end):

```python
# ── Project models ────────────────────────────────────────────────────────────

class Project(BaseModel):
    """A client project that groups one or more CSV upload sessions.

    prefix is the natural unique key (1-3 uppercase alphanumeric chars).
    It is used as the ID prefix for all CatalogEntries in this project
    (e.g., prefix="ACM" → entry IDs like "ACM-4F2A1B").
    """
    prefix: str                          # e.g., "ACM"
    client_name: str
    domain: str
    description: Optional[str] = None
    accenture_ref: Optional[str] = None
    created_at: str


class ProjectCreateRequest(BaseModel):
    """Body for POST /api/v1/projects."""
    prefix: str = Field(
        ...,
        pattern=r"^[A-Z0-9]{1,3}$",
        description="1-3 uppercase alphanumeric chars. Auto-generated from client initials.",
    )
    client_name: str = Field(..., min_length=1, max_length=100)
    domain: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    accenture_ref: Optional[str] = Field(None, max_length=100)


class FinalizeRequirementsRequest(BaseModel):
    """Body for POST /api/v1/requirements/finalize."""
    project_id: str = Field(
        ...,
        pattern=r"^[A-Z0-9]{1,3}$",
        description="Prefix of an existing Project. CatalogEntries will use this as ID prefix.",
    )
```

**Step 2: Verify schemas import cleanly**

```bash
cd services/integration-agent
python -c "from schemas import Project, ProjectCreateRequest, FinalizeRequirementsRequest, CatalogEntry; print('OK')"
```

Expected output: `OK`

**Step 3: Commit**

```bash
git add services/integration-agent/schemas.py
git commit -m "feat: add Project schema, ProjectCreateRequest, FinalizeRequirementsRequest; add project_id to CatalogEntry"
```

---

## Task 2: db.py — projects collection + in-memory dict

**Files:**
- Modify: `services/integration-agent/db.py`
- Modify: `services/integration-agent/main.py` (add `projects` in-memory dict declaration)

**Step 1: Add `projects_col` to `db.py`**

In `db.py`, add the new collection variable alongside the others:

```python
catalog_col:      motor.motor_asyncio.AsyncIOMotorCollection | None = None
approvals_col:    motor.motor_asyncio.AsyncIOMotorCollection | None = None
documents_col:    motor.motor_asyncio.AsyncIOMotorCollection | None = None
kb_documents_col: motor.motor_asyncio.AsyncIOMotorCollection | None = None
llm_settings_col: motor.motor_asyncio.AsyncIOMotorCollection | None = None
projects_col:     motor.motor_asyncio.AsyncIOMotorCollection | None = None  # ← NEW
```

Update the `global` declaration in `init_db()`:

```python
global _client, _db, catalog_col, approvals_col, documents_col, kb_documents_col, llm_settings_col, projects_col
```

Inside `init_db()`, after the `kb_documents_col` assignment:

```python
projects_col = _db["projects"]
await projects_col.create_index("prefix", unique=True)
```

**Step 2: Add `projects` in-memory dict to `main.py`**

In `main.py`, find the block where in-memory state is declared (around line 83-84 where `catalog` and `parsed_requirements` are defined). Add:

```python
from schemas import (
    # ... existing imports ...
    Project,
    ProjectCreateRequest,
    FinalizeRequirementsRequest,
)

# Module-level in-memory state (write-through → MongoDB)
parsed_requirements: list[Requirement] = []
catalog:   dict[str, CatalogEntry] = {}
projects:  dict[str, Project] = {}          # ← NEW: keyed by prefix
```

Also update the `_seed_memory_from_db()` function (or wherever MongoDB data is loaded into memory at startup) to seed `projects`:

Find the startup seeding code (inside `lifespan` or an async startup function). After where `catalog` is seeded, add:

```python
# Seed projects
if db.projects_col is not None:
    async for doc in db.projects_col.find({}):
        doc.pop("_id", None)
        p = Project(**doc)
        projects[p.prefix] = p
    _log(f"[DB] Seeded {len(projects)} projects from MongoDB.", "INFO")
```

**Step 3: Verify db changes**

```bash
python -c "import db; print(hasattr(db, 'projects_col'))"
```

Expected: `True`

**Step 4: Commit**

```bash
git add services/integration-agent/db.py services/integration-agent/main.py
git commit -m "feat: add projects_col to db.py and projects in-memory dict to main.py"
```

---

## Task 3: Backend — Project CRUD endpoints

**Files:**
- Modify: `services/integration-agent/main.py`

Add three endpoints. Find a logical place in `main.py` — after the requirements endpoints and before the agent endpoints is fine. Add a section comment:

```python
# ── Projects ──────────────────────────────────────────────────────────────────
```

**Step 1: Add `POST /api/v1/projects`**

```python
@app.post("/api/v1/projects", tags=["projects"])
async def create_project(
    body: ProjectCreateRequest,
    _token: str = Depends(_require_token),
) -> dict:
    """Create a new project.

    Idempotent: if the prefix already exists and client_name matches → 200.
    If the prefix exists but client_name differs → 409 Conflict.
    """
    prefix = body.prefix.upper().strip()
    existing = projects.get(prefix)
    if existing:
        if existing.client_name.lower() == body.client_name.lower():
            return {"status": "ok", "data": existing.model_dump()}
        raise HTTPException(
            status_code=409,
            detail=f"Prefix '{prefix}' already used by project '{existing.client_name}'.",
        )

    project = Project(
        prefix=prefix,
        client_name=body.client_name,
        domain=body.domain,
        description=body.description,
        accenture_ref=body.accenture_ref,
        created_at=_now_iso(),
    )
    projects[prefix] = project
    if db.projects_col is not None:
        await db.projects_col.replace_one(
            {"prefix": prefix}, project.model_dump(), upsert=True
        )
    _log(f"[PROJECT] Created project '{prefix}' for client '{project.client_name}'.", "INFO")
    return {"status": "created", "data": project.model_dump()}


@app.get("/api/v1/projects", tags=["projects"])
async def list_projects() -> dict:
    """List all projects (used to populate filter dropdowns)."""
    return {"status": "success", "data": [p.model_dump() for p in projects.values()]}


@app.get("/api/v1/projects/{prefix}", tags=["projects"])
async def get_project(prefix: str) -> dict:
    """Get a project by prefix (used for uniqueness check from the frontend modal)."""
    prefix = prefix.upper().strip()
    project = projects.get(prefix)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{prefix}' not found.")
    return {"status": "success", "data": project.model_dump()}
```

**Step 2: Verify endpoints register**

```bash
python -c "from main import app; routes = [r.path for r in app.routes]; print([r for r in routes if 'project' in r])"
```

Expected: `['/api/v1/projects', '/api/v1/projects', '/api/v1/projects/{prefix}']`

**Step 3: Commit**

```bash
git add services/integration-agent/main.py
git commit -m "feat: add POST/GET /api/v1/projects and GET /api/v1/projects/{prefix} endpoints"
```

---

## Task 4: Backend — Modify upload endpoint (parse-only, return preview)

**Files:**
- Modify: `services/integration-agent/main.py`

**Step 1: Remove CatalogEntry creation from `upload_requirements`**

Find the `upload_requirements` function (around line 834). Replace the section that creates `CatalogEntry` objects and the return statement.

**BEFORE** (lines ~876–907):
```python
    # Group requirements by source→target and create CatalogEntries
    groups: dict[str, list[Requirement]] = {}
    for r in parsed_requirements:
        key = f"{r.source_system}|||{r.target_system}"
        groups.setdefault(key, []).append(r)

    for _key, reqs in groups.items():
        source = reqs[0].source_system
        target = reqs[0].target_system
        entry_id = f"INT-{uuid.uuid4().hex[:6].upper()}"
        entry = CatalogEntry(
            id=entry_id,
            name=f"{source} to {target} Integration",
            type="Auto-discovered",
            source={"system": source},
            target={"system": target},
            requirements=[r.req_id for r in reqs],
            status="PENDING_TAG_REVIEW",
            tags=[],
            created_at=_now_iso(),
        )
        catalog[entry_id] = entry
        if db.catalog_col is not None:
            await db.catalog_col.replace_one(
                {"id": entry_id}, entry.model_dump(), upsert=True
            )

    return {
        "status": "success",
        "total_parsed": len(parsed_requirements),
        "integrations_created": len(groups),
    }
```

**AFTER** (replace with):
```python
    # Build a preview of detected source→target pairs (no CatalogEntry created yet).
    # CatalogEntry creation is deferred to POST /api/v1/requirements/finalize
    # once the caller has provided a project_id (ADR-025).
    seen: dict[str, dict] = {}
    for r in parsed_requirements:
        key = f"{r.source_system}|||{r.target_system}"
        if key not in seen:
            seen[key] = {"source": r.source_system, "target": r.target_system}

    _log(
        f"[UPLOAD] Parsed {len(parsed_requirements)} requirements, "
        f"{len(seen)} integration pair(s) detected. Awaiting /finalize.",
        "INFO",
    )
    return {
        "status": "parsed",
        "total_parsed": len(parsed_requirements),
        "preview": list(seen.values()),
    }
```

**Step 2: Commit**

```bash
git add services/integration-agent/main.py
git commit -m "feat: upload endpoint parse-only — defer CatalogEntry creation to /finalize (ADR-025)"
```

---

## Task 5: Backend — POST /requirements/finalize

**Files:**
- Modify: `services/integration-agent/main.py`

Add this endpoint immediately after `upload_requirements`:

```python
@app.post("/api/v1/requirements/finalize", tags=["requirements"])
async def finalize_requirements(body: FinalizeRequirementsRequest) -> dict:
    """Create CatalogEntries for the current parsed_requirements under a given project.

    Must be called after POST /api/v1/requirements/upload.
    The project identified by body.project_id must already exist.

    CatalogEntry IDs use the project prefix: e.g., "ACM-4F2A1B".
    """
    if not parsed_requirements:
        raise HTTPException(
            status_code=400,
            detail="No parsed requirements in memory. Upload a CSV first.",
        )

    project_id = body.project_id.upper().strip()
    project = projects.get(project_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{project_id}' not found. Create it first via POST /api/v1/projects.",
        )

    # Group requirements by source→target pair
    groups: dict[str, list[Requirement]] = {}
    for r in parsed_requirements:
        key = f"{r.source_system}|||{r.target_system}"
        groups.setdefault(key, []).append(r)

    created = 0
    for _key, reqs in groups.items():
        source = reqs[0].source_system
        target = reqs[0].target_system
        entry_id = f"{project_id}-{uuid.uuid4().hex[:6].upper()}"
        entry = CatalogEntry(
            id=entry_id,
            name=f"{source} to {target} Integration",
            type="Auto-discovered",
            source={"system": source},
            target={"system": target},
            requirements=[r.req_id for r in reqs],
            status="PENDING_TAG_REVIEW",
            tags=[],
            project_id=project_id,
            created_at=_now_iso(),
        )
        catalog[entry_id] = entry
        if db.catalog_col is not None:
            await db.catalog_col.replace_one(
                {"id": entry_id}, entry.model_dump(), upsert=True
            )
        created += 1

    _log(
        f"[FINALIZE] Created {created} CatalogEntry(ies) under project '{project_id}' "
        f"({project.client_name}).",
        "INFO",
    )
    return {"status": "success", "integrations_created": created, "project_id": project_id}
```

**Step 2: Verify endpoint registers**

```bash
python -c "from main import app; routes = [r.path for r in app.routes]; print([r for r in routes if 'finalize' in r])"
```

Expected: `['/api/v1/requirements/finalize']`

**Step 3: Commit**

```bash
git add services/integration-agent/main.py
git commit -m "feat: add POST /api/v1/requirements/finalize — creates CatalogEntries with project prefix ID"
```

---

## Task 6: Backend — GET /catalog/integrations with filter params

**Files:**
- Modify: `services/integration-agent/main.py`

**Step 1: Replace the `get_catalog` function**

Find (around line 1092):
```python
@app.get("/api/v1/catalog/integrations", tags=["catalog"])
async def get_catalog() -> dict:
    return {"status": "success", "data": [c.model_dump() for c in catalog.values()]}
```

Replace with:
```python
@app.get("/api/v1/catalog/integrations", tags=["catalog"])
async def get_catalog(
    project_id: Optional[str] = Query(None, description="Filter by project prefix (exact, case-insensitive)"),
    domain: Optional[str] = Query(None, description="Filter by project domain (partial match, case-insensitive)"),
    accenture_ref: Optional[str] = Query(None, description="Filter by Accenture reference (partial match, case-insensitive)"),
) -> dict:
    """List all catalog entries with optional project-level filtering."""
    items = list(catalog.values())

    if project_id:
        pid = project_id.upper().strip()
        items = [i for i in items if i.project_id == pid]

    if domain:
        low = domain.lower().strip()
        items = [
            i for i in items
            if (p := projects.get(i.project_id)) and low in p.domain.lower()
        ]

    if accenture_ref:
        low = accenture_ref.lower().strip()
        items = [
            i for i in items
            if (p := projects.get(i.project_id))
            and p.accenture_ref
            and low in p.accenture_ref.lower()
        ]

    # Enrich each entry with its project metadata for display in the frontend
    result = []
    for i in items:
        d = i.model_dump()
        proj = projects.get(i.project_id)
        if proj:
            d["_project"] = {
                "client_name": proj.client_name,
                "domain": proj.domain,
                "accenture_ref": proj.accenture_ref,
            }
        result.append(d)

    return {"status": "success", "data": result}
```

Also add `Optional` and `Query` to FastAPI imports at the top of `main.py` if not already present:
```python
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Query
from typing import Optional  # (already imported likely — verify)
```

**Step 2: Commit**

```bash
git add services/integration-agent/main.py
git commit -m "feat: GET /catalog/integrations accepts project_id, domain, accenture_ref filter params"
```

---

## Task 7: Tests — test_projects.py (new)

**Files:**
- Create: `services/integration-agent/tests/test_projects.py`

**Step 1: Write the tests**

```python
"""Unit tests for Project CRUD endpoints (ADR-025).

POST /api/v1/projects  — create (new, idempotent same client, 409 clash)
GET  /api/v1/projects  — list
GET  /api/v1/projects/{prefix} — get by prefix (uniqueness check)
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    with (
        patch("db.init_db",          new_callable=AsyncMock),
        patch("db.close_db",         new_callable=AsyncMock),
        patch("main._init_chromadb", new_callable=AsyncMock),
    ):
        from main import app
        with TestClient(app) as c:
            yield c


@pytest.fixture(autouse=True)
def clear_projects():
    """Ensure projects dict is empty before each test."""
    import main
    main.projects.clear()
    yield
    main.projects.clear()


_VALID_PROJECT = {
    "prefix": "ACM",
    "client_name": "Acme Corp",
    "domain": "Fashion Retail",
    "description": "Global fashion integration",
    "accenture_ref": "Mario Rossi",
}


class TestCreateProject:
    def test_create_new_project_returns_201_or_200(self, client):
        resp = client.post("/api/v1/projects", json=_VALID_PROJECT)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["data"]["prefix"] == "ACM"
        assert data["data"]["client_name"] == "Acme Corp"

    def test_create_stores_in_memory(self, client):
        import main
        client.post("/api/v1/projects", json=_VALID_PROJECT)
        assert "ACM" in main.projects
        assert main.projects["ACM"].client_name == "Acme Corp"

    def test_create_idempotent_same_client(self, client):
        """Same prefix + same client_name → 200, returns existing project."""
        client.post("/api/v1/projects", json=_VALID_PROJECT)
        resp = client.post("/api/v1/projects", json=_VALID_PROJECT)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_create_clash_different_client_returns_409(self, client):
        """Same prefix but different client_name → 409 Conflict."""
        client.post("/api/v1/projects", json=_VALID_PROJECT)
        clash = {**_VALID_PROJECT, "client_name": "Another Corp"}
        resp = client.post("/api/v1/projects", json=clash)
        assert resp.status_code == 409
        assert "Another Corp" not in resp.json()["detail"] or "ACM" in resp.json()["detail"]

    def test_prefix_lowercase_normalised_to_upper(self, client):
        """Prefix sent as lowercase must be stored uppercase."""
        payload = {**_VALID_PROJECT, "prefix": "acm"}
        # pattern=r"^[A-Z0-9]{1,3}$" on the Pydantic model rejects lowercase
        resp = client.post("/api/v1/projects", json=payload)
        assert resp.status_code == 422  # Pydantic validation error

    def test_missing_client_name_returns_422(self, client):
        payload = {k: v for k, v in _VALID_PROJECT.items() if k != "client_name"}
        resp = client.post("/api/v1/projects", json=payload)
        assert resp.status_code == 422

    def test_missing_domain_returns_422(self, client):
        payload = {k: v for k, v in _VALID_PROJECT.items() if k != "domain"}
        resp = client.post("/api/v1/projects", json=payload)
        assert resp.status_code == 422


class TestListProjects:
    def test_list_empty(self, client):
        resp = client.get("/api/v1/projects")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_list_returns_created_projects(self, client):
        client.post("/api/v1/projects", json=_VALID_PROJECT)
        resp = client.get("/api/v1/projects")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["prefix"] == "ACM"


class TestGetProjectByPrefix:
    def test_get_existing_project(self, client):
        client.post("/api/v1/projects", json=_VALID_PROJECT)
        resp = client.get("/api/v1/projects/ACM")
        assert resp.status_code == 200
        assert resp.json()["data"]["client_name"] == "Acme Corp"

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/api/v1/projects/ZZZ")
        assert resp.status_code == 404
```

**Step 2: Run tests to verify they pass**

```bash
cd services/integration-agent
pytest tests/test_projects.py -v
```

Expected: all tests PASS.

**Step 3: Commit**

```bash
git add services/integration-agent/tests/test_projects.py
git commit -m "test: add test_projects.py — Project CRUD endpoint coverage (ADR-025)"
```

---

## Task 8: Tests — test_finalize_requirements.py (new)

**Files:**
- Create: `services/integration-agent/tests/test_finalize_requirements.py`

**Step 1: Write the tests**

```python
"""Unit tests for POST /api/v1/requirements/finalize (ADR-025).

Verifies:
- Happy path: upload CSV + create project + finalize → CatalogEntries created
- 400 if no parsed requirements in memory
- 404 if project_id does not exist
- Entry IDs use the project prefix (not INT-)
"""
import io
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    with (
        patch("db.init_db",          new_callable=AsyncMock),
        patch("db.close_db",         new_callable=AsyncMock),
        patch("main._init_chromadb", new_callable=AsyncMock),
    ):
        from main import app
        with TestClient(app) as c:
            yield c


_CSV = (
    b"ReqID,Source,Target,Category,Description\n"
    b"R-001,ERP,PLM,Sync,Sync products\n"
    b"R-002,PLM,PIM,Enrich,Enrich in PIM\n"
)
_PROJECT = {"prefix": "TST", "client_name": "Test Corp", "domain": "Test Domain"}


def _upload(client):
    return client.post(
        "/api/v1/requirements/upload",
        files={"file": ("reqs.csv", io.BytesIO(_CSV), "text/csv")},
    )


def _create_project(client):
    return client.post("/api/v1/projects", json=_PROJECT)


class TestFinalizeRequirements:
    def setup_method(self):
        """Clear state before each test."""
        import main
        main.catalog.clear()
        main.parsed_requirements.clear()
        main.projects.clear()

    def test_happy_path_creates_catalog_entries(self, client):
        _upload(client)
        _create_project(client)
        resp = client.post("/api/v1/requirements/finalize", json={"project_id": "TST"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["integrations_created"] == 2   # ERP→PLM + PLM→PIM
        assert data["project_id"] == "TST"

    def test_entry_ids_use_project_prefix(self, client):
        import main
        _upload(client)
        _create_project(client)
        client.post("/api/v1/requirements/finalize", json={"project_id": "TST"})
        for entry_id in main.catalog:
            assert entry_id.startswith("TST-"), f"Expected TST- prefix, got {entry_id}"

    def test_entry_ids_do_not_use_int_prefix(self, client):
        import main
        _upload(client)
        _create_project(client)
        client.post("/api/v1/requirements/finalize", json={"project_id": "TST"})
        for entry_id in main.catalog:
            assert not entry_id.startswith("INT-"), "Old INT- prefix must not be used"

    def test_400_if_no_parsed_requirements(self, client):
        """Finalize without prior upload must return 400."""
        import main
        main.parsed_requirements.clear()
        _create_project(client)
        resp = client.post("/api/v1/requirements/finalize", json={"project_id": "TST"})
        assert resp.status_code == 400

    def test_404_if_project_not_found(self, client):
        """Finalize with unknown project_id must return 404."""
        _upload(client)
        resp = client.post("/api/v1/requirements/finalize", json={"project_id": "ZZZ"})
        assert resp.status_code == 404
```

**Step 2: Run tests**

```bash
pytest tests/test_finalize_requirements.py -v
```

Expected: all PASS.

**Step 3: Commit**

```bash
git add services/integration-agent/tests/test_finalize_requirements.py
git commit -m "test: add test_finalize_requirements.py — finalize endpoint coverage (ADR-025)"
```

---

## Task 9: Tests — test_catalog_filter.py (new)

**Files:**
- Create: `services/integration-agent/tests/test_catalog_filter.py`

**Step 1: Write the tests**

```python
"""Unit tests for GET /catalog/integrations filter params (ADR-025).

Tests project_id, domain, accenture_ref query params
and the _project metadata enrichment in the response.
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from schemas import CatalogEntry, Project


@pytest.fixture(scope="module")
def client():
    with (
        patch("db.init_db",          new_callable=AsyncMock),
        patch("db.close_db",         new_callable=AsyncMock),
        patch("main._init_chromadb", new_callable=AsyncMock),
    ):
        from main import app
        with TestClient(app) as c:
            yield c


@pytest.fixture(autouse=True)
def seed_data():
    """Seed two projects and two catalog entries."""
    import main
    from datetime import datetime, timezone

    main.projects.clear()
    main.catalog.clear()

    main.projects["ACM"] = Project(
        prefix="ACM",
        client_name="Acme Corp",
        domain="Fashion Retail",
        accenture_ref="Mario Rossi",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    main.projects["GLB"] = Project(
        prefix="GLB",
        client_name="Global Co",
        domain="Automotive",
        accenture_ref="Anna Verdi",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    main.catalog["ACM-000001"] = CatalogEntry(
        id="ACM-000001", name="ERP to Salsify", type="Auto-discovered",
        source={"system": "ERP"}, target={"system": "Salsify"},
        requirements=["R-001"], status="TAG_CONFIRMED",
        project_id="ACM", created_at=datetime.now(timezone.utc).isoformat(),
    )
    main.catalog["GLB-000002"] = CatalogEntry(
        id="GLB-000002", name="PLM to PIM", type="Auto-discovered",
        source={"system": "PLM"}, target={"system": "PIM"},
        requirements=["R-002"], status="TAG_CONFIRMED",
        project_id="GLB", created_at=datetime.now(timezone.utc).isoformat(),
    )
    yield
    main.projects.clear()
    main.catalog.clear()


class TestCatalogFilter:
    def test_no_filter_returns_all(self, client):
        resp = client.get("/api/v1/catalog/integrations")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2

    def test_filter_by_project_id(self, client):
        resp = client.get("/api/v1/catalog/integrations?project_id=ACM")
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == "ACM-000001"

    def test_filter_by_project_id_case_insensitive(self, client):
        resp = client.get("/api/v1/catalog/integrations?project_id=acm")
        assert len(resp.json()["data"]) == 1

    def test_filter_by_domain_partial(self, client):
        resp = client.get("/api/v1/catalog/integrations?domain=fashion")
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["project_id"] == "ACM"

    def test_filter_by_accenture_ref_partial(self, client):
        resp = client.get("/api/v1/catalog/integrations?accenture_ref=verdi")
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["project_id"] == "GLB"

    def test_response_includes_project_metadata(self, client):
        resp = client.get("/api/v1/catalog/integrations?project_id=ACM")
        entry = resp.json()["data"][0]
        assert "_project" in entry
        assert entry["_project"]["client_name"] == "Acme Corp"
        assert entry["_project"]["domain"] == "Fashion Retail"

    def test_unknown_project_id_returns_empty_list(self, client):
        resp = client.get("/api/v1/catalog/integrations?project_id=ZZZ")
        assert resp.json()["data"] == []
```

**Step 2: Run tests**

```bash
pytest tests/test_catalog_filter.py -v
```

Expected: all PASS.

**Step 3: Commit**

```bash
git add services/integration-agent/tests/test_catalog_filter.py
git commit -m "test: add test_catalog_filter.py — catalog filter params and _project enrichment"
```

---

## Task 10: Tests — Rewrite test_upload_creates_catalog.py

The old test assumed upload creates `CatalogEntry`. Since upload is now parse-only, this test must use the new two-step flow (upload → create project → finalize).

**Files:**
- Modify: `services/integration-agent/tests/test_upload_creates_catalog.py`

**Step 1: Rewrite the file**

```python
"""Tests that the upload + finalize flow creates CatalogEntries (ADR-025).

upload now returns a preview only (parse-only).
CatalogEntry creation happens in POST /api/v1/requirements/finalize.
"""
import io
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


CSV_CONTENT = (
    "ReqID,Source,Target,Category,Description\n"
    "REQ-101,ERP,PLM,Product Collection,Sync articles from ERP to PLM.\n"
    "REQ-102,PLM,PIM,Enrichment INIT,Create shell product in PIM.\n"
    "REQ-103,DAM,PIM,Image Collection,Link images to PIM SKU.\n"
)

_PROJECT = {"prefix": "TST", "client_name": "Test Corp", "domain": "Testing"}


def test_upload_returns_preview_not_integrations_created(client):
    """Upload must return 'preview' key, not 'integrations_created'."""
    import main
    main.catalog.clear()
    main.parsed_requirements.clear()

    resp = client.post(
        "/api/v1/requirements/upload",
        files={"file": ("reqs.csv", io.BytesIO(CSV_CONTENT.encode()), "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "parsed"
    assert "preview" in data
    assert "integrations_created" not in data
    # Catalog must still be empty — finalize not called yet
    assert len(main.catalog) == 0


def test_finalize_creates_catalog_entries(client):
    """upload + finalize → 3 CatalogEntries with TST- prefix."""
    import main
    main.catalog.clear()
    main.parsed_requirements.clear()
    main.projects.clear()

    client.post(
        "/api/v1/requirements/upload",
        files={"file": ("reqs.csv", io.BytesIO(CSV_CONTENT.encode()), "text/csv")},
    )
    client.post("/api/v1/projects", json=_PROJECT)
    resp = client.post("/api/v1/requirements/finalize", json={"project_id": "TST"})

    assert resp.status_code == 200
    assert resp.json()["integrations_created"] == 3

    # ERP→PLM, PLM→PIM, DAM→PIM = 3 unique pairs
    assert len(main.catalog) == 3
    for entry in main.catalog.values():
        assert entry.status == "PENDING_TAG_REVIEW"
        assert entry.project_id == "TST"
        assert entry.id.startswith("TST-")
```

**Step 2: Run updated tests**

```bash
pytest tests/test_upload_creates_catalog.py -v
```

Expected: 2 tests PASS.

**Step 3: Commit**

```bash
git add services/integration-agent/tests/test_upload_creates_catalog.py
git commit -m "test: rewrite test_upload_creates_catalog.py for two-step upload+finalize flow (ADR-025)"
```

---

## Task 11: Tests — Update test_trigger_gate.py

`_upload_csv()` helper currently relies on upload creating catalog entries. Update it to use the two-step flow.

**Files:**
- Modify: `services/integration-agent/tests/test_trigger_gate.py`

**Step 1: Update the helper and add project setup**

```python
"""Tests that trigger is blocked when entries are in PENDING_TAG_REVIEW."""
import io
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


_CSV = (
    "ReqID,Source,Target,Category,Description\n"
    "REQ-101,ERP,PLM,Sync,Sync articles.\n"
)
_PROJECT = {"prefix": "GTE", "client_name": "Gate Test Corp", "domain": "Testing"}


def _upload_and_finalize(client):
    """Upload CSV + create project + finalize → creates CatalogEntries."""
    client.post(
        "/api/v1/requirements/upload",
        files={"file": ("reqs.csv", io.BytesIO(_CSV.encode()), "text/csv")},
    )
    client.post("/api/v1/projects", json=_PROJECT)
    client.post("/api/v1/requirements/finalize", json={"project_id": "GTE"})


def test_trigger_blocked_when_pending_tag_review(client):
    import main
    main.catalog.clear()
    main.parsed_requirements.clear()
    main.projects.clear()
    _upload_and_finalize(client)
    # All entries are PENDING_TAG_REVIEW — trigger must be blocked
    resp = client.post("/api/v1/agent/trigger")
    assert resp.status_code == 409
    assert "tag" in resp.json()["detail"].lower()


def test_trigger_allowed_when_all_tag_confirmed(client):
    import main
    main.catalog.clear()
    main.parsed_requirements.clear()
    main.projects.clear()
    _upload_and_finalize(client)
    # Force all entries to TAG_CONFIRMED
    for entry in main.catalog.values():
        entry.status = "TAG_CONFIRMED"
        entry.tags = ["Sync"]
    # Trigger should start (may fail later due to Ollama, but not 409 from tag gate)
    resp = client.post("/api/v1/agent/trigger")
    assert resp.status_code in (200, 400, 500)  # not 409 from tag gate
```

**Step 2: Run updated tests**

```bash
pytest tests/test_trigger_gate.py -v
```

Expected: both PASS.

**Step 3: Run full suite to verify no regressions**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all 171+ tests pass (0 failures).

**Step 4: Commit**

```bash
git add services/integration-agent/tests/test_trigger_gate.py
git commit -m "test: update test_trigger_gate.py to use upload+finalize two-step flow (ADR-025)"
```

---

## Task 12: Frontend — api.js new methods

**Files:**
- Modify: `services/web-dashboard/js/api.js`

**Step 1: Add project and finalize API methods**

Find the end of the API object (just before the closing `};`). Add:

```javascript
    // ── Projects (ADR-025) ──
    async createProject(data) {
        const resp = await fetch(`${this.AGENT}/api/v1/projects`, {
            method: 'POST',
            headers: this.headers(),
            body: JSON.stringify(data),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        return resp.json();
    },

    async listProjects() {
        const resp = await fetch(`${this.AGENT}/api/v1/projects`, { headers: this.headers() });
        return resp.json();
    },

    async getProject(prefix) {
        const resp = await fetch(`${this.AGENT}/api/v1/projects/${encodeURIComponent(prefix)}`, {
            headers: this.headers(),
        });
        return resp.json();
    },

    async finalizeRequirements(projectId) {
        const resp = await fetch(`${this.AGENT}/api/v1/requirements/finalize`, {
            method: 'POST',
            headers: this.headers(),
            body: JSON.stringify({ project_id: projectId }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        return resp.json();
    },

    async getCatalogEntries({ projectId, domain, accentureRef } = {}) {
        const params = new URLSearchParams();
        if (projectId)     params.set('project_id', projectId);
        if (domain)        params.set('domain', domain);
        if (accentureRef)  params.set('accenture_ref', accentureRef);
        const qs = params.toString() ? `?${params}` : '';
        const resp = await fetch(`${this.AGENT}/api/v1/catalog/integrations${qs}`, {
            headers: this.headers(),
        });
        return resp.json();
    },
```

> **Note:** `getCatalogEntries` is being **replaced** — find the existing method (around line 44) and delete it, then use the new version above that accepts optional filter params.

**Step 2: Commit**

```bash
git add services/web-dashboard/js/api.js
git commit -m "feat: add API.createProject, listProjects, getProject, finalizeRequirements; extend getCatalogEntries with filter params"
```

---

## Task 13: Frontend — Project Modal + updated uploadCsv()

**Files:**
- Modify: `services/web-dashboard/js/app.js`

**Step 1: Add prefix auto-generation helper**

Add this utility function near the top of `app.js` (after the `escapeHtml` or `truncate` helpers):

```javascript
// ── Project helpers ──────────────────────────────────────────────────────────

/**
 * Auto-generate a 1-3 char uppercase prefix from a client name.
 * "Acme Corp" → "AC" | "Global Fashion Group" → "GFG" | "Salsify" → "SAL"
 */
function generatePrefix(clientName) {
    const clean = clientName.trim();
    if (!clean) return '';
    const words = clean.split(/\s+/).filter(Boolean);
    let prefix;
    if (words.length === 1) {
        prefix = words[0].replace(/[^A-Z0-9]/gi, '').toUpperCase().slice(0, 3);
    } else {
        prefix = words.map(w => w[0]).join('').replace(/[^A-Z0-9]/gi, '').toUpperCase().slice(0, 3);
    }
    return prefix;
}
```

**Step 2: Add `showProjectModal()` function**

Add this function after `loadRequirementsList()`:

```javascript
// ── Project Modal (ADR-025) ───────────────────────────────────────────────────

let _prefixCheckTimer = null;
let _resolvedProjectId = null;   // set when existing project found

async function showProjectModal(preview) {
    // Remove any existing modal
    document.getElementById('projectModal')?.remove();

    const integrationLines = preview.map(p =>
        `<li><span class="badge badge-primary">${escapeHtml(p.source)}</span> → <span class="badge badge-info" style="background:var(--info)">${escapeHtml(p.target)}</span></li>`
    ).join('');

    const modal = document.createElement('div');
    modal.id = 'projectModal';
    modal.style.cssText = `
        position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;
        display:flex;align-items:center;justify-content:center;`;
    modal.innerHTML = `
        <div style="background:var(--bg-secondary);border-radius:12px;padding:32px;width:480px;
                    max-width:95vw;box-shadow:0 20px 60px rgba(0,0,0,.4);">
            <h3 style="margin:0 0 8px;color:var(--text-primary)">📋 Informazioni Progetto</h3>
            <p style="margin:0 0 20px;color:var(--text-secondary);font-size:14px;">
                Trovati <strong>${preview.reduce((s,_)=>s,0) || preview.length}</strong> pair(s) di integrazione:
                <ul style="margin:4px 0 0 16px;padding:0;">${integrationLines}</ul>
            </p>

            <div style="display:flex;flex-direction:column;gap:14px;">
                <div>
                    <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px;">
                        Nome Cliente <span style="color:var(--error)">*</span>
                    </label>
                    <input id="pm-client" type="text" placeholder="Acme Corp"
                        style="width:100%;box-sizing:border-box;padding:8px 12px;border-radius:6px;
                               border:1px solid var(--border);background:var(--bg-primary);
                               color:var(--text-primary);font-size:14px;" />
                </div>
                <div>
                    <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px;">
                        Dominio Integrazione <span style="color:var(--error)">*</span>
                    </label>
                    <input id="pm-domain" type="text" placeholder="Fashion Retail"
                        style="width:100%;box-sizing:border-box;padding:8px 12px;border-radius:6px;
                               border:1px solid var(--border);background:var(--bg-primary);
                               color:var(--text-primary);font-size:14px;" />
                </div>
                <div>
                    <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px;">
                        Prefisso
                        <span style="color:var(--text-secondary);font-size:11px;">(auto-generato, max 3 car.)</span>
                    </label>
                    <div style="display:flex;gap:8px;align-items:center;">
                        <input id="pm-prefix" type="text" maxlength="3" placeholder="ACM"
                            style="width:80px;padding:8px 12px;border-radius:6px;
                                   border:1px solid var(--border);background:var(--bg-primary);
                                   color:var(--text-primary);font-size:14px;text-transform:uppercase;" />
                        <span id="pm-prefix-status" style="font-size:13px;"></span>
                    </div>
                </div>
                <div>
                    <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px;">
                        Descrizione
                    </label>
                    <input id="pm-desc" type="text" placeholder="Opzionale"
                        style="width:100%;box-sizing:border-box;padding:8px 12px;border-radius:6px;
                               border:1px solid var(--border);background:var(--bg-primary);
                               color:var(--text-primary);font-size:14px;" />
                </div>
                <div>
                    <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px;">
                        Riferimento Accenture
                    </label>
                    <input id="pm-ref" type="text" placeholder="Mario Rossi"
                        style="width:100%;box-sizing:border-box;padding:8px 12px;border-radius:6px;
                               border:1px solid var(--border);background:var(--bg-primary);
                               color:var(--text-primary);font-size:14px;" />
                </div>
            </div>

            <div style="margin-top:24px;display:flex;justify-content:flex-end;gap:12px;">
                <button id="pm-cancel" class="btn btn-secondary">Annulla</button>
                <button id="pm-confirm" class="btn btn-primary" disabled>Conferma →</button>
            </div>
        </div>`;

    document.body.appendChild(modal);
    _resolvedProjectId = null;

    const clientInput  = document.getElementById('pm-client');
    const prefixInput  = document.getElementById('pm-prefix');
    const domainInput  = document.getElementById('pm-domain');
    const prefixStatus = document.getElementById('pm-prefix-status');
    const confirmBtn   = document.getElementById('pm-confirm');

    function updateConfirmState() {
        const ready = clientInput.value.trim() && domainInput.value.trim() && prefixInput.value.trim();
        confirmBtn.disabled = !ready;
    }

    async function checkPrefix() {
        const prefix = prefixInput.value.toUpperCase().trim();
        if (!prefix || !/^[A-Z0-9]{1,3}$/.test(prefix)) {
            prefixStatus.innerHTML = '';
            _resolvedProjectId = null;
            updateConfirmState();
            return;
        }
        try {
            const data = await API.getProject(prefix);
            const found = data?.data;
            const clientName = clientInput.value.trim();
            if (found.client_name.toLowerCase() === clientName.toLowerCase()) {
                prefixStatus.innerHTML = `<span style="color:var(--success)">✅ ${escapeHtml(found.client_name)} esiste già. I documenti saranno aggiunti al progetto <strong>${escapeHtml(prefix)}</strong>.</span>`;
                _resolvedProjectId = prefix;
                confirmBtn.disabled = false;
            } else {
                prefixStatus.innerHTML = `<span style="color:var(--error)">❌ Prefisso già usato da <strong>${escapeHtml(found.client_name)}</strong>. Modifica il prefisso.</span>`;
                _resolvedProjectId = null;
                confirmBtn.disabled = true;
            }
        } catch (_) {
            // 404 → prefix is free
            prefixStatus.innerHTML = '';
            _resolvedProjectId = null;
            updateConfirmState();
        }
    }

    clientInput.addEventListener('input', () => {
        prefixInput.value = generatePrefix(clientInput.value);
        clearTimeout(_prefixCheckTimer);
        _prefixCheckTimer = setTimeout(checkPrefix, 400);
        updateConfirmState();
    });

    prefixInput.addEventListener('input', () => {
        prefixInput.value = prefixInput.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
        clearTimeout(_prefixCheckTimer);
        _prefixCheckTimer = setTimeout(checkPrefix, 400);
        updateConfirmState();
    });

    domainInput.addEventListener('input', updateConfirmState);

    document.getElementById('pm-cancel').addEventListener('click', () => modal.remove());

    document.getElementById('pm-confirm').addEventListener('click', async () => {
        const prefix      = prefixInput.value.toUpperCase().trim();
        const clientName  = clientInput.value.trim();
        const domain      = domainInput.value.trim();
        const description = document.getElementById('pm-desc').value.trim() || null;
        const accentureRef= document.getElementById('pm-ref').value.trim() || null;

        confirmBtn.disabled = true;
        confirmBtn.textContent = 'Saving...';

        try {
            if (!_resolvedProjectId) {
                await API.createProject({ prefix, client_name: clientName, domain, description, accenture_ref: accentureRef });
            }
            const finalizeData = await API.finalizeRequirements(prefix);
            modal.remove();
            const res = document.getElementById('uploadResult');
            if (res) res.innerHTML = `<span style="color:var(--success)">✅ ${finalizeData.integrations_created} integrazione/i create sotto il progetto <strong>${escapeHtml(prefix)}</strong> (${escapeHtml(clientName)}).</span>`;
            loadRequirementsList();
            fetchAndShowTagConfirmation();
        } catch (err) {
            confirmBtn.disabled = false;
            confirmBtn.textContent = 'Conferma →';
            prefixStatus.innerHTML = `<span style="color:var(--error)">❌ ${escapeHtml(err.message)}</span>`;
        }
    });

    // Focus client name field
    setTimeout(() => clientInput.focus(), 50);
}
```

**Step 3: Update `uploadCsv()` to show modal instead of calling finalize directly**

Replace the existing `uploadCsv()` function:

```javascript
async function uploadCsv() {
    const fileInput = document.getElementById('csvFile');
    const res = document.getElementById('uploadResult');
    if (!fileInput.files[0]) {
        res.innerHTML = '<span style="color:var(--error)">Please select a file.</span>';
        return;
    }
    res.innerHTML = '<span style="color:var(--info)">Uploading and parsing...</span>';
    try {
        const data = await API.uploadRequirements(fileInput.files[0]);
        res.innerHTML = `<span style="color:var(--info)">✔ Parsed ${data.total_parsed || 0} requirements. Fill project info to continue.</span>`;
        loadRequirementsList();
        // Show project modal; tag confirmation will run after finalize inside the modal
        showProjectModal(data.preview || []);
    } catch (e) {
        res.innerHTML = `<span style="color:var(--error)">❌ Error: ${escapeHtml(e.message)}</span>`;
    }
}
```

**Step 4: Commit**

```bash
git add services/web-dashboard/js/app.js
git commit -m "feat: add Project Modal with prefix auto-gen, uniqueness check, finalize on confirm (ADR-025)"
```

---

## Task 14: Frontend — Catalog filter bar + updated cards

**Files:**
- Modify: `services/web-dashboard/js/app.js`

**Step 1: Add catalog filter state variables**

Near the top of `app.js` where other module-level state variables are (near `_cachedLogs` etc.), add:

```javascript
// ── Catalog filter state (ADR-025) ───────────────────────────────────────────
let _catalogFilterProjectId = '';
let _catalogFilterDomain    = '';
let _catalogFilterAccRef    = '';
```

**Step 2: Replace `renderCatalog()` with filter-aware version**

Replace the entire `renderCatalog()` function with:

```javascript
async function renderCatalog() {
    const area = document.getElementById('contentArea');
    area.innerHTML = '<div class="loading">Loading catalog integrations...</div>';

    try {
        // Fetch projects for filter dropdown
        const projectsData = await API.listProjects();
        const allProjects  = projectsData?.data || [];

        // Fetch catalog entries (with active filters)
        const catalogData = await API.getCatalogEntries({
            projectId:    _catalogFilterProjectId || undefined,
            domain:       _catalogFilterDomain    || undefined,
            accentureRef: _catalogFilterAccRef    || undefined,
        });
        const items = catalogData?.data || [];

        // Build project dropdown options
        const projectOptions = [
            '<option value="">Tutti i clienti</option>',
            ...allProjects.map(p =>
                `<option value="${escapeHtml(p.prefix)}" ${_catalogFilterProjectId === p.prefix ? 'selected' : ''}>
                    ${escapeHtml(p.prefix)} · ${escapeHtml(p.client_name)}
                </option>`
            )
        ].join('');

        // Filter bar HTML
        const filterBar = `
            <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;
                        margin-bottom:20px;padding:16px;background:var(--bg-secondary);
                        border-radius:8px;border:1px solid var(--border);">
                <div>
                    <label style="font-size:12px;color:var(--text-secondary);display:block;margin-bottom:4px;">🏢 Cliente</label>
                    <select id="cf-project" onchange="onCatalogFilterChange()"
                        style="padding:6px 10px;border-radius:6px;border:1px solid var(--border);
                               background:var(--bg-primary);color:var(--text-primary);font-size:13px;">
                        ${projectOptions}
                    </select>
                </div>
                <div>
                    <label style="font-size:12px;color:var(--text-secondary);display:block;margin-bottom:4px;">🏷️ Dominio</label>
                    <input id="cf-domain" type="text" value="${escapeHtml(_catalogFilterDomain)}"
                        placeholder="Partial match..." oninput="onCatalogFilterChange()"
                        style="padding:6px 10px;border-radius:6px;border:1px solid var(--border);
                               background:var(--bg-primary);color:var(--text-primary);font-size:13px;width:160px;" />
                </div>
                <div>
                    <label style="font-size:12px;color:var(--text-secondary);display:block;margin-bottom:4px;">👤 Ref. Accenture</label>
                    <input id="cf-ref" type="text" value="${escapeHtml(_catalogFilterAccRef)}"
                        placeholder="Partial match..." oninput="onCatalogFilterChange()"
                        style="padding:6px 10px;border-radius:6px;border:1px solid var(--border);
                               background:var(--bg-primary);color:var(--text-primary);font-size:13px;width:160px;" />
                </div>
                <button class="btn btn-secondary btn-sm" onclick="resetCatalogFilters()"
                    style="padding:6px 14px;font-size:13px;align-self:flex-end;">Reset filtri</button>
            </div>`;

        // Cards
        const cards = items.length === 0
            ? `<div class="empty-state"><div class="icon">📋</div><h3>Nessun risultato</h3>
               <p>Nessuna integrazione trovata con i filtri selezionati.</p></div>`
            : `<div class="card-grid">${items.map(i => {
                const proj = i._project || {};
                return `
                <div class="card">
                    <div class="card-header">
                        <div>
                            <div class="card-title">
                                <span style="background:var(--primary);color:#fff;border-radius:4px;
                                             padding:2px 7px;font-size:11px;font-weight:700;
                                             margin-right:8px;">${escapeHtml(i.project_id || '')}</span>
                                ${escapeHtml(i.name)}
                            </div>
                            <div class="card-subtitle">${escapeHtml(i.id)} · ${escapeHtml(i.type)}</div>
                        </div>
                        <span class="badge badge-${i.status === 'generated' ? 'success' : 'info'}">${escapeHtml(i.status)}</span>
                    </div>
                    <div class="card-body">
                        ${escapeHtml(i.source?.system || '?')} → ${escapeHtml(i.target?.system || '?')}
                    </div>
                    ${proj.client_name ? `
                    <div style="padding:8px 0 4px;font-size:13px;color:var(--text-secondary);
                                border-top:1px solid var(--border);margin-top:8px;">
                        🏢 ${escapeHtml(proj.client_name)} &nbsp;•&nbsp; ${escapeHtml(proj.domain || '')}
                        ${proj.accenture_ref ? `<br>👤 ${escapeHtml(proj.accenture_ref)}` : ''}
                    </div>` : ''}
                    <div class="card-footer">
                        ${(i.requirements || []).map(r => `<span class="badge badge-primary">${escapeHtml(r)}</span>`).join('')}
                    </div>
                </div>`;
            }).join('')}</div>`;

        area.innerHTML = filterBar + cards;

    } catch (e) {
        area.innerHTML = `<div class="empty-state"><div class="icon">⚠️</div>
            <h3>Connection Error</h3><p>${escapeHtml(e.message)}</p></div>`;
    }
}

let _catalogFilterTimer = null;
function onCatalogFilterChange() {
    _catalogFilterProjectId = document.getElementById('cf-project')?.value || '';
    _catalogFilterDomain    = document.getElementById('cf-domain')?.value  || '';
    _catalogFilterAccRef    = document.getElementById('cf-ref')?.value     || '';
    // Debounce text inputs
    clearTimeout(_catalogFilterTimer);
    _catalogFilterTimer = setTimeout(renderCatalog, 300);
}

function resetCatalogFilters() {
    _catalogFilterProjectId = '';
    _catalogFilterDomain    = '';
    _catalogFilterAccRef    = '';
    renderCatalog();
}
```

**Step 3: Commit**

```bash
git add services/web-dashboard/js/app.js
git commit -m "feat: add catalog filter bar (client dropdown, domain, accenture ref) and project metadata in cards (ADR-025)"
```

---

## Task 15: ADR-025 + full regression + push

**Files:**
- Create: `docs/adr/ADR-025-project-metadata-upload-modal.md`
- Run: full test suite

**Step 1: Create ADR-025**

```bash
cat > docs/adr/ADR-025-project-metadata-upload-modal.md << 'EOF'
# ADR-025 — Project Metadata & Upload Modal

| Field        | Value                              |
|--------------|------------------------------------|
| **Status**   | Accepted                           |
| **Date**     | 2026-03-19                         |
| **Deciders** | Integration Mate PoC team          |
| **Tags**     | project, client, upload, catalog   |

## Context

Every CSV upload produced anonymous integrations with meaningless `INT-` IDs.
No concept of client, project, or domain existed, making the tool unsuitable
for multi-client professional delivery.

## Decision

Introduce a `Project` entity (prefix, client_name, domain, description, accenture_ref).
Upload is split into parse-only + `/finalize` (requires a project_id).
Integration IDs use the project prefix (e.g., `ACM-4F2A1B`).
A project modal is shown after CSV parse, before tag confirmation.
The Catalog accepts filter query params: `project_id`, `domain`, `accenture_ref`.

## Consequences

- Integration IDs are now meaningful and client-traceable.
- Multiple uploads for the same client accumulate under one project.
- Existing `INT-xxx` entries (if any) carry `project_id="LEGACY"` as default.
- All unit tests updated to use two-step upload+finalize flow.

## References

- Design doc: `docs/plans/2026-03-19-project-metadata-upload-modal-design.md`
- ADR-013: MongoDB persistence pattern
- ADR-016: Pydantic Settings env-var pattern
EOF
```

**Step 2: Run full test suite**

```bash
cd services/integration-agent
pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: **all tests pass**, count ≥ 171.

**Step 3: Commit and push**

```bash
git add docs/adr/ADR-025-project-metadata-upload-modal.md
git commit -m "docs: add ADR-025 project metadata upload modal"
git push origin main
```

---

## Summary

| Task | Backend / Frontend | Files touched |
|------|--------------------|---------------|
| 1 | Backend | `schemas.py` |
| 2 | Backend | `db.py`, `main.py` (state) |
| 3 | Backend | `main.py` (project endpoints) |
| 4 | Backend | `main.py` (upload parse-only) |
| 5 | Backend | `main.py` (finalize endpoint) |
| 6 | Backend | `main.py` (catalog filter) |
| 7 | Tests | `tests/test_projects.py` (new) |
| 8 | Tests | `tests/test_finalize_requirements.py` (new) |
| 9 | Tests | `tests/test_catalog_filter.py` (new) |
| 10 | Tests | `tests/test_upload_creates_catalog.py` (rewrite) |
| 11 | Tests | `tests/test_trigger_gate.py` (update helper) |
| 12 | Frontend | `api.js` |
| 13 | Frontend | `app.js` (modal + uploadCsv) |
| 14 | Frontend | `app.js` (catalog filter + cards) |
| 15 | Docs | `docs/adr/ADR-025-...md` |
