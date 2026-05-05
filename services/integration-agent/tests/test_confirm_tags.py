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
    main.projects.clear()
    csv = (
        "ReqID,Source,Target,Category,Description\n"
        "REQ-101,ERP,PLM,Sync,Sync articles.\n"
    )
    client.post(
        "/api/v1/requirements/upload",
        files={"file": ("reqs.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    client.post("/api/v1/projects", json={"prefix": "TST", "client_name": "Test Corp", "domain": "Testing"})
    client.post("/api/v1/requirements/finalize", json={"project_id": "TST"})
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
        json={"tags": [f"Tag{i}" for i in range(16)]},
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
