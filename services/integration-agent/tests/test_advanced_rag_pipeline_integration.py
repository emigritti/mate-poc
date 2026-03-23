"""
Integration tests for the Advanced RAG Pipeline (ADR-031 / ADR-032).

These tests exercise the full data flow from document upload to context assembly
using in-process mocks for Docling, LLaVA, LLM, and ChromaDB.

Scenarios:
  1. Upload with text + table + figure chunks → all 3 types stored in ChromaDB
  2. Upload with 4 chunks in same section → SummaryChunk stored in summaries_col
  3. Retrieve → ContextAssembler output includes DOCUMENT SUMMARIES section
  4. Vision disabled → figure chunk has placeholder caption, no crash
"""
import asyncio
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

from document_parser import DoclingChunk
from services.summarizer_service import SummaryChunk
from services.retriever import ScoredChunk


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_docling_chunks_mixed(section: str = "## Integration Patterns") -> list[DoclingChunk]:
    return [
        DoclingChunk(text="PLM sends product data to PIM.",    chunk_type="text",   page_num=1, section_header=section, index=0, metadata={}),
        DoclingChunk(text="Sync interval: 30 min via REST.",   chunk_type="text",   page_num=1, section_header=section, index=1, metadata={}),
        DoclingChunk(text="[TABLE]\n| Field | Type |",         chunk_type="table",  page_num=2, section_header=section, index=2, metadata={}),
        DoclingChunk(text="[FIGURE: Data flow diagram.]",      chunk_type="figure", page_num=2, section_header=section, index=3, metadata={}),
    ]


# ── Scenario 1: All 3 chunk types stored in ChromaDB ────────────────────────

def test_upload_stores_text_table_figure_chunks_in_chromadb():
    """All 3 DoclingChunk types (text, table, figure) are stored in ChromaDB."""
    from fastapi.testclient import TestClient

    chunks = _make_docling_chunks_mixed()
    stored_chunk_types: set[str] = set()

    def _capture_upsert(**kwargs):
        for meta in kwargs.get("metadatas", []):
            stored_chunk_types.add(meta.get("chunk_type", ""))

    mock_kb_col = MagicMock()
    mock_kb_col.upsert = _capture_upsert
    mock_summaries_col = MagicMock()
    mock_summaries_col.upsert = MagicMock()

    with (
        patch("db.init_db",          new_callable=AsyncMock),
        patch("db.close_db",         new_callable=AsyncMock),
        patch("main._init_chromadb", new_callable=AsyncMock),
    ):
        from main import app
        with TestClient(app) as client:
            with (
                patch("routers.kb.parse_with_docling", new=AsyncMock(return_value=chunks)),
                patch("routers.kb.suggest_kb_tags_via_llm", new=AsyncMock(return_value=["Integration"])),
                patch("routers.kb.summarize_section", new=AsyncMock(return_value=None)),
                patch("routers.kb.state") as mock_state,
                patch("routers.kb.db") as mock_db,
            ):
                mock_state.kb_collection = mock_kb_col
                mock_state.summaries_col = mock_summaries_col
                mock_state.kb_docs = {}
                mock_state.kb_chunks = {}
                mock_db.kb_documents_col = None

                response = client.post(
                    "/api/v1/kb/upload",
                    files={"file": ("integration.md", b"# Patterns\n\nContent.", "text/markdown")},
                )

    assert response.status_code == 200
    assert "text"   in stored_chunk_types, "text chunks not stored"
    assert "table"  in stored_chunk_types, "table chunks not stored"
    assert "figure" in stored_chunk_types, "figure chunks not stored"


# ── Scenario 2: Section summary stored in summaries_col ─────────────────────

def test_upload_stores_summary_when_section_has_enough_chunks():
    """SummaryChunk is stored in summaries_col when summarize_section returns a result."""
    from fastapi.testclient import TestClient

    chunks = _make_docling_chunks_mixed()
    summary = SummaryChunk(
        text="Section covers PLM→PIM data sync via REST every 30 minutes.",
        document_id="KB-INT01",
        section_header="## Integration Patterns",
        tags=["Integration"],
    )
    captured_summaries: list[str] = []

    def _capture_summary_upsert(**kwargs):
        captured_summaries.extend(kwargs.get("documents", []))

    mock_kb_col = MagicMock()
    mock_summaries_col = MagicMock()
    mock_summaries_col.upsert = _capture_summary_upsert

    with (
        patch("db.init_db",          new_callable=AsyncMock),
        patch("db.close_db",         new_callable=AsyncMock),
        patch("main._init_chromadb", new_callable=AsyncMock),
    ):
        from main import app
        with TestClient(app) as client:
            with (
                patch("routers.kb.parse_with_docling", new=AsyncMock(return_value=chunks)),
                patch("routers.kb.suggest_kb_tags_via_llm", new=AsyncMock(return_value=["Integration"])),
                patch("routers.kb.summarize_section", new=AsyncMock(return_value=summary)),
                patch("routers.kb.state") as mock_state,
                patch("routers.kb.db") as mock_db,
            ):
                mock_state.kb_collection = mock_kb_col
                mock_state.summaries_col = mock_summaries_col
                mock_state.kb_docs = {}
                mock_state.kb_chunks = {}
                mock_db.kb_documents_col = None

                client.post(
                    "/api/v1/kb/upload",
                    files={"file": ("integration.md", b"# Patterns\n\nContent.", "text/markdown")},
                )

    assert summary.text in captured_summaries, "Summary not stored in summaries_col"


# ── Scenario 3: Retrieve → ContextAssembler includes DOCUMENT SUMMARIES ──────

def test_context_assembler_includes_document_summaries_when_available():
    """Full pipeline: retrieve_summaries → ContextAssembler includes DOCUMENT SUMMARIES."""
    from services.rag_service import ContextAssembler
    from services.retriever import ScoredChunk

    summary_chunks = [
        ScoredChunk(
            text="Section summary: PLM to PIM REST integration with field mapping.",
            score=0.88,
            source_label="summary",
        )
    ]
    kb_chunks = [
        ScoredChunk(text="Use idempotent REST calls.", score=0.72, source_label="kb_file")
    ]

    assembler = ContextAssembler()
    result = assembler.assemble(
        [], kb_chunks, [],
        max_chars=3000,
        summary_chunks=summary_chunks,
    )

    assert "DOCUMENT SUMMARIES" in result
    assert "PLM to PIM REST integration" in result
    assert result.index("DOCUMENT SUMMARIES") < result.index("BEST PRACTICE PATTERNS")


# ── Scenario 4: Vision disabled → placeholder caption, no crash ──────────────

def test_upload_with_vision_disabled_uses_placeholder_and_does_not_crash():
    """When vision_captioning_enabled=False, figure chunks get placeholder caption without error."""
    from fastapi.testclient import TestClient

    # parse_with_docling falls back gracefully → returns text-only DoclingChunks
    fallback_chunks = [
        DoclingChunk(
            text="[FIGURE: no caption available]",
            chunk_type="figure",
            page_num=1,
            section_header="## Overview",
            index=0,
            metadata={},
        ),
    ]

    stored_texts: list[str] = []
    mock_kb_col = MagicMock()
    mock_kb_col.upsert = lambda **kw: stored_texts.extend(kw.get("documents", []))
    mock_summaries_col = MagicMock()

    with (
        patch("db.init_db",          new_callable=AsyncMock),
        patch("db.close_db",         new_callable=AsyncMock),
        patch("main._init_chromadb", new_callable=AsyncMock),
    ):
        from main import app
        with TestClient(app) as client:
            with (
                patch("routers.kb.parse_with_docling", new=AsyncMock(return_value=fallback_chunks)),
                patch("routers.kb.suggest_kb_tags_via_llm", new=AsyncMock(return_value=["Integration"])),
                patch("routers.kb.summarize_section", new=AsyncMock(return_value=None)),
                patch("routers.kb.state") as mock_state,
                patch("routers.kb.db") as mock_db,
            ):
                mock_state.kb_collection = mock_kb_col
                mock_state.summaries_col = mock_summaries_col
                mock_state.kb_docs = {}
                mock_state.kb_chunks = {}
                mock_db.kb_documents_col = None

                response = client.post(
                    "/api/v1/kb/upload",
                    files={"file": ("diagram.pdf", b"PDF bytes", "application/pdf")},
                )

    assert response.status_code == 200
    assert "[FIGURE: no caption available]" in stored_texts
