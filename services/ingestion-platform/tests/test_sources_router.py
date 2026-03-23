"""
TDD — Source Registry Router Unit Tests (RED phase)

Tests Source CRUD endpoints BEFORE config.py / routers/sources.py / main.py exist.
MongoDB is mocked via state module — no real DB required.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client(mock_mongo_collection):
    """
    TestClient with MongoDB collections replaced by AsyncMock.
    Patches state.sources_col and state.runs_col before importing app.
    """
    import state
    state.sources_col = mock_mongo_collection
    state.runs_col = mock_mongo_collection

    from main import app
    return TestClient(app)


VALID_SOURCE_PAYLOAD = {
    "code": "payment_api_v3",
    "source_type": "openapi",
    "entrypoints": ["https://api.example.com/openapi.json"],
    "tags": ["payment", "api"],
    "description": "Payment API v3",
}


class TestCreateSource:
    def test_create_source_returns_201(self, client):
        response = client.post("/api/v1/sources", json=VALID_SOURCE_PAYLOAD)
        assert response.status_code == 201

    def test_create_source_returns_id(self, client):
        response = client.post("/api/v1/sources", json=VALID_SOURCE_PAYLOAD)
        data = response.json()
        assert "id" in data
        assert data["id"].startswith("src_")

    def test_create_source_returns_code(self, client):
        response = client.post("/api/v1/sources", json=VALID_SOURCE_PAYLOAD)
        data = response.json()
        assert data["code"] == "payment_api_v3"

    def test_create_source_invalid_type_returns_422(self, client):
        bad_payload = {**VALID_SOURCE_PAYLOAD, "source_type": "invalid"}
        response = client.post("/api/v1/sources", json=bad_payload)
        assert response.status_code == 422

    def test_create_source_empty_entrypoints_returns_422(self, client):
        bad_payload = {**VALID_SOURCE_PAYLOAD, "entrypoints": []}
        response = client.post("/api/v1/sources", json=bad_payload)
        assert response.status_code == 422

    def test_create_source_empty_tags_returns_422(self, client):
        bad_payload = {**VALID_SOURCE_PAYLOAD, "tags": []}
        response = client.post("/api/v1/sources", json=bad_payload)
        assert response.status_code == 422


class TestListSources:
    def test_list_sources_returns_200(self, client):
        response = client.get("/api/v1/sources")
        assert response.status_code == 200

    def test_list_sources_returns_list(self, client):
        response = client.get("/api/v1/sources")
        assert isinstance(response.json(), list)

    def test_list_sources_empty_initially(self, client, mock_mongo_collection):
        mock_mongo_collection.find.return_value.to_list = AsyncMock(return_value=[])
        response = client.get("/api/v1/sources")
        assert response.json() == []


class TestGetSource:
    def test_get_existing_source_returns_200(self, client, mock_mongo_collection):
        from models.source import SourceType, SourceState
        from datetime import datetime
        mock_mongo_collection.find_one = AsyncMock(return_value={
            "_id": "src_abc123",
            "id": "src_abc123",
            "code": "payment_api_v3",
            "source_type": "openapi",
            "entrypoints": ["https://example.com"],
            "tags": ["payment"],
            "refresh_cron": "0 */6 * * *",
            "description": None,
            "status": {"state": "active", "last_run_at": None, "last_success_at": None, "last_error": None},
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        })
        response = client.get("/api/v1/sources/src_abc123")
        assert response.status_code == 200

    def test_get_nonexistent_source_returns_404(self, client, mock_mongo_collection):
        mock_mongo_collection.find_one = AsyncMock(return_value=None)
        response = client.get("/api/v1/sources/nonexistent_id")
        assert response.status_code == 404


class TestDeleteSource:
    def test_delete_source_returns_204(self, client, mock_mongo_collection):
        from datetime import datetime
        mock_mongo_collection.find_one = AsyncMock(return_value={
            "id": "src_del_001", "code": "to_delete",
            "source_type": "mcp",
            "entrypoints": ["https://mcp.example.com"],
            "tags": ["test"],
            "refresh_cron": "0 */6 * * *",
            "description": None,
            "status": {"state": "active", "last_run_at": None, "last_success_at": None, "last_error": None},
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        })
        mock_mongo_collection.delete_one = AsyncMock()
        response = client.delete("/api/v1/sources/src_del_001")
        assert response.status_code == 204

    def test_delete_nonexistent_source_returns_404(self, client, mock_mongo_collection):
        mock_mongo_collection.find_one = AsyncMock(return_value=None)
        response = client.delete("/api/v1/sources/does_not_exist")
        assert response.status_code == 404


class TestPauseSource:
    def test_pause_source_returns_200(self, client, mock_mongo_collection):
        from datetime import datetime
        doc = {
            "id": "src_pause_001", "code": "pauseable",
            "source_type": "openapi",
            "entrypoints": ["https://example.com"],
            "tags": ["test"],
            "refresh_cron": "0 */6 * * *",
            "description": None,
            "status": {"state": "active", "last_run_at": None, "last_success_at": None, "last_error": None},
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        mock_mongo_collection.find_one = AsyncMock(return_value=doc)
        mock_mongo_collection.replace_one = AsyncMock()
        response = client.put("/api/v1/sources/src_pause_001/pause")
        assert response.status_code == 200
        assert response.json()["status"]["state"] == "paused"
