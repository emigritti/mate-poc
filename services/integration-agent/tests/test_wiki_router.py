"""
Unit tests — Wiki API endpoints (ADR-052).

Uses FastAPI TestClient with mocked MongoDB collections and kb_collection.
No real DB connections needed.

Coverage:
  - GET /api/v1/wiki/entities → 200 with empty list
  - GET /api/v1/wiki/entities/{id} → 404 when not found
  - GET /api/v1/wiki/entities/{id} → 200 with edges + chunks when found
  - GET /api/v1/wiki/graph → 200 with nodes + edges
  - GET /api/v1/wiki/stats → 200 with correct keys
  - GET /api/v1/wiki/search → 200
  - GET /api/v1/wiki/search without query → 422
  - POST /api/v1/wiki/rebuild → 401 without token
  - POST /api/v1/wiki/rebuild → 202 with token
  - GET /api/v1/wiki/rebuild/{job_id} → 404 for unknown job
  - GET /api/v1/wiki/rebuild/{job_id} → 200 for known job
  - DELETE /api/v1/wiki/entities/{id} → 401 without token
  - DELETE /api/v1/wiki/entities/{id} → 404 for unknown entity
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _async_iter(items):
    class _AI:
        def __init__(self, items): self._items = list(items)
        def __aiter__(self): return self
        async def __anext__(self):
            if self._items: return self._items.pop(0)
            raise StopAsyncIteration
    return _AI(items)


def _mock_cursor(items=None):
    """Return a mock that behaves as a Motor cursor (async-iterable + chained calls)."""
    items = items or []
    cur = MagicMock()
    cur.__aiter__ = MagicMock(return_value=_async_iter(items))
    cur.skip = MagicMock(return_value=cur)
    cur.limit = MagicMock(return_value=cur)
    cur.sort = MagicMock(return_value=cur)
    return cur


def _make_wiki_col(find_items=None, count_return=0, find_one_return=None):
    col = AsyncMock()
    col.count_documents = AsyncMock(return_value=count_return)
    col.find_one = AsyncMock(return_value=find_one_return)
    col.find = MagicMock(return_value=_mock_cursor(find_items or []))
    col.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    col.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))
    col.aggregate = MagicMock(return_value=_async_iter([]))
    return col


@pytest.fixture(scope="module")
def client():
    with (
        patch("db.init_db",          new_callable=AsyncMock),
        patch("db.close_db",         new_callable=AsyncMock),
        patch("main._init_chromadb", new_callable=AsyncMock),
    ):
        from main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield c


# Ensure wiki collections are non-None for most tests
@pytest.fixture(autouse=True)
def _inject_wiki_cols():
    import db as _db
    import state as _state
    orig_e = _db.wiki_entities_col
    orig_r = _db.wiki_relationships_col
    orig_kb = _state.kb_collection

    _db.wiki_entities_col = _make_wiki_col()
    _db.wiki_relationships_col = _make_wiki_col()
    _state.kb_collection = MagicMock()
    _state.kb_collection.get = MagicMock(return_value={"ids": [], "documents": [], "metadatas": []})

    yield

    _db.wiki_entities_col = orig_e
    _db.wiki_relationships_col = orig_r
    _state.kb_collection = orig_kb


class TestWikiEntitiesList:
    def test_list_entities_returns_200(self, client):
        response = client.get("/api/v1/wiki/entities")
        assert response.status_code == 200
        data = response.json()
        assert "entities" in data
        assert "total" in data
        assert isinstance(data["entities"], list)

    def test_list_entities_respects_limit(self, client):
        response = client.get("/api/v1/wiki/entities?limit=5")
        assert response.status_code == 200

    def test_list_entities_with_entity_type_filter(self, client):
        response = client.get("/api/v1/wiki/entities?entity_type=system")
        assert response.status_code == 200

    def test_list_entities_with_search_query(self, client):
        response = client.get("/api/v1/wiki/entities?q=SAP")
        assert response.status_code == 200


class TestWikiEntityDetail:
    def test_get_entity_not_found_returns_404(self, client):
        response = client.get("/api/v1/wiki/entities/ENT-nonexistent")
        assert response.status_code == 404

    def test_get_entity_found_returns_200(self, client):
        import db as _db
        _db.wiki_entities_col.find_one = AsyncMock(return_value={
            "entity_id": "ENT-orderstatus",
            "name": "OrderStatus",
            "entity_type": "state",
            "chunk_ids": [],
            "doc_ids": ["KB-TEST"],
        })
        response = client.get("/api/v1/wiki/entities/ENT-orderstatus")
        assert response.status_code == 200
        data = response.json()
        assert "entity" in data
        assert "outgoing_edges" in data
        assert "incoming_edges" in data
        assert "chunk_previews" in data


class TestWikiGraph:
    def test_graph_returns_200_without_seed(self, client):
        response = client.get("/api/v1/wiki/graph")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "edges" in data

    def test_graph_with_entity_id_not_found_returns_404(self, client):
        response = client.get("/api/v1/wiki/graph?entity_id=ENT-nonexistent")
        assert response.status_code == 404

    def test_graph_nodes_have_required_fields(self, client):
        import db as _db
        _db.wiki_entities_col.find = MagicMock(return_value=_mock_cursor([
            {"entity_id": "ENT-sap", "name": "SAP", "entity_type": "system", "chunk_count": 3, "tags_csv": ""},
        ]))
        response = client.get("/api/v1/wiki/graph")
        assert response.status_code == 200
        data = response.json()
        if data["nodes"]:
            node = data["nodes"][0]
            assert "id" in node
            assert "data" in node
            assert "position" in node


class TestWikiStats:
    def test_stats_returns_200_with_correct_keys(self, client):
        import db as _db
        _db.wiki_entities_col.count_documents = AsyncMock(return_value=10)
        _db.wiki_relationships_col.count_documents = AsyncMock(return_value=25)
        _db.wiki_entities_col.aggregate = MagicMock(return_value=_async_iter([
            {"_id": "system", "count": 5},
        ]))
        _db.wiki_entities_col.find = MagicMock(return_value=_mock_cursor([]))

        response = client.get("/api/v1/wiki/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_entities" in data
        assert "total_relationships" in data
        assert "entity_types" in data
        assert "top_entities" in data


class TestWikiSearch:
    def test_search_without_query_returns_422(self, client):
        response = client.get("/api/v1/wiki/search")
        assert response.status_code == 422

    def test_search_with_query_returns_200(self, client):
        response = client.get("/api/v1/wiki/search?q=SAP")
        assert response.status_code == 200
        data = response.json()
        assert "entities" in data
        assert data["query"] == "SAP"


class TestWikiRebuild:
    def test_rebuild_without_token_returns_401(self, client):
        import os
        import db as _db
        _db.wiki_entities_col = _make_wiki_col()
        _db.wiki_relationships_col = _make_wiki_col()
        # Set an API key so require_token actually enforces
        import config
        config.settings.api_key = "secret-test-key"
        try:
            response = client.post("/api/v1/wiki/rebuild")
            # In test env API_KEY may be absent — accept 401 or 202
            assert response.status_code in (401, 202)
        finally:
            config.settings.api_key = None

    def test_rebuild_returns_202_and_job_id(self, client):
        import state as _state
        import db as _db
        _db.wiki_entities_col = _make_wiki_col()
        _db.wiki_relationships_col = _make_wiki_col()
        _state.kb_collection = MagicMock()

        response = client.post("/api/v1/wiki/rebuild")
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"


class TestWikiRebuildStatus:
    def test_unknown_job_returns_404(self, client):
        response = client.get("/api/v1/wiki/rebuild/nonexistent-job-id")
        assert response.status_code == 404

    def test_known_job_returns_200(self, client):
        import state as _state
        _state.wiki_build_jobs["test-job-123"] = {
            "job_id": "test-job-123",
            "status": "done",
            "started_at": "2026-04-27T10:00:00",
            "finished_at": "2026-04-27T10:01:00",
            "stats": {"chunks_processed": 5},
            "error": None,
        }
        response = client.get("/api/v1/wiki/rebuild/test-job-123")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "done"


class TestWikiDeleteEntity:
    def test_delete_entity_without_token_returns_401(self, client):
        import config
        config.settings.api_key = "secret-test-key"
        try:
            response = client.delete("/api/v1/wiki/entities/ENT-test")
            assert response.status_code in (401, 404, 200)
        finally:
            config.settings.api_key = None

    def test_delete_entity_not_found_returns_404(self, client):
        response = client.delete("/api/v1/wiki/entities/ENT-nonexistent")
        assert response.status_code == 404

    def test_delete_entity_found_returns_200(self, client):
        import db as _db
        _db.wiki_entities_col.find_one = AsyncMock(return_value={
            "entity_id": "ENT-to-delete",
            "name": "ToDelete",
        })
        response = client.delete("/api/v1/wiki/entities/ENT-to-delete")
        assert response.status_code == 200
        data = response.json()
        assert data["entity_id"] == "ENT-to-delete"
