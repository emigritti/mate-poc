"""
Unit tests — requirements MongoDB persistence on PATCH (ADR-050).

Verifies that PATCH /requirements/{req_id} syncs the mandatory flag to MongoDB.
"""

import io
import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

_CSV = (
    b"ReqID,Source,Target,Category,Description\n"
    b"R-001,PLM,PIM,Sync,Sync product master data\n"
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


class TestPatchPersistence:
    def _upload(self, client):
        with patch("db.requirements_col", AsyncMock()):
            client.post(
                "/api/v1/requirements/upload",
                files={"file": ("r.csv", io.BytesIO(_CSV), "text/csv")},
            )

    def test_patch_calls_update_one(self, client):
        self._upload(client)
        mock_col = AsyncMock()
        with patch("db.requirements_col", mock_col):
            resp = client.patch("/api/v1/requirements/R-001", json={"mandatory": True})
        assert resp.status_code == 200
        mock_col.update_one.assert_called_once()

    def test_patch_update_one_sets_mandatory(self, client):
        self._upload(client)
        mock_col = AsyncMock()
        with patch("db.requirements_col", mock_col):
            client.patch("/api/v1/requirements/R-001", json={"mandatory": True})
        _, update_doc = mock_col.update_one.call_args.args
        assert update_doc["$set"]["mandatory"] is True

    def test_patch_filter_uses_req_id(self, client):
        self._upload(client)
        mock_col = AsyncMock()
        with patch("db.requirements_col", mock_col):
            client.patch("/api/v1/requirements/R-001", json={"mandatory": False})
        filter_doc, _ = mock_col.update_one.call_args.args
        assert filter_doc["req_id"] == "R-001"

    def test_patch_nonexistent_req_returns_404_no_db_call(self, client):
        mock_col = AsyncMock()
        with patch("db.requirements_col", mock_col):
            resp = client.patch("/api/v1/requirements/NOPE", json={"mandatory": True})
        assert resp.status_code == 404
        mock_col.update_one.assert_not_called()

    def test_patch_degraded_mode_does_not_raise(self, client):
        self._upload(client)
        with patch("db.requirements_col", None):
            resp = client.patch("/api/v1/requirements/R-001", json={"mandatory": True})
        assert resp.status_code == 200
