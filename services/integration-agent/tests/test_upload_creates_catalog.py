"""Tests that the two-step upload + finalize flow creates CatalogEntries (ADR-025).

upload is now parse-only (returns preview).
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

    assert len(main.catalog) == 3
    for entry in main.catalog.values():
        assert entry.status == "PENDING_TAG_REVIEW"
        assert entry.project_id == "TST"
        assert entry.id.startswith("TST-")
