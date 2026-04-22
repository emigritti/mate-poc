"""
Unit tests — requirements MongoDB persistence on upload (ADR-050).

Verifies that POST /requirements/upload persists each parsed requirement
to requirements_col with the correct upload_id, and stores upload_id in state.
"""

import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from fastapi.testclient import TestClient

_VALID_CSV = (
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


class TestRequirementsPersistenceOnUpload:
    def test_upload_id_returned_in_response(self, client):
        mock_col = AsyncMock()
        with patch("db.requirements_col", mock_col):
            resp = client.post(
                "/api/v1/requirements/upload",
                files={"file": ("reqs.csv", io.BytesIO(_VALID_CSV), "text/csv")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "upload_id" in data
        assert len(data["upload_id"]) == 32  # uuid4().hex length

    def test_replace_one_called_per_requirement(self, client):
        mock_col = AsyncMock()
        with patch("db.requirements_col", mock_col):
            resp = client.post(
                "/api/v1/requirements/upload",
                files={"file": ("reqs.csv", io.BytesIO(_VALID_CSV), "text/csv")},
            )
        assert resp.status_code == 200
        assert mock_col.replace_one.call_count == 2

    def test_replace_one_filter_includes_upload_id(self, client):
        mock_col = AsyncMock()
        with patch("db.requirements_col", mock_col):
            resp = client.post(
                "/api/v1/requirements/upload",
                files={"file": ("reqs.csv", io.BytesIO(_VALID_CSV), "text/csv")},
            )
        upload_id = resp.json()["upload_id"]
        for c in mock_col.replace_one.call_args_list:
            filter_doc = c.args[0]
            assert filter_doc["upload_id"] == upload_id

    def test_replace_one_document_contains_upload_id(self, client):
        mock_col = AsyncMock()
        with patch("db.requirements_col", mock_col):
            resp = client.post(
                "/api/v1/requirements/upload",
                files={"file": ("reqs.csv", io.BytesIO(_VALID_CSV), "text/csv")},
            )
        upload_id = resp.json()["upload_id"]
        for c in mock_col.replace_one.call_args_list:
            persisted_doc = c.args[1]
            assert persisted_doc["upload_id"] == upload_id

    def test_state_current_upload_id_set(self, client):
        import state
        mock_col = AsyncMock()
        with patch("db.requirements_col", mock_col):
            resp = client.post(
                "/api/v1/requirements/upload",
                files={"file": ("reqs.csv", io.BytesIO(_VALID_CSV), "text/csv")},
            )
        assert state.current_upload_id == resp.json()["upload_id"]

    def test_degraded_mode_no_db_does_not_raise(self, client):
        """requirements_col=None (degraded mode) must not crash the endpoint."""
        with patch("db.requirements_col", None):
            resp = client.post(
                "/api/v1/requirements/upload",
                files={"file": ("reqs.csv", io.BytesIO(_VALID_CSV), "text/csv")},
            )
        assert resp.status_code == 200
        assert resp.json()["total_parsed"] == 2
