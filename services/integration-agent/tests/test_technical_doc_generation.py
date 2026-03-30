"""
Unit tests for technical design document generation.
ADR-038: Two-phase doc generation — technical spec after functional approval.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException
from output_guard import sanitize_llm_output, LLMOutputValidationError
from schemas import CatalogEntry


def test_catalog_entry_has_technical_status_field():
    entry = CatalogEntry(
        id="TEST-001",
        name="Test Integration",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        created_at="2026-03-30T00:00:00Z",
    )
    assert hasattr(entry, "technical_status")
    assert entry.technical_status is None


def test_catalog_entry_technical_status_can_be_set():
    entry = CatalogEntry(
        id="TEST-001",
        name="Test Integration",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        technical_status="TECH_PENDING",
        created_at="2026-03-30T00:00:00Z",
    )
    assert entry.technical_status == "TECH_PENDING"


def test_sanitize_llm_output_technical_valid():
    raw = "# Integration Technical Design\n\n## 1. Purpose\nTest content here with enough words to pass quality.\n"
    result = sanitize_llm_output(raw, doc_type="technical")
    assert result.startswith("# Integration Technical Design")


def test_sanitize_llm_output_technical_invalid_heading():
    raw = "# Integration Functional Design\n\n## 1. Purpose\nWrong heading for technical doc.\n"
    with pytest.raises(LLMOutputValidationError):
        sanitize_llm_output(raw, doc_type="technical")


def test_sanitize_llm_output_technical_strips_preamble():
    raw = "Here is the document:\n\n# Integration Technical Design\n\n## 1. Purpose\nContent.\n"
    result = sanitize_llm_output(raw, doc_type="technical")
    assert result.startswith("# Integration Technical Design")


def test_sanitize_llm_output_functional_unchanged():
    """Existing functional behavior must not regress."""
    raw = "# Integration Functional Design\n\n## 1. Overview\nContent here.\n"
    result = sanitize_llm_output(raw, doc_type="functional")
    assert result.startswith("# Integration Functional Design")


def test_sanitize_llm_output_default_is_functional():
    """doc_type defaults to functional — no breaking change."""
    raw = "# Integration Functional Design\n\n## 1. Overview\nContent.\n"
    result = sanitize_llm_output(raw)
    assert result.startswith("# Integration Functional Design")


def test_build_technical_prompt_includes_functional_spec():
    from prompt_builder import build_technical_prompt
    result = build_technical_prompt(
        source_system="PLM",
        target_system="PIM",
        formatted_requirements="Sync product catalog every 6h",
        functional_spec="# Integration Functional Design\n\n## 1. Overview\nTest spec.",
        rag_context="",
        kb_context="",
    )
    assert "PLM" in result
    assert "PIM" in result
    assert "Sync product catalog" in result
    assert "Integration Functional Design" in result


def test_build_technical_prompt_with_feedback():
    from prompt_builder import build_technical_prompt
    result = build_technical_prompt(
        source_system="PLM",
        target_system="PIM",
        formatted_requirements="Sync products",
        functional_spec="# Integration Functional Design\nSpec content.",
        rag_context="",
        kb_context="",
        reviewer_feedback="Missing retry policy details",
    )
    assert "Missing retry policy details" in result
    assert "PREVIOUS REJECTION FEEDBACK" in result


def test_build_technical_prompt_empty_functional_spec():
    from prompt_builder import build_technical_prompt
    result = build_technical_prompt(
        source_system="PLM",
        target_system="PIM",
        formatted_requirements="Req 1",
        functional_spec="",
        rag_context="",
        kb_context="",
    )
    # Should not crash; placeholder just empty
    assert "PLM" in result


@pytest.mark.asyncio
async def test_generate_technical_doc_calls_rag_and_llm():
    """generate_technical_doc must call KB retrieval and LLM, return sanitized technical markdown."""
    from services.agent_service import generate_technical_doc
    from schemas import CatalogEntry

    entry = CatalogEntry(
        id="PLM-001",
        name="PLM to PIM Sync",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        tags=["plm", "pim"],
        created_at="2026-03-30T00:00:00Z",
    )
    functional_spec = "# Integration Functional Design\n\n## 1. Overview\nApproved spec."

    with patch("services.agent_service.hybrid_retriever") as mock_retriever, \
         patch("services.agent_service.generate_with_retry", new_callable=AsyncMock) as mock_llm, \
         patch("services.agent_service.state") as mock_state, \
         patch("services.agent_service.fetch_url_kb_context", new_callable=AsyncMock) as mock_url:

        mock_retriever.retrieve = AsyncMock(return_value=[])
        mock_retriever.retrieve_summaries = AsyncMock(return_value=[])
        mock_state.kb_collection = MagicMock()
        mock_state.kb_docs = {}
        mock_state.summaries_col = MagicMock()
        mock_url.return_value = ""
        mock_llm.return_value = (
            "# Integration Technical Design\n\n## 1. Purpose\n"
            + "Technical content " * 20
        )

        result = await generate_technical_doc(entry, functional_spec)

    assert result.startswith("# Integration Technical Design")
    mock_llm.assert_called_once()


@pytest.mark.asyncio
async def test_generate_technical_doc_uses_functional_spec_in_prompt():
    """The functional spec content must appear in the prompt sent to the LLM."""
    from services.agent_service import generate_technical_doc
    from schemas import CatalogEntry

    entry = CatalogEntry(
        id="PLM-001",
        name="Test",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        tags=["plm"],
        created_at="2026-03-30T00:00:00Z",
    )
    functional_spec = "UNIQUE_FUNCTIONAL_SPEC_MARKER_12345"

    captured_prompt: list[str] = []

    async def capture_and_return(prompt, **kwargs):
        captured_prompt.append(prompt)
        return (
            "# Integration Technical Design\n\n## 1. Purpose\n"
            + "Technical content " * 20
        )

    with patch("services.agent_service.hybrid_retriever") as mock_retriever, \
         patch("services.agent_service.generate_with_retry", side_effect=capture_and_return), \
         patch("services.agent_service.state") as mock_state, \
         patch("services.agent_service.fetch_url_kb_context", new_callable=AsyncMock) as mock_url:

        mock_retriever.retrieve = AsyncMock(return_value=[])
        mock_retriever.retrieve_summaries = AsyncMock(return_value=[])
        mock_state.kb_collection = MagicMock()
        mock_state.kb_docs = {}
        mock_state.summaries_col = MagicMock()
        mock_url.return_value = ""

        await generate_technical_doc(entry, functional_spec)

    assert len(captured_prompt) == 1
    assert "UNIQUE_FUNCTIONAL_SPEC_MARKER_12345" in captured_prompt[0]


@pytest.mark.asyncio
async def test_generate_technical_doc_reviewer_feedback_in_prompt():
    """reviewer_feedback must be wired through to the LLM prompt."""
    from services.agent_service import generate_technical_doc
    from schemas import CatalogEntry

    entry = CatalogEntry(
        id="PLM-001",
        name="Test",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        tags=["plm"],
        created_at="2026-03-30T00:00:00Z",
    )

    captured_prompt: list[str] = []

    async def capture_and_return(prompt, **kwargs):
        captured_prompt.append(prompt)
        return "# Integration Technical Design\n\n## 1. Purpose\n" + "Content " * 20

    with patch("services.agent_service.hybrid_retriever") as mock_retriever, \
         patch("services.agent_service.generate_with_retry", side_effect=capture_and_return), \
         patch("services.agent_service.state") as mock_state, \
         patch("services.agent_service.fetch_url_kb_context", new_callable=AsyncMock) as mock_url:

        mock_retriever.retrieve = AsyncMock(return_value=[])
        mock_retriever.retrieve_summaries = AsyncMock(return_value=[])
        mock_state.kb_collection = MagicMock()
        mock_state.kb_docs = {}
        mock_state.summaries_col = MagicMock()
        mock_url.return_value = ""

        await generate_technical_doc(
            entry,
            functional_spec_content="# Integration Functional Design\nSpec.",
            reviewer_feedback="UNIQUE_FEEDBACK_MARKER_67890",
        )

    assert len(captured_prompt) == 1
    assert "UNIQUE_FEEDBACK_MARKER_67890" in captured_prompt[0]
    assert "PREVIOUS REJECTION FEEDBACK" in captured_prompt[0]


# ── Task 7: approve_doc sets technical_status ────────────────────────────────

def test_approve_functional_sets_tech_pending():
    """When functional approval is approved → CatalogEntry.technical_status = TECH_PENDING."""
    from schemas import Approval, CatalogEntry, ApproveRequest

    entry = CatalogEntry(
        id="PLM-001",
        name="PLM to PIM",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        created_at="2026-03-30T00:00:00Z",
    )
    approval = Approval(
        id="APP-AAA001",
        integration_id="PLM-001",
        doc_type="functional",
        content="# Integration Functional Design\nContent",
        status="PENDING",
        generated_at="2026-03-30T00:00:00Z",
    )

    with patch("routers.approvals.state") as mock_state, \
         patch("routers.approvals.db") as mock_db:

        mock_state.approvals = {"APP-AAA001": approval}
        mock_state.catalog = {"PLM-001": entry}
        mock_state.documents = {}
        mock_db.approvals_col = None
        mock_db.documents_col = None
        mock_db.catalog_col = None

        from routers.approvals import approve_doc

        asyncio.run(approve_doc(
            id="APP-AAA001",
            body=ApproveRequest(final_markdown="# Integration Functional Design\nApproved content"),
            _token="test",
        ))

    assert entry.technical_status == "TECH_PENDING"


def test_approve_technical_sets_tech_done():
    """When technical approval is approved → CatalogEntry.technical_status = TECH_DONE."""
    from schemas import Approval, CatalogEntry, ApproveRequest

    entry = CatalogEntry(
        id="PLM-001",
        name="PLM to PIM",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        technical_status="TECH_REVIEW",
        created_at="2026-03-30T00:00:00Z",
    )
    approval = Approval(
        id="APP-BBB002",
        integration_id="PLM-001",
        doc_type="technical",
        content="# Integration Technical Design\nContent",
        status="PENDING",
        generated_at="2026-03-30T00:00:00Z",
    )

    with patch("routers.approvals.state") as mock_state, \
         patch("routers.approvals.db") as mock_db:

        mock_state.approvals = {"APP-BBB002": approval}
        mock_state.catalog = {"PLM-001": entry}
        mock_state.documents = {}
        mock_db.approvals_col = None
        mock_db.documents_col = None
        mock_db.catalog_col = None

        from routers.approvals import approve_doc

        asyncio.run(approve_doc(
            id="APP-BBB002",
            body=ApproveRequest(final_markdown="# Integration Technical Design\nApproved content"),
            _token="test",
        ))

    assert entry.technical_status == "TECH_DONE"


# ── Task 8: trigger-technical endpoint ───────────────────────────────────────

def test_trigger_technical_rejects_when_not_tech_pending():
    """Should return 409 if technical_status is not TECH_PENDING."""
    from schemas import CatalogEntry

    entry = CatalogEntry(
        id="PLM-001",
        name="PLM to PIM",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        technical_status=None,
        created_at="2026-03-30T00:00:00Z",
    )

    with patch("routers.agent.state") as mock_state:
        mock_state.catalog = {"PLM-001": entry}

        from routers.agent import trigger_technical

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(trigger_technical(integration_id="PLM-001", _token="test"))

        assert exc_info.value.status_code == 409


def test_trigger_technical_rejects_when_functional_spec_missing():
    """Should return 404 if approved functional spec doesn't exist."""
    from schemas import CatalogEntry

    entry = CatalogEntry(
        id="PLM-001",
        name="PLM to PIM",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        technical_status="TECH_PENDING",
        created_at="2026-03-30T00:00:00Z",
    )

    with patch("routers.agent.state") as mock_state:
        mock_state.catalog = {"PLM-001": entry}
        mock_state.documents = {}

        from routers.agent import trigger_technical

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(trigger_technical(integration_id="PLM-001", _token="test"))

        assert exc_info.value.status_code == 404
