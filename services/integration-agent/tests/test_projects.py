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
    def test_create_new_project_returns_200(self, client):
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
        """Same prefix + same client_name → 200 with status ok."""
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

    def test_prefix_lowercase_rejected_by_pydantic(self, client):
        """Prefix must match ^[A-Z0-9]{1,3}$ — lowercase rejected with 422."""
        payload = {**_VALID_PROJECT, "prefix": "acm"}
        resp = client.post("/api/v1/projects", json=payload)
        assert resp.status_code == 422

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
