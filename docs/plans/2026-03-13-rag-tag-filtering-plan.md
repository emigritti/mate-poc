# RAG Tag-Filtering Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Introduce HITL tag-confirmation before LLM generation so ChromaDB is queried with category metadata filters, improving RAG relevance and reducing prompt size.

**Architecture:** CatalogEntry creation is split from document generation. Upload now creates entries with `PENDING_TAG_REVIEW`; suggest-tags + confirm-tags operate on them; trigger validates all entries are `TAG_CONFIRMED` before starting generation. RAG queries ChromaDB with a `tags_csv` metadata filter, falling back to similarity-only with a warning log.

**Tech Stack:** FastAPI, Pydantic v2, ChromaDB, Motor (MongoDB), httpx, vanilla JS (web-dashboard)

---

## Reference files

| File | Role |
|------|------|
| `services/integration-agent/schemas.py` | Pydantic models |
| `services/integration-agent/main.py` | All endpoints + RAG flow |
| `services/integration-agent/config.py` | Settings |
| `services/integration-agent/tests/test_agent_flow.py` | Existing flow tests (needs update) |
| `services/web-dashboard/js/app.js` | Frontend |

Run all tests from: `cd services/integration-agent && python -m pytest tests/ -v`

---

## Task 1: Schema changes — CatalogEntry + new request/response models

**Files:**
- Modify: `services/integration-agent/schemas.py`

### Step 1: Write the failing test

Create `services/integration-agent/tests/test_schemas.py`:

```python
"""Tests for new schema fields and models (Task 1)."""
from schemas import CatalogEntry, ConfirmTagsRequest, SuggestTagsResponse


def test_catalog_entry_has_tags_field():
    entry = CatalogEntry(
        id="INT-001", name="A", type="Auto", source={"system": "ERP"},
        target={"system": "PLM"}, requirements=[], status="PENDING_TAG_REVIEW",
        created_at="2026-01-01T00:00:00Z",
    )
    assert entry.tags == []


def test_catalog_entry_tags_populated():
    entry = CatalogEntry(
        id="INT-001", name="A", type="Auto", source={"system": "ERP"},
        target={"system": "PLM"}, requirements=[], status="TAG_CONFIRMED",
        tags=["Sync", "PLM"], created_at="2026-01-01T00:00:00Z",
    )
    assert entry.tags == ["Sync", "PLM"]


def test_confirm_tags_request_valid():
    body = ConfirmTagsRequest(tags=["Sync", "PLM", "Custom"])
    assert body.tags == ["Sync", "PLM", "Custom"]


def test_confirm_tags_request_too_many():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ConfirmTagsRequest(tags=["A", "B", "C", "D", "E", "F"])


def test_confirm_tags_request_empty_list():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ConfirmTagsRequest(tags=[])


def test_suggest_tags_response():
    r = SuggestTagsResponse(
        integration_id="INT-001",
        suggested_tags=["Sync", "PLM"],
        source={"from_categories": ["Sync"], "from_llm": ["PLM"]},
    )
    assert r.integration_id == "INT-001"
    assert len(r.suggested_tags) == 2
```

### Step 2: Run to verify it fails

```bash
cd services/integration-agent && python -m pytest tests/test_schemas.py -v
```

Expected: `ImportError` or `AttributeError` — `tags`, `ConfirmTagsRequest`, `SuggestTagsResponse` not yet defined.

### Step 3: Implement schema changes

In `services/integration-agent/schemas.py`, add `tags` to `CatalogEntry` and two new models at the bottom:

```python
# In CatalogEntry — add tags field after status:
class CatalogEntry(BaseModel):
    id: str
    name: str
    type: str
    source: Dict[str, str]
    target: Dict[str, str]
    requirements: List[str]
    status: str
    tags: List[str] = []          # confirmed tags (max 5)
    created_at: str


# New models — add after existing models:

class ConfirmTagsRequest(BaseModel):
    """Body for POST /api/v1/catalog/integrations/{id}/confirm-tags."""
    tags: List[str] = Field(
        min_length=1,
        max_length=5,
        description="Confirmed tags (1–5 items). Each tag max 50 chars.",
    )


class SuggestTagsResponse(BaseModel):
    """Response for GET /api/v1/catalog/integrations/{id}/suggest-tags."""
    integration_id: str
    suggested_tags: List[str]
    source: Dict[str, List[str]]
```

### Step 4: Run tests to verify they pass

```bash
cd services/integration-agent && python -m pytest tests/test_schemas.py -v
```

Expected: 6 tests PASS.

### Step 5: Run full suite to check no regressions

```bash
cd services/integration-agent && python -m pytest tests/ -v
```

Expected: all existing 50 tests PASS + 6 new = 56 total.

### Step 6: Commit

```bash
git add services/integration-agent/schemas.py services/integration-agent/tests/test_schemas.py
git commit -m "feat(schema): add tags field to CatalogEntry, ConfirmTagsRequest, SuggestTagsResponse"
```

---

## Task 2: Tag extraction — pure function from Requirement categories

**Files:**
- Modify: `services/integration-agent/main.py` (add helper function before `run_agentic_rag_flow`)
- Test: `services/integration-agent/tests/test_tag_suggestion.py`

### Step 1: Write the failing tests (category extraction only)

Create `services/integration-agent/tests/test_tag_suggestion.py`:

```python
"""Tests for tag suggestion logic (Task 2 + Task 3)."""
import pytest
from schemas import Requirement


# ── Helpers ──────────────────────────────────────────────────────────────────
def _make_req(category: str, source: str = "ERP", target: str = "PLM") -> Requirement:
    return Requirement(
        req_id="R-001", source_system=source, target_system=target,
        category=category, description="test req",
    )


# ── Task 2: category extraction ───────────────────────────────────────────────
def test_extract_category_tags_unique():
    from main import _extract_category_tags
    reqs = [_make_req("Sync"), _make_req("Sync"), _make_req("Enrichment")]
    tags = _extract_category_tags(reqs)
    assert tags == ["Sync", "Enrichment"]  # unique, order-preserving


def test_extract_category_tags_empty():
    from main import _extract_category_tags
    assert _extract_category_tags([]) == []


def test_extract_category_tags_strips_whitespace():
    from main import _extract_category_tags
    reqs = [_make_req("  Sync  "), _make_req("Sync")]
    tags = _extract_category_tags(reqs)
    assert tags == ["Sync"]


def test_extract_category_tags_max_5():
    from main import _extract_category_tags
    reqs = [_make_req(f"Cat{i}") for i in range(10)]
    tags = _extract_category_tags(reqs)
    assert len(tags) <= 5
```

### Step 2: Run to verify it fails

```bash
cd services/integration-agent && python -m pytest tests/test_tag_suggestion.py::test_extract_category_tags_unique -v
```

Expected: `ImportError: cannot import name '_extract_category_tags' from 'main'`

### Step 3: Implement `_extract_category_tags`

In `services/integration-agent/main.py`, add this function immediately before `run_agentic_rag_flow` (around line 287):

```python
# ── Tag helpers ───────────────────────────────────────────────────────────────

def _extract_category_tags(reqs: list[Requirement]) -> list[str]:
    """Return unique, whitespace-stripped category values from requirements (max 5)."""
    seen: list[str] = []
    for r in reqs:
        tag = r.category.strip()
        if tag and tag not in seen:
            seen.append(tag)
        if len(seen) >= 5:
            break
    return seen
```

### Step 4: Run tests to verify they pass

```bash
cd services/integration-agent && python -m pytest tests/test_tag_suggestion.py -k "extract_category" -v
```

Expected: 4 tests PASS.

### Step 5: Full suite check

```bash
cd services/integration-agent && python -m pytest tests/ -v
```

Expected: all tests pass.

### Step 6: Commit

```bash
git add services/integration-agent/main.py services/integration-agent/tests/test_tag_suggestion.py
git commit -m "feat(tags): add _extract_category_tags helper"
```

---

## Task 3: LLM tag suggestion — async helper

**Files:**
- Modify: `services/integration-agent/main.py` (add after `_extract_category_tags`)

### Step 1: Add tests for LLM tag suggestion

Append to `services/integration-agent/tests/test_tag_suggestion.py`:

```python
# ── Task 3: LLM tag suggestion ────────────────────────────────────────────────
import asyncio
from unittest.mock import AsyncMock, patch


def test_suggest_tags_via_llm_valid_json(monkeypatch):
    from main import _suggest_tags_via_llm
    monkeypatch.setattr(
        "main.generate_with_ollama",
        AsyncMock(return_value='["Data Sync", "Real-time"]'),
    )
    result = asyncio.get_event_loop().run_until_complete(
        _suggest_tags_via_llm("ERP", "PLM", "sync products daily")
    )
    assert result == ["Data Sync", "Real-time"]


def test_suggest_tags_via_llm_malformed_json(monkeypatch):
    from main import _suggest_tags_via_llm
    monkeypatch.setattr(
        "main.generate_with_ollama",
        AsyncMock(return_value="Sure! Tags are: Sync, Export"),
    )
    result = asyncio.get_event_loop().run_until_complete(
        _suggest_tags_via_llm("ERP", "PLM", "sync products")
    )
    assert result == []   # graceful fallback on parse failure


def test_suggest_tags_via_llm_exception(monkeypatch):
    from main import _suggest_tags_via_llm
    monkeypatch.setattr(
        "main.generate_with_ollama",
        AsyncMock(side_effect=Exception("Ollama timeout")),
    )
    result = asyncio.get_event_loop().run_until_complete(
        _suggest_tags_via_llm("ERP", "PLM", "sync products")
    )
    assert result == []   # never raises


def test_suggest_tags_via_llm_max_2(monkeypatch):
    from main import _suggest_tags_via_llm
    monkeypatch.setattr(
        "main.generate_with_ollama",
        AsyncMock(return_value='["A", "B", "C", "D"]'),
    )
    result = asyncio.get_event_loop().run_until_complete(
        _suggest_tags_via_llm("ERP", "PLM", "sync products")
    )
    assert len(result) <= 2
```

### Step 2: Run to verify it fails

```bash
cd services/integration-agent && python -m pytest tests/test_tag_suggestion.py -k "llm" -v
```

Expected: `ImportError` — `_suggest_tags_via_llm` not defined.

### Step 3: Implement `_suggest_tags_via_llm`

Add after `_extract_category_tags` in `main.py`:

```python
async def _suggest_tags_via_llm(source: str, target: str, req_text: str) -> list[str]:
    """Call LLM with a lightweight prompt to suggest up to 2 integration tags.

    Returns empty list on any failure (timeout, parse error, etc.) so the
    caller can safely ignore LLM tags and fall back to category-only tags.
    """
    short_req = req_text[:500]
    prompt = (
        f"Given this integration between {source} and {target} "
        f"with these requirements:\n{short_req}\n"
        "Suggest up to 2 short tags (1-3 words each) that best categorize "
        "this integration.\n"
        'Reply with a JSON array only. Example: ["Data Sync", "Real-time"]'
    )
    try:
        raw = await generate_with_ollama(prompt)
        # Extract JSON array from response (LLM may wrap it in prose)
        import re as _re
        match = _re.search(r"\[.*?\]", raw, _re.DOTALL)
        if not match:
            return []
        tags = json.loads(match.group())
        if not isinstance(tags, list):
            return []
        return [str(t).strip() for t in tags if str(t).strip()][:2]
    except Exception as exc:
        logger.warning("[Tags] LLM tag suggestion failed: %s", exc)
        return []
```

Note: `json` is already imported at the top of `main.py` (used elsewhere). If not present, add `import json` with the other imports.

### Step 4: Run tests to verify they pass

```bash
cd services/integration-agent && python -m pytest tests/test_tag_suggestion.py -v
```

Expected: all 8 tests PASS.

### Step 5: Full suite check

```bash
cd services/integration-agent && python -m pytest tests/ -v
```

### Step 6: Commit

```bash
git add services/integration-agent/main.py services/integration-agent/tests/test_tag_suggestion.py
git commit -m "feat(tags): add _suggest_tags_via_llm helper with graceful fallback"
```

---

## Task 4: Modify upload endpoint to create CatalogEntries with PENDING_TAG_REVIEW

**Files:**
- Modify: `services/integration-agent/main.py` — `upload_requirements` endpoint (~line 432–465)

This is the key architectural split: CatalogEntry creation moves from `run_agentic_rag_flow` to upload time.

### Step 1: Write the failing test

Create `services/integration-agent/tests/test_upload_creates_catalog.py`:

```python
"""Tests that upload creates CatalogEntries with PENDING_TAG_REVIEW status."""
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


def test_upload_creates_catalog_entries(client):
    import main
    main.catalog.clear()
    main.parsed_requirements.clear()

    resp = client.post(
        "/api/v1/requirements/upload",
        files={"file": ("reqs.csv", io.BytesIO(CSV_CONTENT.encode()), "text/csv")},
    )
    assert resp.status_code == 200

    # Catalog entries should be created (grouped by source→target)
    assert len(main.catalog) == 2  # ERP→PLM and PLM/DAM→PIM = actually 3 unique pairs
    # All entries should be PENDING_TAG_REVIEW
    for entry in main.catalog.values():
        assert entry.status == "PENDING_TAG_REVIEW"


def test_upload_catalog_entry_count(client):
    """3 requirements across 3 unique source→target pairs = 3 entries."""
    import main
    main.catalog.clear()
    main.parsed_requirements.clear()

    resp = client.post(
        "/api/v1/requirements/upload",
        files={"file": ("reqs.csv", io.BytesIO(CSV_CONTENT.encode()), "text/csv")},
    )
    assert resp.status_code == 200
    # ERP→PLM (REQ-101), PLM→PIM (REQ-102), DAM→PIM (REQ-103) = 3 groups
    assert len(main.catalog) == 3
```

### Step 2: Run to verify it fails

```bash
cd services/integration-agent && python -m pytest tests/test_upload_creates_catalog.py -v
```

Expected: FAIL — `len(main.catalog) == 0` because upload doesn't create entries yet.

### Step 3: Implement — modify upload endpoint

In `main.py`, in the `upload_requirements` function, add catalog entry creation after `parsed_requirements.append(req)` loop ends (around line 463). Replace the `return` statement:

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

Also change the function signature from `def upload_requirements` to `async def upload_requirements` if not already async (check — it currently uses `await file.read()` so it is already `async def`).

### Step 4: Run tests to verify they pass

```bash
cd services/integration-agent && python -m pytest tests/test_upload_creates_catalog.py -v
```

Expected: PASS.

### Step 5: Update existing upload test

Open `services/integration-agent/tests/test_requirements_upload.py` and check if any test asserts `total_parsed` only. Add `integrations_created` if needed. If the response shape changed, update assertions.

```bash
cd services/integration-agent && python -m pytest tests/test_requirements_upload.py -v
```

Fix any failures before proceeding.

### Step 6: Full suite check

```bash
cd services/integration-agent && python -m pytest tests/ -v
```

### Step 7: Commit

```bash
git add services/integration-agent/main.py services/integration-agent/tests/test_upload_creates_catalog.py
git commit -m "feat(upload): create CatalogEntries with PENDING_TAG_REVIEW at upload time"
```

---

## Task 5: GET /suggest-tags endpoint

**Files:**
- Modify: `services/integration-agent/main.py` — add endpoint after `get_tech_spec`

### Step 1: Write the failing test

Create `services/integration-agent/tests/test_suggest_tags_endpoint.py`:

```python
"""Tests for GET /api/v1/catalog/integrations/{id}/suggest-tags."""
import asyncio
import io
import pytest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture
def seeded_catalog(client):
    """Upload CSV to populate catalog with PENDING_TAG_REVIEW entries."""
    import main
    main.catalog.clear()
    main.parsed_requirements.clear()
    csv = (
        "ReqID,Source,Target,Category,Description\n"
        "REQ-101,ERP,PLM,Product Collection,Sync articles.\n"
        "REQ-102,ERP,PLM,Enrichment INIT,Init product in PLM.\n"
    )
    client.post(
        "/api/v1/requirements/upload",
        files={"file": ("reqs.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    return list(main.catalog.keys())[0]


def test_suggest_tags_returns_category_tags(client, seeded_catalog, monkeypatch):
    monkeypatch.setattr(
        "main._suggest_tags_via_llm",
        AsyncMock(return_value=[]),
    )
    resp = client.get(f"/api/v1/catalog/integrations/{seeded_catalog}/suggest-tags")
    assert resp.status_code == 200
    data = resp.json()
    assert "Product Collection" in data["suggested_tags"]
    assert "Enrichment INIT" in data["suggested_tags"]


def test_suggest_tags_merges_llm_tags(client, seeded_catalog, monkeypatch):
    monkeypatch.setattr(
        "main._suggest_tags_via_llm",
        AsyncMock(return_value=["Data Sync"]),
    )
    resp = client.get(f"/api/v1/catalog/integrations/{seeded_catalog}/suggest-tags")
    assert resp.status_code == 200
    data = resp.json()
    assert "Data Sync" in data["suggested_tags"]


def test_suggest_tags_no_duplicates(client, seeded_catalog, monkeypatch):
    monkeypatch.setattr(
        "main._suggest_tags_via_llm",
        AsyncMock(return_value=["Product Collection"]),  # duplicate
    )
    resp = client.get(f"/api/v1/catalog/integrations/{seeded_catalog}/suggest-tags")
    tags = resp.json()["suggested_tags"]
    assert len(tags) == len(set(tags))


def test_suggest_tags_not_found(client):
    resp = client.get("/api/v1/catalog/integrations/NONEXISTENT/suggest-tags")
    assert resp.status_code == 404
```

### Step 2: Run to verify it fails

```bash
cd services/integration-agent && python -m pytest tests/test_suggest_tags_endpoint.py -v
```

Expected: `404` from FastAPI (route not found) — all tests fail.

### Step 3: Implement the endpoint

Add after `get_tech_spec` in `main.py` (~line 564):

```python
@app.get("/api/v1/catalog/integrations/{id}/suggest-tags", tags=["catalog"])
async def suggest_tags(id: str) -> dict:
    """Propose tags for an integration from requirement categories + LLM."""
    if id not in catalog:
        raise HTTPException(status_code=404, detail="Integration not found.")

    entry = catalog[id]
    reqs = [r for r in parsed_requirements if r.req_id in entry.requirements]

    # Source 1: category extraction (deterministic)
    category_tags = _extract_category_tags(reqs)

    # Source 2: LLM suggestion (may return empty list on failure)
    req_text = " ".join(r.description for r in reqs)
    llm_tags = await _suggest_tags_via_llm(
        entry.source.get("system", ""), entry.target.get("system", ""), req_text
    )

    # Merge, deduplicate, cap at 5
    merged: list[str] = list(category_tags)
    for t in llm_tags:
        if t not in merged:
            merged.append(t)
    suggested = merged[:5]

    return SuggestTagsResponse(
        integration_id=id,
        suggested_tags=suggested,
        source={
            "from_categories": category_tags,
            "from_llm": [t for t in llm_tags if t not in category_tags],
        },
    ).model_dump()
```

Also add `SuggestTagsResponse` to the imports from `schemas` at the top of `main.py`.

### Step 4: Run tests to verify they pass

```bash
cd services/integration-agent && python -m pytest tests/test_suggest_tags_endpoint.py -v
```

Expected: 4 tests PASS.

### Step 5: Full suite check

```bash
cd services/integration-agent && python -m pytest tests/ -v
```

### Step 6: Commit

```bash
git add services/integration-agent/main.py services/integration-agent/tests/test_suggest_tags_endpoint.py
git commit -m "feat(tags): add GET /suggest-tags endpoint"
```

---

## Task 6: POST /confirm-tags endpoint

**Files:**
- Modify: `services/integration-agent/main.py`

### Step 1: Write the failing test

Create `services/integration-agent/tests/test_confirm_tags.py`:

```python
"""Tests for POST /api/v1/catalog/integrations/{id}/confirm-tags."""
import io
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture
def pending_entry(client):
    import main
    main.catalog.clear()
    main.parsed_requirements.clear()
    csv = (
        "ReqID,Source,Target,Category,Description\n"
        "REQ-101,ERP,PLM,Sync,Sync articles.\n"
    )
    client.post(
        "/api/v1/requirements/upload",
        files={"file": ("reqs.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    return list(main.catalog.keys())[0]


def test_confirm_tags_ok(client, pending_entry):
    import main
    resp = client.post(
        f"/api/v1/catalog/integrations/{pending_entry}/confirm-tags",
        json={"tags": ["Sync", "PLM"]},
    )
    assert resp.status_code == 200
    assert main.catalog[pending_entry].status == "TAG_CONFIRMED"
    assert main.catalog[pending_entry].tags == ["Sync", "PLM"]


def test_confirm_tags_wrong_status(client, pending_entry):
    import main
    # Force wrong status
    main.catalog[pending_entry].status = "TAG_CONFIRMED"
    resp = client.post(
        f"/api/v1/catalog/integrations/{pending_entry}/confirm-tags",
        json={"tags": ["Sync"]},
    )
    assert resp.status_code == 409


def test_confirm_tags_too_many(client, pending_entry):
    resp = client.post(
        f"/api/v1/catalog/integrations/{pending_entry}/confirm-tags",
        json={"tags": ["A", "B", "C", "D", "E", "F"]},
    )
    assert resp.status_code == 422


def test_confirm_tags_empty_list(client, pending_entry):
    resp = client.post(
        f"/api/v1/catalog/integrations/{pending_entry}/confirm-tags",
        json={"tags": []},
    )
    assert resp.status_code == 422


def test_confirm_tags_whitespace_stripped(client, pending_entry):
    import main
    resp = client.post(
        f"/api/v1/catalog/integrations/{pending_entry}/confirm-tags",
        json={"tags": ["  Sync  ", "  ", "PLM"]},
    )
    assert resp.status_code == 200
    # "  " is blank — should be discarded; "  Sync  " should be stripped
    assert "Sync" in main.catalog[pending_entry].tags
    assert "" not in main.catalog[pending_entry].tags
    assert "  " not in main.catalog[pending_entry].tags


def test_confirm_tags_not_found(client):
    resp = client.post(
        "/api/v1/catalog/integrations/NONEXISTENT/confirm-tags",
        json={"tags": ["Sync"]},
    )
    assert resp.status_code == 404
```

### Step 2: Run to verify it fails

```bash
cd services/integration-agent && python -m pytest tests/test_confirm_tags.py -v
```

Expected: `404` from FastAPI — route not found.

### Step 3: Implement the endpoint

Add after `suggest_tags` in `main.py`:

```python
@app.post("/api/v1/catalog/integrations/{id}/confirm-tags", tags=["catalog"])
async def confirm_tags(
    id: str,
    body: ConfirmTagsRequest,
    _token: str = Depends(_require_token),
) -> dict:
    """Confirm integration tags and transition status to TAG_CONFIRMED."""
    if id not in catalog:
        raise HTTPException(status_code=404, detail="Integration not found.")

    entry = catalog[id]
    if entry.status != "PENDING_TAG_REVIEW":
        raise HTTPException(
            status_code=409,
            detail=f"Tags already confirmed or entry is in status '{entry.status}'.",
        )

    # Strip whitespace, discard blank tags, enforce max 50 chars each
    clean_tags = [t.strip()[:50] for t in body.tags if t.strip()]
    if not clean_tags:
        raise HTTPException(status_code=422, detail="No valid tags after stripping whitespace.")

    entry.tags = clean_tags
    entry.status = "TAG_CONFIRMED"
    if db.catalog_col is not None:
        await db.catalog_col.replace_one(
            {"id": id}, entry.model_dump(), upsert=True
        )

    return {
        "status": "success",
        "integration_id": id,
        "confirmed_tags": clean_tags,
    }
```

Add `ConfirmTagsRequest` to the imports from `schemas`.

### Step 4: Run tests to verify they pass

```bash
cd services/integration-agent && python -m pytest tests/test_confirm_tags.py -v
```

Expected: 6 tests PASS.

### Step 5: Full suite check

```bash
cd services/integration-agent && python -m pytest tests/ -v
```

### Step 6: Commit

```bash
git add services/integration-agent/main.py services/integration-agent/tests/test_confirm_tags.py
git commit -m "feat(tags): add POST /confirm-tags endpoint with status gate"
```

---

## Task 7: Trigger gate — block generation if any entry is PENDING_TAG_REVIEW

**Files:**
- Modify: `services/integration-agent/main.py` — `trigger_agent` endpoint (~line 507)

### Step 1: Write the failing test

Create `services/integration-agent/tests/test_trigger_gate.py`:

```python
"""Tests that trigger is blocked when entries are in PENDING_TAG_REVIEW."""
import io
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _upload_csv(client):
    csv = (
        "ReqID,Source,Target,Category,Description\n"
        "REQ-101,ERP,PLM,Sync,Sync articles.\n"
    )
    client.post(
        "/api/v1/requirements/upload",
        files={"file": ("reqs.csv", io.BytesIO(csv.encode()), "text/csv")},
    )


def test_trigger_blocked_when_pending_tag_review(client):
    import main
    main.catalog.clear()
    main.parsed_requirements.clear()
    _upload_csv(client)
    # All entries are PENDING_TAG_REVIEW — trigger must be blocked
    resp = client.post("/api/v1/agent/trigger")
    assert resp.status_code == 409
    assert "tag" in resp.json()["detail"].lower()


def test_trigger_allowed_when_all_tag_confirmed(client):
    import main
    main.catalog.clear()
    main.parsed_requirements.clear()
    _upload_csv(client)
    # Force all entries to TAG_CONFIRMED
    for entry in main.catalog.values():
        entry.status = "TAG_CONFIRMED"
        entry.tags = ["Sync"]
    # Trigger should start (may fail later due to Ollama, but not 409 from gate)
    resp = client.post("/api/v1/agent/trigger")
    assert resp.status_code in (200, 400, 500)  # not 409 from tag gate
```

### Step 2: Run to verify it fails

```bash
cd services/integration-agent && python -m pytest tests/test_trigger_gate.py::test_trigger_blocked_when_pending_tag_review -v
```

Expected: FAIL — trigger returns 200 (gate not yet implemented).

### Step 3: Implement the gate

In `trigger_agent` in `main.py`, add this check after the `_agent_lock.locked()` check (~line 526):

```python
    # Gate: all catalog entries must have confirmed tags before generation
    pending_tag_review = [
        e.id for e in catalog.values() if e.status == "PENDING_TAG_REVIEW"
    ]
    if pending_tag_review:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(pending_tag_review)} integration(s) are awaiting tag confirmation. "
                f"Confirm tags before triggering generation."
            ),
        )
```

### Step 4: Run tests to verify they pass

```bash
cd services/integration-agent && python -m pytest tests/test_trigger_gate.py -v
```

Expected: 2 tests PASS.

### Step 5: Full suite check

```bash
cd services/integration-agent && python -m pytest tests/ -v
```

### Step 6: Commit

```bash
git add services/integration-agent/main.py services/integration-agent/tests/test_trigger_gate.py
git commit -m "feat(trigger): block generation if any CatalogEntry is PENDING_TAG_REVIEW"
```

---

## Task 8: RAG helper functions — extract + tag-filtered query

**Files:**
- Modify: `services/integration-agent/main.py`
- Test: `services/integration-agent/tests/test_rag_filtering.py`

### Step 1: Write the failing tests

Create `services/integration-agent/tests/test_rag_filtering.py`:

```python
"""Tests for RAG filtering helper functions."""
import pytest
from unittest.mock import MagicMock, patch
import asyncio


def test_build_rag_context_no_truncation():
    from main import _build_rag_context
    docs = ["short doc A", "short doc B"]
    result = _build_rag_context(docs)
    assert "short doc A" in result
    assert "short doc B" in result


def test_build_rag_context_truncation():
    from main import _build_rag_context
    import main
    original = main.settings.ollama_rag_max_chars
    main.settings.ollama_rag_max_chars = 10
    try:
        result = _build_rag_context(["a" * 20, "b" * 20])
        assert len(result) == 10
    finally:
        main.settings.ollama_rag_max_chars = original


def test_query_rag_tag_filtered_hit():
    from main import _query_rag_with_tags
    import main

    mock_collection = MagicMock()
    mock_collection.query.return_value = {"documents": [["example doc"]]}
    main.collection = mock_collection

    result, source = asyncio.get_event_loop().run_until_complete(
        _query_rag_with_tags("sync products", ["Sync"])
    )
    assert source == "tag_filtered"
    assert "example doc" in result


def test_query_rag_tag_miss_fallback():
    from main import _query_rag_with_tags
    import main

    call_count = 0
    def mock_query(**kwargs):
        nonlocal call_count
        call_count += 1
        # First call (tag-filtered) returns empty, second (fallback) returns doc
        if "where" in kwargs:
            return {"documents": [[]]}
        return {"documents": [["fallback doc"]]}

    mock_collection = MagicMock()
    mock_collection.query.side_effect = lambda **kwargs: mock_query(**kwargs)
    main.collection = mock_collection

    result, source = asyncio.get_event_loop().run_until_complete(
        _query_rag_with_tags("sync products", ["Sync"])
    )
    assert source == "similarity_fallback"
    assert "fallback doc" in result


def test_query_rag_no_collection():
    from main import _query_rag_with_tags
    import main

    original = main.collection
    main.collection = None
    try:
        result, source = asyncio.get_event_loop().run_until_complete(
            _query_rag_with_tags("sync products", ["Sync"])
        )
        assert result == ""
        assert source == "none"
    finally:
        main.collection = original


def test_query_rag_no_tags_uses_similarity():
    from main import _query_rag_with_tags
    import main

    mock_collection = MagicMock()
    mock_collection.query.return_value = {"documents": [["similarity doc"]]}
    main.collection = mock_collection

    result, source = asyncio.get_event_loop().run_until_complete(
        _query_rag_with_tags("sync products", [])
    )
    # No tags → skip tag-filtered step → go straight to similarity
    assert source == "similarity_fallback"
```

### Step 2: Run to verify it fails

```bash
cd services/integration-agent && python -m pytest tests/test_rag_filtering.py -v
```

Expected: `ImportError` — `_build_rag_context` and `_query_rag_with_tags` not defined.

### Step 3: Implement RAG helpers

Add after `_suggest_tags_via_llm` in `main.py`:

```python
def _build_rag_context(docs: list[str]) -> str:
    """Join docs and truncate to prevent prompt overflow on CPU instances."""
    raw = "\n---\n".join(docs)
    max_chars = settings.ollama_rag_max_chars
    if len(raw) > max_chars:
        log_agent(f"[RAG] Context truncated to {max_chars} chars (was {len(raw)}).")
        return raw[:max_chars]
    return raw


async def _query_rag_with_tags(
    query_text: str, tags: list[str]
) -> tuple[str, str]:
    """Query ChromaDB with tag filter, falling back to similarity search.

    Returns:
        (rag_context, source_label)
        source_label: "tag_filtered" | "similarity_fallback" | "none"
    """
    if not collection:
        return "", "none"

    # Step 1: tag-filtered query using primary tag
    if tags:
        try:
            results = collection.query(
                query_texts=[query_text],
                n_results=2,
                where={"tags_csv": {"$contains": tags[0]}},
            )
            docs = (results or {}).get("documents", [[]])[0]
            if docs:
                return _build_rag_context(docs), "tag_filtered"
        except Exception as exc:
            log_agent(f"[RAG] Tag-filtered query failed: {exc}")

        log_agent(f"[RAG] No tagged examples for {tags} — fallback to similarity search.")

    # Step 2: similarity fallback (no metadata filter)
    try:
        results = collection.query(query_texts=[query_text], n_results=2)
        docs = (results or {}).get("documents", [[]])[0]
        if docs:
            return _build_rag_context(docs), "similarity_fallback"
    except Exception as exc:
        log_agent(f"[ERROR] ChromaDB similarity query failed: {exc}")

    return "", "none"
```

### Step 4: Run tests to verify they pass

```bash
cd services/integration-agent && python -m pytest tests/test_rag_filtering.py -v
```

Expected: 6 tests PASS.

### Step 5: Full suite check

```bash
cd services/integration-agent && python -m pytest tests/ -v
```

### Step 6: Commit

```bash
git add services/integration-agent/main.py services/integration-agent/tests/test_rag_filtering.py
git commit -m "feat(rag): add _build_rag_context and _query_rag_with_tags helpers"
```

---

## Task 9: Wire RAG helpers into run_agentic_rag_flow + use confirmed entries

**Files:**
- Modify: `services/integration-agent/main.py` — `run_agentic_rag_flow` function (~line 289–401)

### Step 1: Update existing flow test

Open `services/integration-agent/tests/test_agent_flow.py`. Find where the test pre-populates `parsed_requirements` and check if `catalog` is also seeded. The flow now reads from `catalog` instead of creating entries.

Update or add a fixture that creates a `TAG_CONFIRMED` catalog entry before calling the flow. The exact changes depend on the current test setup — check the file:

```bash
cd services/integration-agent && cat tests/test_agent_flow.py
```

Any test that calls `run_agentic_rag_flow()` will need a pre-seeded `catalog` entry with status `TAG_CONFIRMED`.

### Step 2: Modify run_agentic_rag_flow

Replace the entire body of `run_agentic_rag_flow` with:

```python
async def run_agentic_rag_flow() -> None:
    """
    Core agentic loop: read TAG_CONFIRMED catalog entries → RAG → LLM → guard → HITL queue.

    CatalogEntries are now created at upload time (PENDING_TAG_REVIEW).
    This function only processes entries that have confirmed tags (TAG_CONFIRMED).
    """
    confirmed = [e for e in catalog.values() if e.status == "TAG_CONFIRMED"]
    log_agent(f"Processing {len(confirmed)} TAG_CONFIRMED integration(s)...")

    for entry in confirmed:
        source = entry.source.get("system", "Unknown")
        target = entry.target.get("system", "Unknown")
        reqs = [r for r in parsed_requirements if r.req_id in entry.requirements]

        # Update status to PROCESSING
        entry.status = "PROCESSING"
        if db.catalog_col is not None:
            await db.catalog_col.replace_one(
                {"id": entry.id}, entry.model_dump(), upsert=True
            )
        log_agent(f"Processing entry: {entry.id} ({entry.name}) — {len(reqs)} reqs.")

        # 1. Agentic RAG: query ChromaDB filtered by confirmed tags
        query_text = " ".join(r.description for r in reqs)
        log_agent(f"[RAG] Querying for {entry.id} with tags={entry.tags}...")
        rag_context, rag_source = await _query_rag_with_tags(query_text, entry.tags)
        log_agent(f"[RAG] Source: {rag_source} | chars: {len(rag_context)}")

        # 2. Build prompt
        log_agent(f"[LLM] Prompting for Functional Spec for {entry.id}...")
        prompt = build_prompt(
            source_system=source,
            target_system=target,
            formatted_requirements=query_text,
            rag_context=rag_context,
        )

        # 3. Call LLM + guard
        try:
            raw = await generate_with_ollama(prompt)
            func_content = sanitize_llm_output(raw)
            log_agent(f"[LLM] Spec generated and sanitized for {entry.id}.")
        except LLMOutputValidationError as exc:
            preview = (raw or "")[:120].replace("\n", " ")
            log_agent(f"[GUARD] Output rejected for {entry.id}: {exc}")
            log_agent(f"[GUARD] Raw preview: {preview!r}")
            func_content = "[LLM_OUTPUT_REJECTED: structural guard failed — see agent logs]"
        except Exception as exc:
            log_agent(f"[ERROR] LLM generation failed for {entry.id}: {exc}")
            func_content = "[LLM_UNAVAILABLE: generation failed — retry after Ollama is ready]"

        # 4. Create HITL Approval entry
        app_id = f"APP-{uuid.uuid4().hex[:6].upper()}"
        approval = Approval(
            id=app_id,
            integration_id=entry.id,
            doc_type="functional",
            content=func_content,
            status="PENDING",
            generated_at=_now_iso(),
        )
        approvals[app_id] = approval
        if db.approvals_col is not None:
            await db.approvals_col.replace_one(
                {"id": app_id}, approval.model_dump(), upsert=True
            )
        log_agent(f"Approval {app_id} queued for HITL review.")

        # Update CatalogEntry status to DONE
        entry.status = "DONE"
        if db.catalog_col is not None:
            await db.catalog_col.replace_one(
                {"id": entry.id}, entry.model_dump(), upsert=True
            )

    log_agent("Generation completed. Pending documents are waiting for HITL approval.")
```

### Step 3: Run existing flow tests

```bash
cd services/integration-agent && python -m pytest tests/test_agent_flow.py -v
```

Fix any failures by updating test fixtures to pre-seed catalog with TAG_CONFIRMED entries.

### Step 4: Full suite check

```bash
cd services/integration-agent && python -m pytest tests/ -v
```

Expected: all tests pass.

### Step 5: Commit

```bash
git add services/integration-agent/main.py services/integration-agent/tests/test_agent_flow.py
git commit -m "feat(rag): wire tag-filtered RAG into agentic flow, use pre-created catalog entries"
```

---

## Task 10: ChromaDB — store tags_csv at approval time

**Files:**
- Modify: `services/integration-agent/main.py` — `approve_doc` endpoint (~line 575)

### Step 1: Verify existing approve test still passes before change

```bash
cd services/integration-agent && python -m pytest tests/ -k "approve" -v
```

### Step 2: Modify ChromaDB upsert in approve_doc

Find the `collection.upsert(...)` call inside `approve_doc` (~line 625) and update the metadata:

```python
    # Persist to ChromaDB RAG store (learning loop)
    if collection is not None:
        try:
            # Retrieve confirmed tags from catalog entry for metadata
            cat_entry = catalog.get(app_entry.integration_id)
            tags_csv = ",".join(cat_entry.tags) if cat_entry else ""
            collection.upsert(
                documents=[safe_md],
                metadatas=[{
                    "integration_id": app_entry.integration_id,
                    "type": app_entry.doc_type,
                    "tags_csv": tags_csv,                  # ← new
                }],
                ids=[doc_id],
            )
            logger.info("[RAG] Saved %s to ChromaDB (tags: %s).", doc_id, tags_csv)
        except Exception as exc:
            logger.warning("[RAG] ChromaDB save failed for %s: %s", doc_id, exc)
```

### Step 3: Full suite check

```bash
cd services/integration-agent && python -m pytest tests/ -v
```

### Step 4: Commit

```bash
git add services/integration-agent/main.py
git commit -m "feat(rag): store tags_csv in ChromaDB metadata at approval time"
```

---

## Task 11: UI — tag confirmation panel in web dashboard

**Files:**
- Modify: `services/web-dashboard/js/app.js`

This task modifies the frontend only. No backend tests needed — test manually in browser.

### Step 1: Understand current flow in app.js

Search for the upload handler and the generate/trigger button:

```bash
grep -n "upload\|trigger\|generate\|Generate" services/web-dashboard/js/app.js | head -40
```

### Step 2: Add tag confirmation panel after upload

After the upload success handler (where requirements are displayed), add:

```javascript
async function fetchAndShowTagConfirmation() {
    const response = await fetch('/api/v1/catalog/integrations');
    const data = await response.json();
    const pendingEntries = data.data.filter(e => e.status === 'PENDING_TAG_REVIEW');

    if (pendingEntries.length === 0) return;

    const container = document.getElementById('tag-confirmation-container');
    container.innerHTML = '<h3>Confirm Integration Tags</h3>';

    for (const entry of pendingEntries) {
        const suggestResp = await fetch(`/api/v1/catalog/integrations/${escapeHtml(entry.id)}/suggest-tags`);
        const suggestData = await suggestResp.json();

        const panel = buildTagPanel(entry, suggestData.suggested_tags || []);
        container.appendChild(panel);
    }
    document.getElementById('generate-btn').disabled = true;
}

function buildTagPanel(entry, suggestedTags) {
    const div = document.createElement('div');
    div.className = 'tag-panel';
    div.dataset.entryId = entry.id;

    const title = document.createElement('h4');
    title.textContent = escapeHtml(entry.name);
    div.appendChild(title);

    const chipContainer = document.createElement('div');
    chipContainer.className = 'tag-chips';
    suggestedTags.forEach(tag => {
        const chip = document.createElement('span');
        chip.className = 'tag-chip selected';
        chip.textContent = escapeHtml(tag);
        chip.dataset.tag = tag;
        chip.addEventListener('click', () => chip.classList.toggle('selected'));
        chipContainer.appendChild(chip);
    });
    div.appendChild(chipContainer);

    // Custom tag input (max 3)
    const customContainer = document.createElement('div');
    customContainer.className = 'custom-tags';
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Add custom tag (max 3)';
    input.maxLength = 50;
    const addBtn = document.createElement('button');
    addBtn.textContent = '+ Add';
    addBtn.addEventListener('click', () => {
        const customChips = div.querySelectorAll('.tag-chip.custom');
        if (customChips.length >= 3) return;
        const val = input.value.trim();
        if (!val) return;
        const chip = document.createElement('span');
        chip.className = 'tag-chip selected custom';
        chip.textContent = escapeHtml(val);
        chip.dataset.tag = val;
        chip.addEventListener('click', () => chip.classList.toggle('selected'));
        chipContainer.appendChild(chip);
        input.value = '';
        if (div.querySelectorAll('.tag-chip.custom').length >= 3) {
            input.disabled = true;
            addBtn.disabled = true;
        }
    });
    customContainer.appendChild(input);
    customContainer.appendChild(addBtn);
    div.appendChild(customContainer);

    // Confirm button
    const confirmBtn = document.createElement('button');
    confirmBtn.className = 'confirm-tags-btn';
    confirmBtn.textContent = 'Confirm Tags →';
    confirmBtn.addEventListener('click', () => confirmTagsForEntry(div, entry.id));
    div.appendChild(confirmBtn);

    return div;
}

async function confirmTagsForEntry(panel, entryId) {
    const selected = [...panel.querySelectorAll('.tag-chip.selected')].map(c => c.dataset.tag);
    if (selected.length === 0) {
        alert('Select at least one tag.');
        return;
    }
    const resp = await fetch(`/api/v1/catalog/integrations/${encodeURIComponent(entryId)}/confirm-tags`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tags: selected }),
    });
    if (resp.ok) {
        panel.innerHTML = `<p class="tags-confirmed">✓ Tags confirmed: ${selected.map(escapeHtml).join(', ')}</p>`;
        checkAllTagsConfirmed();
    } else {
        const err = await resp.json();
        alert(`Error: ${escapeHtml(err.detail || 'Unknown error')}`);
    }
}

async function checkAllTagsConfirmed() {
    const resp = await fetch('/api/v1/catalog/integrations');
    const data = await resp.json();
    const allConfirmed = data.data.every(e => e.status !== 'PENDING_TAG_REVIEW');
    document.getElementById('generate-btn').disabled = !allConfirmed;
}
```

### Step 3: Add a `<div id="tag-confirmation-container">` to the HTML

Open `services/web-dashboard/index.html` and add the container div between the upload section and the generate button:

```html
<div id="tag-confirmation-container"></div>
```

### Step 4: Add minimal CSS

In the dashboard CSS file, add styles for `.tag-panel`, `.tag-chip`, `.tag-chip.selected`, `.tags-confirmed`. Reuse existing color variables.

### Step 5: Call `fetchAndShowTagConfirmation()` from upload success handler

In the existing upload success handler in `app.js`, add a call to `fetchAndShowTagConfirmation()` after displaying requirements.

### Step 6: Manual test in browser

1. Start the full stack: `docker-compose up -d`
2. Upload `data/sample-requirements.csv`
3. Verify tag panels appear for each integration
4. Confirm tags for each
5. Verify Generate button enables
6. Trigger generation — verify it starts (not 409)

### Step 7: Commit

```bash
git add services/web-dashboard/js/app.js services/web-dashboard/index.html
git commit -m "feat(ui): add tag confirmation panel before generation trigger"
```

---

## Task 12: ADR-019

**Files:**
- Create: `docs/adr/ADR-019-rag-tag-filtering.md`

### Step 1: Create ADR

Use the template at `docs/adr/ADR-000-template.md` as base. Cover:
- Context: RAG quality issues + CPU timeout problem
- Decision: HITL-gated tag confirmation pre-generation
- Alternatives considered: similarity-only (current), post-generation tagging
- ChromaDB metadata schema change (`tags_csv`)
- State machine extension on `CatalogEntry`
- Validation plan: run 50+ existing tests + new 14 tag tests
- Rollback: env var `OLLAMA_RAG_TAG_FILTER_ENABLED=false` skips filtering

### Step 2: Commit

```bash
git add docs/adr/ADR-019-rag-tag-filtering.md
git commit -m "docs(adr): ADR-019 RAG tag-filtering HITL gate"
```

---

## Final verification

```bash
cd services/integration-agent && python -m pytest tests/ -v
```

Expected: all tests pass (50 original + ~20 new = ~70 total).

Check no regressions in test files touched during this plan:
- `test_requirements_upload.py` (Task 4)
- `test_agent_flow.py` (Task 9)
