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
        import main
        main.parsed_requirements.clear()
        _create_project(client)
        resp = client.post("/api/v1/requirements/finalize", json={"project_id": "TST"})
        assert resp.status_code == 400

    def test_404_if_project_not_found(self, client):
        _upload(client)
        resp = client.post("/api/v1/requirements/finalize", json={"project_id": "ZZZ"})
        assert resp.status_code == 404
