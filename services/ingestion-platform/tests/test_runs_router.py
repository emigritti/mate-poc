"""
Tests for the runs/snapshots read-only router (routers/runs.py).

Endpoints:
  GET /api/v1/runs/{run_id}
  GET /api/v1/sources/{source_id}/runs
  GET /api/v1/sources/{source_id}/snapshots
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient


# ── Fixtures ─────────────────────────────────────────────────────────────────

VALID_RUN_DOC = {
    "_id": "run_20260331_src_abc1",
    "id": "run_20260331_src_abc1",
    "source_id": "src_abc123",
    "trigger": "manual",
    "collector_type": "openapi",
    "status": "success",
    "started_at": "2026-03-31T10:00:00",
    "finished_at": "2026-03-31T10:00:05",
    "chunks_created": 12,
    "changed": True,
    "errors": [],
}

VALID_SNAPSHOT_DOC = {
    "_id": "snap_20260331_src_abc1",
    "id": "snap_20260331_src_abc1",
    "source_id": "src_abc123",
    "snapshot_no": 1,
    "captured_at": "2026-03-31T10:00:05",
    "content_hash": "abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
    "is_current": True,
    "capabilities_count": 8,
    "diff_summary": "Added 3 new endpoints",
}


def _make_chain_mock(return_list):
    """Build a MagicMock that supports .find(...).sort(...).limit(...).to_list(...)."""
    chain = MagicMock()
    chain.sort.return_value = chain
    chain.limit.return_value = chain
    chain.to_list = AsyncMock(return_value=return_list)
    return chain


@pytest.fixture
def client(mock_mongo_collection):
    import state
    state.sources_col = mock_mongo_collection
    state.runs_col = mock_mongo_collection
    state.snapshots_col = mock_mongo_collection
    from main import app
    return TestClient(app)


# ── GET /api/v1/runs/{run_id} ─────────────────────────────────────────────────

class TestGetRun:
    def test_get_existing_run_returns_200(self, client, mock_mongo_collection):
        mock_mongo_collection.find_one = AsyncMock(return_value=dict(VALID_RUN_DOC))
        res = client.get("/api/v1/runs/run_20260331_src_abc1")
        assert res.status_code == 200

    def test_get_nonexistent_run_returns_404(self, client, mock_mongo_collection):
        mock_mongo_collection.find_one = AsyncMock(return_value=None)
        res = client.get("/api/v1/runs/nonexistent_run")
        assert res.status_code == 404

    def test_get_run_response_shape(self, client, mock_mongo_collection):
        mock_mongo_collection.find_one = AsyncMock(return_value=dict(VALID_RUN_DOC))
        res = client.get("/api/v1/runs/run_20260331_src_abc1")
        body = res.json()
        assert body["id"] == VALID_RUN_DOC["id"]
        assert body["source_id"] == VALID_RUN_DOC["source_id"]
        assert body["status"] == VALID_RUN_DOC["status"]
        assert body["chunks_created"] == VALID_RUN_DOC["chunks_created"]
        assert "_id" not in body

    def test_get_run_does_not_expose_mongo_id(self, client, mock_mongo_collection):
        mock_mongo_collection.find_one = AsyncMock(return_value=dict(VALID_RUN_DOC))
        res = client.get("/api/v1/runs/run_20260331_src_abc1")
        assert "_id" not in res.json()


# ── GET /api/v1/sources/{source_id}/runs ──────────────────────────────────────

class TestGetSourceRuns:
    def test_list_runs_returns_200(self, client, mock_mongo_collection):
        mock_mongo_collection.find = MagicMock(return_value=_make_chain_mock([dict(VALID_RUN_DOC)]))
        res = client.get("/api/v1/sources/src_abc123/runs")
        assert res.status_code == 200

    def test_list_runs_returns_list(self, client, mock_mongo_collection):
        mock_mongo_collection.find = MagicMock(return_value=_make_chain_mock([dict(VALID_RUN_DOC)]))
        body = client.get("/api/v1/sources/src_abc123/runs").json()
        assert isinstance(body, list)
        assert len(body) == 1

    def test_list_runs_empty_when_no_runs(self, client, mock_mongo_collection):
        mock_mongo_collection.find = MagicMock(return_value=_make_chain_mock([]))
        body = client.get("/api/v1/sources/src_abc123/runs").json()
        assert body == []

    def test_list_runs_calls_sort_descending(self, client, mock_mongo_collection):
        chain = _make_chain_mock([])
        mock_mongo_collection.find = MagicMock(return_value=chain)
        client.get("/api/v1/sources/src_abc123/runs")
        chain.sort.assert_called_once_with("started_at", -1)

    def test_list_runs_calls_limit_20(self, client, mock_mongo_collection):
        chain = _make_chain_mock([])
        mock_mongo_collection.find = MagicMock(return_value=chain)
        client.get("/api/v1/sources/src_abc123/runs")
        chain.limit.assert_called_once_with(20)

    def test_list_runs_item_shape(self, client, mock_mongo_collection):
        mock_mongo_collection.find = MagicMock(return_value=_make_chain_mock([dict(VALID_RUN_DOC)]))
        body = client.get("/api/v1/sources/src_abc123/runs").json()
        item = body[0]
        assert item["id"] == VALID_RUN_DOC["id"]
        assert item["trigger"] == VALID_RUN_DOC["trigger"]
        assert "_id" not in item


# ── GET /api/v1/sources/{source_id}/snapshots ─────────────────────────────────

class TestGetSourceSnapshots:
    def test_list_snapshots_returns_200(self, client, mock_mongo_collection):
        mock_mongo_collection.find = MagicMock(return_value=_make_chain_mock([dict(VALID_SNAPSHOT_DOC)]))
        res = client.get("/api/v1/sources/src_abc123/snapshots")
        assert res.status_code == 200

    def test_list_snapshots_returns_list(self, client, mock_mongo_collection):
        mock_mongo_collection.find = MagicMock(return_value=_make_chain_mock([dict(VALID_SNAPSHOT_DOC)]))
        body = client.get("/api/v1/sources/src_abc123/snapshots").json()
        assert isinstance(body, list)
        assert len(body) == 1

    def test_list_snapshots_empty_when_none(self, client, mock_mongo_collection):
        mock_mongo_collection.find = MagicMock(return_value=_make_chain_mock([]))
        body = client.get("/api/v1/sources/src_abc123/snapshots").json()
        assert body == []

    def test_list_snapshots_calls_limit_10(self, client, mock_mongo_collection):
        chain = _make_chain_mock([])
        mock_mongo_collection.find = MagicMock(return_value=chain)
        client.get("/api/v1/sources/src_abc123/snapshots")
        chain.limit.assert_called_once_with(10)

    def test_snapshot_response_contains_hash(self, client, mock_mongo_collection):
        mock_mongo_collection.find = MagicMock(return_value=_make_chain_mock([dict(VALID_SNAPSHOT_DOC)]))
        body = client.get("/api/v1/sources/src_abc123/snapshots").json()
        assert body[0]["content_hash"] == VALID_SNAPSHOT_DOC["content_hash"]

    def test_snapshot_response_contains_diff_summary(self, client, mock_mongo_collection):
        mock_mongo_collection.find = MagicMock(return_value=_make_chain_mock([dict(VALID_SNAPSHOT_DOC)]))
        body = client.get("/api/v1/sources/src_abc123/snapshots").json()
        assert body[0]["diff_summary"] == VALID_SNAPSHOT_DOC["diff_summary"]

    def test_snapshot_does_not_expose_mongo_id(self, client, mock_mongo_collection):
        mock_mongo_collection.find = MagicMock(return_value=_make_chain_mock([dict(VALID_SNAPSHOT_DOC)]))
        body = client.get("/api/v1/sources/src_abc123/snapshots").json()
        assert "_id" not in body[0]
