"""
Unit tests — agent trigger project scoping (ADR-050).

Verifies:
  - run_agentic_rag_flow with project_id filters only entries for that project
  - run_agentic_rag_flow without project_id processes all TAG_CONFIRMED entries
  - PENDING_TAG_REVIEW gate scoped to project when project_id provided
  - PENDING_TAG_REVIEW gate global when project_id is None
"""

import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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


def _make_entry(entry_id, project_id, status="TAG_CONFIRMED"):
    from schemas import CatalogEntry
    return CatalogEntry(
        id=entry_id,
        name=f"Integration {entry_id}",
        type="Auto-discovered",
        source={"system": "SRC"},
        target={"system": "TGT"},
        requirements=[],
        status=status,
        tags=["tag1"],
        project_id=project_id,
        created_at="2026-01-01T00:00:00Z",
    )


class TestRunAgenticRagFlowProjectScope:
    @pytest.mark.asyncio
    async def test_with_project_id_processes_only_matching_entries(self):
        from routers.agent import run_agentic_rag_flow
        import state

        state.catalog.clear()
        state.catalog["ACM-001"] = _make_entry("ACM-001", "ACM")
        state.catalog["TST-001"] = _make_entry("TST-001", "TST")

        processed = []

        async def fake_generate(entry, requirements, *args, **kwargs):
            processed.append(entry.id)
            return None

        with (
            patch("routers.agent.generate_integration_doc", fake_generate),
            patch("routers.agent.log_agent"),
        ):
            await run_agentic_rag_flow(project_id="ACM")

        assert processed == ["ACM-001"]

    @pytest.mark.asyncio
    async def test_without_project_id_processes_all_confirmed(self):
        from routers.agent import run_agentic_rag_flow
        import state

        state.catalog.clear()
        state.catalog["ACM-001"] = _make_entry("ACM-001", "ACM")
        state.catalog["TST-001"] = _make_entry("TST-001", "TST")

        processed = []

        async def fake_generate(entry, requirements, *args, **kwargs):
            processed.append(entry.id)
            return None

        with (
            patch("routers.agent.generate_integration_doc", fake_generate),
            patch("routers.agent.log_agent"),
        ):
            await run_agentic_rag_flow(project_id=None)

        assert set(processed) == {"ACM-001", "TST-001"}


class TestTriggerPendingTagGate:
    _CSV = (
        b"ReqID,Source,Target,Category,Description\n"
        b"R-001,PLM,PIM,Sync,Sync product master data\n"
    )

    def _upload(self, client):
        with patch("db.requirements_col", AsyncMock()):
            client.post(
                "/api/v1/requirements/upload",
                files={"file": ("r.csv", io.BytesIO(self._CSV), "text/csv")},
            )

    def test_pending_tag_gate_scoped_to_project(self, client):
        """PENDING_TAG_REVIEW in project ACM should NOT block trigger for project TST."""
        import state
        state.catalog.clear()
        state.catalog["ACM-001"] = _make_entry("ACM-001", "ACM", status="PENDING_TAG_REVIEW")
        state.catalog["TST-001"] = _make_entry("TST-001", "TST", status="TAG_CONFIRMED")
        self._upload(client)

        # Trigger for TST — ACM pending should not block
        with patch("db.requirements_col", AsyncMock()):
            resp = client.post(
                "/api/v1/agent/trigger",
                json={"project_id": "TST", "pinned_doc_ids": [], "llm_profile": "default"},
            )
        # Should NOT return 409 for pending tags in a different project
        assert resp.status_code != 409 or "ACM" not in resp.json().get("detail", "")

    def test_pending_tag_gate_global_when_no_project_id(self, client):
        """PENDING_TAG_REVIEW entry should block trigger when no project_id given."""
        import state
        state.catalog.clear()
        state.catalog["ACM-001"] = _make_entry("ACM-001", "ACM", status="PENDING_TAG_REVIEW")
        self._upload(client)

        resp = client.post("/api/v1/agent/trigger", json={})
        assert resp.status_code == 409
        assert "tag confirmation" in resp.json()["detail"].lower()

    def test_trigger_with_project_id_passes_to_flow(self, client):
        """When project_id provided and no pending tags, trigger starts successfully."""
        import state
        state.catalog.clear()
        state.catalog["ACM-001"] = _make_entry("ACM-001", "ACM", status="TAG_CONFIRMED")
        self._upload(client)

        with patch("routers.agent.run_agentic_rag_flow", new_callable=AsyncMock):
            resp = client.post(
                "/api/v1/agent/trigger",
                json={"project_id": "ACM"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"
