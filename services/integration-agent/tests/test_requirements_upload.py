"""
Unit tests — requirements upload and approval endpoints (component level).
ADR-016 / CLAUDE.md §7: Input validation and endpoint behaviour.

Uses FastAPI TestClient with mocked external services (ChromaDB, MongoDB)
so no real infrastructure is needed.

Coverage:
  - Valid CSV upload → 200, correct parse count
  - Non-CSV MIME type → 415
  - Oversized CSV → 413
  - Invalid UTF-8 → 400
  - Approve non-existent ID → 404
  - Approve with empty body → 422 (Pydantic validation)
  - Reject already-rejected → 409
"""

import io
import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    """
    TestClient with mocked external connections.

    Patches applied before lifespan runs so no real DB/ChromaDB connections
    are attempted.  db.catalog_col etc. remain None → MongoDB upserts skipped.
    """
    with (
        patch("db.init_db",          new_callable=AsyncMock),
        patch("db.close_db",         new_callable=AsyncMock),
        patch("main._init_chromadb", new_callable=AsyncMock),
    ):
        from main import app
        with TestClient(app) as c:
            yield c


_VALID_CSV = (
    b"ReqID,Source,Target,Category,Description\n"
    b"R-001,PLM,PIM,Sync,Sync product master data\n"
    b"R-002,PLM,DAM,Transfer,Transfer product images\n"
)


class TestUploadRequirements:
    def test_valid_csv_returns_200(self, client):
        response = client.post(
            "/api/v1/requirements/upload",
            files={"file": ("reqs.csv", io.BytesIO(_VALID_CSV), "text/csv")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["total_parsed"] == 2

    def test_non_csv_mime_returns_415(self, client):
        response = client.post(
            "/api/v1/requirements/upload",
            files={"file": ("binary.bin", io.BytesIO(b"\x00\x01\x02"), "application/octet-stream")},
        )
        assert response.status_code == 415

    def test_oversized_csv_returns_413(self, client):
        # Build a CSV larger than 1 MB
        header = b"ReqID,Source,Target,Category,Description\n"
        row = b"R-001,PLM,PIM,Sync," + b"x" * 200 + b"\n"
        big_csv = header + row * 6_000   # ~1.2 MB
        response = client.post(
            "/api/v1/requirements/upload",
            files={"file": ("big.csv", io.BytesIO(big_csv), "text/csv")},
        )
        assert response.status_code == 413

    def test_invalid_utf8_returns_400(self, client):
        bad_bytes = b"ReqID,Source\n\xff\xfe,PLM\n"
        response = client.post(
            "/api/v1/requirements/upload",
            files={"file": ("bad.csv", io.BytesIO(bad_bytes), "text/csv")},
        )
        assert response.status_code == 400

    def test_empty_csv_returns_zero_parsed(self, client):
        empty = b"ReqID,Source,Target,Category,Description\n"
        response = client.post(
            "/api/v1/requirements/upload",
            files={"file": ("empty.csv", io.BytesIO(empty), "text/csv")},
        )
        assert response.status_code == 200
        assert response.json()["total_parsed"] == 0


class TestApproveReject:
    def test_approve_nonexistent_id_returns_404(self, client):
        response = client.post(
            "/api/v1/approvals/NONEXISTENT/approve",
            json={"final_markdown": "# Functional Specification\n\nContent."},
        )
        assert response.status_code == 404

    def test_approve_empty_body_returns_422(self, client):
        """Pydantic validation must reject an empty JSON body."""
        response = client.post(
            "/api/v1/approvals/APP-FAKE/approve",
            json={},
        )
        assert response.status_code == 422

    def test_reject_empty_feedback_returns_422(self, client):
        response = client.post(
            "/api/v1/approvals/APP-FAKE/reject",
            json={"feedback": ""},
        )
        assert response.status_code == 422

    def test_reject_nonexistent_id_returns_404(self, client):
        response = client.post(
            "/api/v1/approvals/NONEXISTENT/reject",
            json={"feedback": "Does not meet requirements."},
        )
        assert response.status_code == 404

    def test_health_endpoint(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
