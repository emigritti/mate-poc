"""
Unit tests — GET /requirements with optional project_id filter (ADR-050).

Verifies:
  - Without project_id: returns in-memory session requirements
  - With project_id: queries MongoDB requirements_col by project_id
  - Degraded mode (requirements_col=None) returns empty list for project queries
"""

import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

_CSV = (
    b"ReqID,Source,Target,Category,Description\n"
    b"R-001,PLM,PIM,Sync,Sync product master data\n"
    b"R-002,PLM,DAM,Transfer,Transfer product images\n"
)


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


def _upload(client):
    with patch("db.requirements_col", AsyncMock()):
        client.post(
            "/api/v1/requirements/upload",
            files={"file": ("r.csv", io.BytesIO(_CSV), "text/csv")},
        )


def _make_async_iter(docs):
    """Return an async iterable mock over a list of dicts."""
    async def _iter():
        for d in docs:
            yield d

    m = MagicMock()
    m.__aiter__ = lambda self: _iter()
    return m


class TestGetRequirementsByProject:
    def test_without_project_id_returns_in_memory(self, client):
        _upload(client)
        resp = client.get("/api/v1/requirements")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2

    def test_with_project_id_queries_mongo(self, client):
        stored = [
            {"req_id": "R-001", "source_system": "PLM", "target_system": "PIM",
             "category": "Sync", "description": "desc", "mandatory": False,
             "upload_id": "abc", "project_id": "ACM"},
        ]
        mock_col = MagicMock()
        mock_col.find = MagicMock(return_value=_make_async_iter(stored))

        with patch("db.requirements_col", mock_col):
            resp = client.get("/api/v1/requirements?project_id=ACM")

        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1
        mock_col.find.assert_called_once_with({"project_id": "ACM"}, {"_id": 0})

    def test_project_id_uppercased_in_query(self, client):
        mock_col = MagicMock()
        mock_col.find = MagicMock(return_value=_make_async_iter([]))

        with patch("db.requirements_col", mock_col):
            client.get("/api/v1/requirements?project_id=acm")

        filter_doc = mock_col.find.call_args.args[0]
        assert filter_doc["project_id"] == "ACM"

    def test_degraded_mode_returns_empty_for_project_query(self, client):
        with patch("db.requirements_col", None):
            resp = client.get("/api/v1/requirements?project_id=ACM")
        assert resp.status_code == 200
        assert resp.json()["data"] == []
