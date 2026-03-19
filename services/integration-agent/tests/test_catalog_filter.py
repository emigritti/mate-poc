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

    def test_legacy_entry_has_project_none(self, client):
        """Entries with project_id=LEGACY (no project) must have _project=None."""
        import main
        from datetime import datetime, timezone
        main.catalog["LEGACY-001"] = CatalogEntry(
            id="LEGACY-001", name="Old Entry", type="Auto-discovered",
            source={"system": "A"}, target={"system": "B"},
            requirements=[], status="TAG_CONFIRMED",
            project_id="LEGACY", created_at=datetime.now(timezone.utc).isoformat(),
        )
        resp = client.get("/api/v1/catalog/integrations")
        entries = resp.json()["data"]
        legacy = next(e for e in entries if e["id"] == "LEGACY-001")
        assert legacy["_project"] is None
        main.catalog.pop("LEGACY-001", None)
