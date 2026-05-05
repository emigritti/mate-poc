"""
Unit tests — POST /api/v1/approvals/{id}/regenerate
R16: Feedback loop — regenerate document with reviewer feedback injected into prompt.
"""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

import state
from main import app
from schemas import Approval, CatalogEntry

client = TestClient(app)


def _inject_rejected(app_id: str, integration_id: str, feedback: str) -> None:
    """Inject a REJECTED approval and its catalog entry into in-memory state."""
    entry = CatalogEntry(
        id=integration_id,
        name="PLM→PIM",
        type="Data Sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=[],
        tags=["Data Sync"],
        status="DONE",
        created_at="2026-03-20T00:00:00+00:00",
    )
    state.catalog[integration_id] = entry
    state.approvals[app_id] = Approval(
        id=app_id,
        integration_id=integration_id,
        doc_type="functional",
        content="[REJECTED_CONTENT]",
        status="REJECTED",
        generated_at="2026-03-20T00:00:00+00:00",
        feedback=feedback,
    )


def _good_doc() -> str:
    return (
        "# Integration Functional Design\n\n"
        "## 1. Overview\n\nThis section covers the overview.\n\n"
        "## 2. Scope\n\nScope description here.\n\n"
        "## 3. Actors\n\nPLM and PIM systems involved.\n\n"
        "## 4. Process\n\nThe integration process is defined here.\n\n"
        "## 5. Data\n\nData fields and mappings are described here.\n\n"
    )


class TestRegenerateEndpoint:
    def setup_method(self):
        state.approvals.clear()
        state.catalog.clear()
        state.parsed_requirements.clear()

    def test_regenerate_404_for_unknown_approval(self):
        res = client.post("/api/v1/approvals/UNKNOWN/regenerate")
        assert res.status_code == 404

    def test_regenerate_409_if_approval_is_pending(self):
        state.approvals["APP-P"] = Approval(
            id="APP-P", integration_id="X", doc_type="functional",
            content="...", status="PENDING", generated_at="2026-03-20T00:00:00+00:00",
        )
        res = client.post("/api/v1/approvals/APP-P/regenerate")
        assert res.status_code == 409

    def test_regenerate_409_if_approval_is_approved(self):
        state.approvals["APP-A"] = Approval(
            id="APP-A", integration_id="X", doc_type="functional",
            content="...", status="APPROVED", generated_at="2026-03-20T00:00:00+00:00",
        )
        res = client.post("/api/v1/approvals/APP-A/regenerate")
        assert res.status_code == 409

    def test_regenerate_409_if_no_feedback(self):
        _inject_rejected("APP-R0", "INT-000", feedback="")
        state.approvals["APP-R0"].feedback = None
        res = client.post("/api/v1/approvals/APP-R0/regenerate")
        assert res.status_code == 409

    def test_regenerate_creates_new_pending_approval(self):
        _inject_rejected("APP-R1", "INT-001", feedback="Missing error handling section.")
        with patch(
            "routers.approvals.generate_integration_doc",
            new_callable=AsyncMock,
            return_value=(_good_doc(), None),
        ):
            res = client.post("/api/v1/approvals/APP-R1/regenerate")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        new_id = data["data"]["new_approval_id"]
        assert new_id in state.approvals
        assert state.approvals[new_id].status == "PENDING"

    def test_regenerate_response_contains_both_approval_ids(self):
        _inject_rejected("APP-R2", "INT-002", feedback="Add data mapping table.")
        with patch(
            "routers.approvals.generate_integration_doc",
            new_callable=AsyncMock,
            return_value=(_good_doc(), None),
        ):
            res = client.post("/api/v1/approvals/APP-R2/regenerate")
        data = res.json()["data"]
        assert "new_approval_id" in data
        assert data["previous_approval_id"] == "APP-R2"

    def test_regenerate_passes_feedback_to_generator(self):
        _inject_rejected("APP-R3", "INT-003", feedback="Add data mapping table.")
        with patch(
            "routers.approvals.generate_integration_doc",
            new_callable=AsyncMock,
            return_value=(_good_doc(), None),
        ) as mock_gen:
            client.post("/api/v1/approvals/APP-R3/regenerate")
        call_kwargs = mock_gen.call_args.kwargs
        assert "Add data mapping table." in call_kwargs.get("reviewer_feedback", "")
