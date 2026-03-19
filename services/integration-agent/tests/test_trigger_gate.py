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
