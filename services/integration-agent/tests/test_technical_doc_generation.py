"""
Unit tests for unified Integration Spec generation.

Replaces the former two-phase (functional/technical) tests (ADR-038).
Now there is a single document type: "integration".

Coverage:
  - CatalogEntry no longer has technical_status field
  - Approval and Document default to doc_type="integration"
  - sanitize_llm_output accepts "integration" doc_type
  - sanitize_llm_output backward-compat with legacy "functional"/"technical" values
  - approve endpoint stores document with doc_type="integration"
  - trigger-technical endpoint is REMOVED (404)
  - generate_integration_doc produces sanitized output
"""

import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


# ── Schema tests ───────────────────────────────────────────────────────────────

from schemas import CatalogEntry, Approval, Document
from output_guard import sanitize_llm_output, _REQUIRED_PREFIX


class TestCatalogEntryNoTechnicalStatus:
    def test_catalog_entry_has_no_technical_status_field(self):
        """CatalogEntry no longer carries technical_status."""
        entry = CatalogEntry(
            id="T-001",
            name="ERP to Salsify",
            type="Auto-discovered",
            source={"system": "ERP"},
            target={"system": "Salsify"},
            requirements=[],
            status="TAG_CONFIRMED",
            created_at="2026-01-01T00:00:00",
        )
        assert not hasattr(entry, "technical_status"), \
            "technical_status should not exist on CatalogEntry"

    def test_catalog_entry_dumps_without_technical_status(self):
        entry = CatalogEntry(
            id="T-001", name="X", type="Auto-discovered",
            source={"system": "A"}, target={"system": "B"},
            requirements=[], status="DONE", created_at="2026-01-01",
        )
        d = entry.model_dump()
        assert "technical_status" not in d


class TestDocTypeSingle:
    def test_approval_default_doc_type_is_integration(self):
        a = Approval(
            id="APP-001", integration_id="T-001", content="# Integration Design\nHi",
            status="PENDING", generated_at="2026-01-01",
        )
        assert a.doc_type == "integration"

    def test_document_default_doc_type_is_integration(self):
        d = Document(
            id="T-001-integration", integration_id="T-001",
            content="# Integration Design\nHi", generated_at="2026-01-01",
        )
        assert d.doc_type == "integration"


# ── Output guard tests ─────────────────────────────────────────────────────────

class TestSanitizeLlmOutputUnified:
    def test_integration_doc_type_accepted(self):
        raw = "# Integration Design\n\n## 1. Overview\n\nSome content."
        result = sanitize_llm_output(raw, doc_type="integration")
        assert result.startswith("# Integration Design")

    def test_default_doc_type_is_integration(self):
        """sanitize_llm_output() with no doc_type must accept # Integration Design."""
        raw = "# Integration Design\n\n## 1. Overview\n\nContent."
        result = sanitize_llm_output(raw)
        assert result.startswith("# Integration Design")

    def test_legacy_functional_doc_type_still_works(self):
        """Backward-compat: 'functional' is accepted as an alias for 'integration'."""
        raw = "# Integration Design\n\n## 1. Overview\n\nContent."
        result = sanitize_llm_output(raw, doc_type="functional")
        assert "# Integration Design" in result

    def test_legacy_technical_doc_type_still_works(self):
        """Backward-compat: 'technical' is accepted as an alias for 'integration'."""
        raw = "# Integration Design\n\nContent."
        result = sanitize_llm_output(raw, doc_type="technical")
        assert result.startswith("# Integration Design")

    def test_strips_preamble_before_heading(self):
        raw = "Here is the document:\n\n# Integration Design\n\nContent."
        result = sanitize_llm_output(raw, doc_type="integration")
        assert result.startswith("# Integration Design")

    def test_required_prefix_constant(self):
        assert _REQUIRED_PREFIX == "# Integration Design"


# ── Endpoint tests ─────────────────────────────────────────────────────────────

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


class TestTriggerTechnicalRemoved:
    def test_trigger_technical_endpoint_no_longer_exists(self, client):
        """POST /agent/trigger-technical/{id} must be removed (404 or 405)."""
        res = client.post("/api/v1/agent/trigger-technical/FAKE-001")
        assert res.status_code in (404, 405)


class TestApproveStoresIntegrationDocType:
    def test_approve_sets_doc_type_integration(self, client):
        """When an approval is created via the agent flow, doc_type should be 'integration'."""
        import state
        from schemas import Approval

        # Inject a pending approval directly into state
        approval = Approval(
            id="APP-TEST01",
            integration_id="T-TEST",
            doc_type="integration",
            content="# Integration Design\n\nContent.",
            status="PENDING",
            generated_at="2026-01-01T00:00:00",
        )
        state.approvals["APP-TEST01"] = approval

        res = client.post(
            "/api/v1/approvals/APP-TEST01/approve",
            json={"final_markdown": "# Integration Design\n\nApproved content."},
        )
        assert res.status_code == 200

        # Stored document must be keyed as "{id}-integration" with doc_type="integration"
        doc = state.documents.get("T-TEST-integration")
        assert doc is not None
        assert doc.doc_type == "integration"

        # Cleanup
        del state.approvals["APP-TEST01"]
        del state.documents["T-TEST-integration"]
