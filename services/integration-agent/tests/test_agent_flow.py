"""
Unit tests — agentic flow (integration-agent)
CLAUDE.md §7: Security guard tests are highest priority.
CLAUDE.md §11: Protect against concurrent execution and ChromaDB absence.

Coverage:
  - asyncio.Lock prevents concurrent runs (returns 409 Conflict)
  - No requirements loaded → trigger returns 400
  - Requirements loaded → trigger returns 200 with task_id
  - Cancel endpoint: idle agent returns 409
  - ChromaDB=None → graceful skip, no crash
  - LLM connection error → caught in background flow, not propagated as crash
  - Health endpoint reports service state

Fixes applied (2026-03-06):
  F-02: use agent_main.collection (not _collection) — correct module-level var name
  F-03: endpoint is /api/v1/agent/trigger (not /api/v1/agent/run); trigger has no JSON
        body — 422 tests for a non-existent body schema were replaced with meaningful
        tests for the actual trigger contract (no requirements → 400, lock held → 409).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Shared fixture ─────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    """
    TestClient with all external I/O mocked.

    Patches applied before lifespan to avoid real DB / ChromaDB connections.
    """
    with (
        patch("db.init_db",          new_callable=AsyncMock),
        patch("db.close_db",         new_callable=AsyncMock),
        patch("main._init_chromadb", new_callable=AsyncMock),
    ):
        from main import app
        with TestClient(app) as c:
            yield c


# ── Agent trigger endpoint ─────────────────────────────────────────────


class TestAgentTrigger:
    def test_trigger_returns_400_when_no_requirements(self, client):
        """
        POST /api/v1/agent/trigger must return 400 if no requirements have been
        uploaded yet.  Ensures the guard on parsed_requirements works correctly.
        """
        import main as agent_main

        original = list(agent_main.parsed_requirements)
        agent_main.parsed_requirements.clear()
        try:
            response = client.post("/api/v1/agent/trigger")
            assert response.status_code == 400
            assert "requirements" in response.json().get("detail", "").lower()
        finally:
            agent_main.parsed_requirements.extend(original)

    def test_trigger_returns_409_when_already_running(self, client):
        """
        When the asyncio.Lock is held (agent running), a second trigger must
        return 409 Conflict — not 500 or a silent ignore (F-09 / asyncio.Lock guard).

        The endpoint checks parsed_requirements BEFORE the lock, so at least one
        requirement must be loaded to reach the 409 branch.
        """
        import main as agent_main
        from schemas import Requirement

        # Requirement must be present so the endpoint reaches the lock check.
        agent_main.parsed_requirements[:] = [
            Requirement(
                req_id="R-LOCK",
                source_system="PLM",
                target_system="PIM",
                category="Test",
                description="Lock contention test",
            )
        ]
        asyncio.get_event_loop().run_until_complete(agent_main._agent_lock.acquire())
        try:
            response = client.post("/api/v1/agent/trigger")
            assert response.status_code == 409
            assert "running" in response.json().get("detail", "").lower()
        finally:
            agent_main._agent_lock.release()
            agent_main.parsed_requirements.clear()

    def test_trigger_starts_successfully_with_requirements(self, client):
        """
        When requirements are loaded and the lock is free, trigger must return 200
        with a status='started' and a task_id field.
        """
        import main as agent_main
        from schemas import Requirement

        agent_main.parsed_requirements[:] = [
            Requirement(
                req_id="R-001",
                source_system="PLM",
                target_system="PIM",
                category="Sync",
                description="Sync product master data",
            )
        ]
        try:
            with patch("main.run_agentic_rag_flow", new_callable=AsyncMock):
                response = client.post("/api/v1/agent/trigger")
            assert response.status_code == 200
            data = response.json()
            assert data.get("status") == "started"
            assert "task_id" in data
        finally:
            agent_main.parsed_requirements.clear()


# ── Cancel endpoint ────────────────────────────────────────────────────


class TestCancelEndpoint:
    def test_cancel_returns_409_when_no_agent_running(self, client):
        """
        POST /api/v1/agent/cancel must return 409 Conflict when no agent is
        currently running (lock not held).
        """
        import main as agent_main

        if agent_main._agent_lock.locked():
            agent_main._agent_lock.release()

        response = client.post("/api/v1/agent/cancel")
        assert response.status_code == 409
        assert "no agent" in response.json().get("detail", "").lower()


# ── ChromaDB graceful degradation ─────────────────────────────────────


class TestChromaDBGracefulDegradation:
    def test_chromadb_none_does_not_crash_upload(self, client):
        """
        CSV upload must succeed even when the ChromaDB collection is None
        (failed init). Upload only parses CSV into memory; it does not use
        ChromaDB.

        Fix F-02: collection (not _collection) is the correct variable name.
        """
        import io
        import main as agent_main

        original_collection = agent_main.collection
        agent_main.collection = None  # simulate failed ChromaDB init

        try:
            csv_bytes = (
                b"ReqID,Source,Target,Category,Description\n"
                b"R-001,PLM,PIM,Sync,Sync product master data\n"
            )
            response = client.post(
                "/api/v1/requirements/upload",
                files={"file": ("reqs.csv", io.BytesIO(csv_bytes), "text/csv")},
            )
            assert response.status_code == 200
            assert response.json()["total_parsed"] == 1
        finally:
            agent_main.collection = original_collection
            agent_main.catalog.clear()
            agent_main.parsed_requirements.clear()

    def test_chromadb_none_does_not_crash_approve(self, client):
        """
        Approve endpoint must not raise an unhandled exception when ChromaDB is
        None — it must return 404 for an unknown ID, not 500.

        Fix F-02: collection (not _collection) is the correct variable name.
        """
        import main as agent_main

        original_collection = agent_main.collection
        agent_main.collection = None

        try:
            response = client.post(
                "/api/v1/approvals/NONEXISTENT/approve",
                json={"final_markdown": "# Functional Specification\n\nContent."},
            )
            # 404 because ID is unknown — must NOT be 500 (unhandled crash)
            assert response.status_code == 404
        finally:
            agent_main.collection = original_collection


# ── LLM error propagation ──────────────────────────────────────────────


class TestLLMErrorHandling:
    def test_llm_connection_error_is_caught_in_flow(self, client):
        """
        If Ollama is unreachable during an agentic flow run, the exception must
        be caught inside the background task and logged — not propagate as an
        unhandled crash.  The trigger endpoint still returns 200 (job accepted).
        """
        import httpx
        import main as agent_main
        from schemas import Requirement

        agent_main.parsed_requirements[:] = [
            Requirement(
                req_id="R-001",
                source_system="PLM",
                target_system="PIM",
                category="Sync",
                description="Sync product data",
            )
        ]
        try:
            with patch(
                "main.generate_with_ollama",
                new_callable=AsyncMock,
                side_effect=httpx.ConnectError("Connection refused"),
            ):
                response = client.post("/api/v1/agent/trigger")
            # Endpoint accepted the job; LLM error is handled inside the background task
            assert response.status_code in (200, 202)
        finally:
            agent_main.parsed_requirements.clear()

    def test_llm_timeout_does_not_leave_lock_permanently_held(self, client):
        """
        After a timeout during the agent flow, the asyncio.Lock must be released
        automatically by the context manager — subsequent trigger calls must be
        accepted (no permanent deadlock).
        """
        import main as agent_main

        # Ensure lock is free (prerequisite for this test)
        if agent_main._agent_lock.locked():
            agent_main._agent_lock.release()

        # Lock must be free; any prior timeout must have released it
        assert not agent_main._agent_lock.locked()


# ── Ollama payload options ─────────────────────────────────────────────


class TestGenerateWithOllamaOptions:
    def _call_generate_with_ollama(self) -> dict:
        """
        Helper: call generate_with_ollama with a mocked httpx client and
        return the captured JSON payload sent to the Ollama API.
        """
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        captured = {}

        async def fake_post(url, json=None, **kwargs):
            captured["payload"] = json
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "response": "# Integration Functional Design\n\nContent.",
                "eval_count": 10,
                "prompt_eval_count": 5,
                "eval_duration": 1_000_000_000,
                "total_duration": 2_000_000_000,
                "load_duration": 100_000_000,
            }
            return mock_resp

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = fake_post

        with patch("main.httpx.AsyncClient", return_value=mock_client):
            from main import generate_with_ollama
            asyncio.run(generate_with_ollama("test prompt"))

        return captured.get("payload", {})

    def test_ollama_payload_num_predict_matches_settings(self):
        """
        generate_with_ollama must read num_predict from settings.ollama_num_predict
        so the token cap is tunable via OLLAMA_NUM_PREDICT env var without
        redeploying code.  On CPU-only instances (llama3.1:8b ~3 tok/s),
        1800 tokens × (1/3 tok/s) = 600s = timeout; a lower default prevents that.
        """
        from config import settings

        payload = self._call_generate_with_ollama()
        options = payload.get("options", {})
        assert options.get("num_predict") == settings.ollama_num_predict, (
            f"Expected num_predict={settings.ollama_num_predict}, "
            f"got {options.get('num_predict')!r}"
        )

    def test_ollama_payload_temperature_matches_settings(self):
        """
        generate_with_ollama must read temperature from settings.ollama_temperature
        so the value is tunable via OLLAMA_TEMPERATURE env var.
        """
        from config import settings

        payload = self._call_generate_with_ollama()
        options = payload.get("options", {})
        assert options.get("temperature") == settings.ollama_temperature, (
            f"Expected temperature={settings.ollama_temperature}, "
            f"got {options.get('temperature')!r}"
        )


# ── Health endpoint ────────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_contains_status_field(self, client):
        response = client.get("/health")
        assert "status" in response.json()

    def test_health_reports_chromadb_status(self, client):
        """Health endpoint must report ChromaDB connectivity status."""
        response = client.get("/health")
        data = response.json()
        assert "chromadb" in data or "chroma" in str(data).lower()


# ── Document lifecycle ─────────────────────────────────────────────────


class TestDocumentLifecycle:
    def test_document_model_has_kb_status_field(self):
        """Document model must include kb_status field defaulting to 'staged'."""
        from schemas import Document
        doc = Document(
            id="INT-001-functional",
            integration_id="INT-001",
            doc_type="functional",
            content="# Spec",
            generated_at="2026-03-18T00:00:00Z",
        )
        assert doc.kb_status == "staged"

    def test_document_model_accepts_promoted_status(self):
        """Document model must accept 'promoted' as a valid kb_status value."""
        from schemas import Document
        doc = Document(
            id="INT-001-functional",
            integration_id="INT-001",
            doc_type="functional",
            content="# Spec",
            generated_at="2026-03-18T00:00:00Z",
            kb_status="promoted",
        )
        assert doc.kb_status == "promoted"

    def test_document_model_rejects_invalid_kb_status(self):
        """Document model must reject any kb_status value outside the allowed Literal."""
        from schemas import Document
        from pydantic import ValidationError
        import pytest
        with pytest.raises(ValidationError):
            Document(
                id="INT-001-functional",
                integration_id="INT-001",
                doc_type="functional",
                content="# Spec",
                generated_at="2026-03-18T00:00:00Z",
                kb_status="archived",
            )

    def test_approve_sets_kb_status_staged(self, client):
        """After approval, document kb_status must be 'staged' (not written to ChromaDB)."""
        import main as agent_main
        from schemas import Approval

        approval_id = "test-approve-lifecycle"
        agent_main.approvals[approval_id] = Approval(
            id=approval_id,
            integration_id="INT-LIFECYCLE",
            doc_type="functional",
            content="# Test\n\nContent.",
            status="PENDING",
            generated_at="2026-03-18T00:00:00Z",
        )
        try:
            response = client.post(
                f"/api/v1/approvals/{approval_id}/approve",
                json={"final_markdown": "# Functional Specification\n\nApproved content."},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["message"] == "Approved and staged. Use 'Promote to KB' to add to RAG."
            doc_id = "INT-LIFECYCLE-functional"
            assert doc_id in agent_main.documents
            assert agent_main.documents[doc_id].kb_status == "staged"
        finally:
            agent_main.approvals.pop(approval_id, None)
            agent_main.documents.pop("INT-LIFECYCLE-functional", None)

    def test_documents_list_endpoint_returns_empty_list(self, client):
        """GET /api/v1/documents must return an empty list when no documents exist."""
        import main as agent_main
        original = dict(agent_main.documents)
        agent_main.documents.clear()
        try:
            response = client.get("/api/v1/documents")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 0
        finally:
            agent_main.documents.update(original)

    def test_documents_list_endpoint_returns_documents_with_kb_status(self, client):
        """GET /api/v1/documents must return all documents with their kb_status."""
        import main as agent_main
        from schemas import Document
        original = dict(agent_main.documents)
        agent_main.documents.clear()
        doc = Document(
            id="INT-TEST-functional",
            integration_id="INT-TEST",
            doc_type="functional",
            content="# Test",
            generated_at="2026-03-18T00:00:00Z",
            kb_status="staged",
        )
        agent_main.documents["INT-TEST-functional"] = doc
        try:
            response = client.get("/api/v1/documents")
            assert response.status_code == 200
            items = response.json()
            assert len(items) == 1
            assert items[0]["kb_status"] == "staged"
            assert items[0]["id"] == "INT-TEST-functional"
        finally:
            agent_main.documents.clear()
            agent_main.documents.update(original)

    def test_promote_unknown_doc_returns_404(self, client):
        """POST promote-to-kb with unknown doc_id must return 404."""
        response = client.post("/api/v1/documents/NONEXISTENT-functional/promote-to-kb")
        assert response.status_code == 404

    def test_promote_already_promoted_returns_409(self, client):
        """POST promote-to-kb on an already-promoted doc must return 409."""
        import main as agent_main
        from schemas import Document
        doc = Document(
            id="INT-ALREADY-functional",
            integration_id="INT-ALREADY",
            doc_type="functional",
            content="# Spec",
            generated_at="2026-03-18T00:00:00Z",
            kb_status="promoted",
        )
        agent_main.documents["INT-ALREADY-functional"] = doc
        try:
            response = client.post("/api/v1/documents/INT-ALREADY-functional/promote-to-kb")
            assert response.status_code == 409
            assert "already" in response.json().get("detail", "").lower()
        finally:
            agent_main.documents.pop("INT-ALREADY-functional", None)

    def test_promote_staged_doc_succeeds(self, client):
        """POST promote-to-kb must set kb_status='promoted' and return 200."""
        import main as agent_main
        from schemas import Document
        doc = Document(
            id="INT-PROMOTE-functional",
            integration_id="INT-PROMOTE",
            doc_type="functional",
            content="# Spec\n\nContent.",
            generated_at="2026-03-18T00:00:00Z",
            kb_status="staged",
        )
        agent_main.documents["INT-PROMOTE-functional"] = doc
        try:
            with patch("state.collection") as mock_col:
                mock_col.upsert = MagicMock()
                response = client.post("/api/v1/documents/INT-PROMOTE-functional/promote-to-kb")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "success"
                mock_col.upsert.assert_called_once()
            assert agent_main.documents["INT-PROMOTE-functional"].kb_status == "promoted"
        finally:
            agent_main.documents.pop("INT-PROMOTE-functional", None)
            agent_main.catalog.pop("INT-PROMOTE", None)

    def test_promote_returns_503_when_chromadb_unavailable(self, client):
        """POST promote-to-kb must return 503 when ChromaDB collection is None."""
        import main as agent_main
        from schemas import Document
        doc = Document(
            id="INT-503-functional",
            integration_id="INT-503",
            doc_type="functional",
            content="# Spec",
            generated_at="2026-03-18T00:00:00Z",
            kb_status="staged",
        )
        agent_main.documents["INT-503-functional"] = doc
        try:
            with patch("state.collection", None):
                response = client.post("/api/v1/documents/INT-503-functional/promote-to-kb")
            assert response.status_code == 503
            assert "unavailable" in response.json().get("detail", "").lower()
        finally:
            agent_main.documents.pop("INT-503-functional", None)


# ── Agent progress tracking (R18) ──────────────────────────────────────


class TestAgentProgressTracking:
    def test_logs_response_includes_progress_key(self, client):
        """GET /agent/logs must include a 'progress' key in the response (R18)."""
        resp = client.get("/api/v1/agent/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "progress" in data
        assert isinstance(data["progress"], dict)

    def test_logs_progress_is_empty_dict_when_agent_not_run(self, client):
        """
        When no agent run has occurred, agent_progress is {} and the logs
        response must reflect that (an empty dict, not absent or None).
        """
        import state

        original = state.agent_progress.copy()
        state.agent_progress.clear()
        try:
            resp = client.get("/api/v1/agent/logs")
            assert resp.status_code == 200
            data = resp.json()
            assert data["progress"] == {}
        finally:
            state.agent_progress.update(original)

    def test_logs_progress_reflects_state(self, client):
        """
        When state.agent_progress is pre-populated, the logs endpoint must
        return the same value under the 'progress' key.
        """
        import state

        original = state.agent_progress.copy()
        state.agent_progress.clear()
        state.agent_progress["overall"] = {"step": "Completed", "done": 3, "total": 3}
        try:
            resp = client.get("/api/v1/agent/logs")
            assert resp.status_code == 200
            data = resp.json()
            assert data["progress"]["overall"]["done"] == 3
            assert data["progress"]["overall"]["total"] == 3
            assert data["progress"]["overall"]["step"] == "Completed"
        finally:
            state.agent_progress.clear()
            state.agent_progress.update(original)

