"""
Unit tests — requirements MongoDB persistence on finalize (ADR-050).

Verifies that POST /requirements/finalize:
  - calls requirements_col.update_one for each resolved requirement with project_id
  - clears state.current_upload_id after finalize
"""

import io
import pytest
from unittest.mock import AsyncMock, patch

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


def _upload_csv(client, mock_req_col):
    with patch("db.requirements_col", mock_req_col):
        return client.post(
            "/api/v1/requirements/upload",
            files={"file": ("reqs.csv", io.BytesIO(_VALID_CSV), "text/csv")},
        )


def _create_project(client, prefix="TST"):
    with patch("db.projects_col", AsyncMock()):
        return client.post(
            "/api/v1/projects",
            json={"prefix": prefix, "client_name": "Test Client", "domain": "Testing"},
        )


class TestFinalizePersistence:
    def test_update_one_called_per_requirement(self, client):
        _upload_csv(client, AsyncMock())
        _create_project(client, "FP1")

        mock_req_col = AsyncMock()
        with (
            patch("db.requirements_col", mock_req_col),
            patch("db.catalog_col", AsyncMock()),
        ):
            resp = client.post(
                "/api/v1/requirements/finalize",
                json={"project_id": "FP1"},
            )
        assert resp.status_code == 200
        assert mock_req_col.update_one.call_count == 2

    def test_update_one_sets_project_id(self, client):
        _upload_csv(client, AsyncMock())
        _create_project(client, "FP2")

        mock_req_col = AsyncMock()
        with (
            patch("db.requirements_col", mock_req_col),
            patch("db.catalog_col", AsyncMock()),
        ):
            client.post("/api/v1/requirements/finalize", json={"project_id": "FP2"})

        for c in mock_req_col.update_one.call_args_list:
            update_doc = c.args[1]
            assert update_doc["$set"]["project_id"] == "FP2"

    def test_current_upload_id_cleared_after_finalize(self, client):
        import state
        _upload_csv(client, AsyncMock())
        assert state.current_upload_id is not None

        _create_project(client, "FP3")
        with (
            patch("db.requirements_col", AsyncMock()),
            patch("db.catalog_col", AsyncMock()),
        ):
            client.post("/api/v1/requirements/finalize", json={"project_id": "FP3"})

        assert state.current_upload_id is None

    def test_degraded_mode_finalize_does_not_raise(self, client):
        """requirements_col=None during finalize must not crash."""
        _upload_csv(client, AsyncMock())
        _create_project(client, "FP4")

        with (
            patch("db.requirements_col", None),
            patch("db.catalog_col", AsyncMock()),
        ):
            resp = client.post("/api/v1/requirements/finalize", json={"project_id": "FP4"})
        assert resp.status_code == 200
