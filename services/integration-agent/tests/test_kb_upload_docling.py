"""
Unit tests for KB upload flow with Docling pipeline (ADR-031 / ADR-032 / ADR-044).

TDD: tests written before modifying routers/kb.py.

Verifies:
  - Upload endpoint calls parse_with_docling (not legacy parse_document)
  - DoclingChunks are stored in kb_collection with chunk_type, page_num, section_header metadata
  - Summaries are generated for sections with >= 3 chunks and upserted to summaries_col
  - Figure chunks are included in BM25 rebuild (all chunk types in state.kb_chunks)
  ADR-044 additions:
  - Semantic metadata fields (semantic_type, entity_names, field_names, rule_markers,
    integration_keywords, source_modality) are present in every ChromaDB chunk upsert
"""
import asyncio
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from document_parser import DoclingChunk
from services.summarizer_service import SummaryChunk


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_docling_chunks(section: str = "## Field Mapping") -> list[DoclingChunk]:
    """Return 4 DoclingChunks: 2 text + 1 table + 1 figure, all in same section."""
    return [
        DoclingChunk(text="PLM product_id maps to PIM sku.", chunk_type="text",
                     page_num=1, section_header=section, index=0, metadata={}),
        DoclingChunk(text="Sync runs every 30 minutes via REST.", chunk_type="text",
                     page_num=1, section_header=section, index=1, metadata={}),
        DoclingChunk(text="[TABLE]\n| Source | Target |\n| product_id | sku |",
                     chunk_type="table", page_num=2, section_header=section, index=2, metadata={}),
        DoclingChunk(text="[FIGURE: Flow diagram showing sync between PLM and PIM.]",
                     chunk_type="figure", page_num=2, section_header=section, index=3, metadata={}),
    ]


@pytest.fixture(scope="module")
def client():
    """TestClient with all external services mocked."""
    with (
        patch("db.init_db",          new_callable=AsyncMock),
        patch("db.close_db",         new_callable=AsyncMock),
        patch("main._init_chromadb", new_callable=AsyncMock),
    ):
        from main import app
        with TestClient(app) as c:
            yield c


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_upload_calls_parse_with_docling_not_legacy_parser(client):
    """KB upload uses parse_with_docling — NOT the legacy parse_document + semantic_chunk."""
    chunks = _make_docling_chunks()

    mock_kb_col = MagicMock()
    mock_summaries_col = MagicMock()

    with patch("routers.kb.parse_with_docling", new=AsyncMock(return_value=chunks)) as mock_docling, \
         patch("routers.kb.suggest_kb_tags_via_llm", new=AsyncMock(return_value=["Integration"])), \
         patch("routers.kb.summarize_section", new=AsyncMock(return_value=None)), \
         patch("routers.kb.state") as mock_state, \
         patch("routers.kb.db") as mock_db:
        mock_state.kb_collection = mock_kb_col
        mock_state.summaries_col = mock_summaries_col
        mock_state.kb_docs = {}
        mock_state.kb_chunks = {}
        mock_db.kb_documents_col = None

        response = client.post(
            "/api/v1/kb/upload",
            files={"file": ("test.md", b"# Section\n\nSome content here.", "text/markdown")},
        )

    assert response.status_code == 200
    mock_docling.assert_called_once()


def test_upload_stores_chunk_type_in_chromadb_metadata(client):
    """DoclingChunks are stored with chunk_type, page_num, section_header in ChromaDB metadata."""
    chunks = _make_docling_chunks()
    captured_metadatas: list[list[dict]] = []

    def _capture_upsert(**kwargs):
        captured_metadatas.append(kwargs.get("metadatas", []))

    mock_kb_col = MagicMock()
    mock_kb_col.upsert = _capture_upsert
    mock_summaries_col = MagicMock()

    with patch("routers.kb.parse_with_docling", new=AsyncMock(return_value=chunks)), \
         patch("routers.kb.suggest_kb_tags_via_llm", new=AsyncMock(return_value=["Integration"])), \
         patch("routers.kb.summarize_section", new=AsyncMock(return_value=None)), \
         patch("routers.kb.state") as mock_state, \
         patch("routers.kb.db") as mock_db:
        mock_state.kb_collection = mock_kb_col
        mock_state.summaries_col = mock_summaries_col
        mock_state.kb_docs = {}
        mock_state.kb_chunks = {}
        mock_db.kb_documents_col = None

        client.post(
            "/api/v1/kb/upload",
            files={"file": ("test.md", b"# Section\n\nSome content.", "text/markdown")},
        )

    assert captured_metadatas, "ChromaDB upsert was not called"
    meta_list = captured_metadatas[0]
    # Verify all 4 chunks have chunk_type stored
    chunk_types = {m["chunk_type"] for m in meta_list}
    assert "text" in chunk_types
    assert "table" in chunk_types
    assert "figure" in chunk_types
    # Verify section_header and page_num are present
    assert all("section_header" in m for m in meta_list)
    assert all("page_num" in m for m in meta_list)


def test_upload_upserts_summary_to_summaries_col_when_section_has_enough_chunks(client):
    """SummaryChunk is upserted to summaries_col when summarize_section returns non-None."""
    chunks = _make_docling_chunks()
    summary = SummaryChunk(
        text="Field mapping section: PLM product_id → PIM sku.",
        document_id="KB-TEST01",
        section_header="## Field Mapping",
        tags=["Integration"],
    )

    captured_summaries: list = []
    mock_summaries_col = MagicMock()

    def _capture_upsert(**kwargs):
        captured_summaries.extend(kwargs.get("documents", []))

    mock_summaries_col.upsert = _capture_upsert
    mock_kb_col = MagicMock()

    with patch("routers.kb.parse_with_docling", new=AsyncMock(return_value=chunks)), \
         patch("routers.kb.suggest_kb_tags_via_llm", new=AsyncMock(return_value=["Integration"])), \
         patch("routers.kb.summarize_section", new=AsyncMock(return_value=summary)), \
         patch("routers.kb.state") as mock_state, \
         patch("routers.kb.db") as mock_db:
        mock_state.kb_collection = mock_kb_col
        mock_state.summaries_col = mock_summaries_col
        mock_state.kb_docs = {}
        mock_state.kb_chunks = {}
        mock_db.kb_documents_col = None

        client.post(
            "/api/v1/kb/upload",
            files={"file": ("test.md", b"# Section\n\nContent.", "text/markdown")},
        )

    assert summary.text in captured_summaries, "Summary was not upserted to summaries_col"


def test_upload_stores_semantic_metadata_in_chromadb(client):
    """Every chunk upserted to ChromaDB must include all 6 ADR-044 semantic metadata fields."""
    chunks = _make_docling_chunks()
    captured_metadatas: list[list[dict]] = []

    def _capture_upsert(**kwargs):
        captured_metadatas.append(kwargs.get("metadatas", []))

    mock_kb_col = MagicMock()
    mock_kb_col.upsert = _capture_upsert
    mock_summaries_col = MagicMock()

    with patch("routers.kb.parse_with_docling", new=AsyncMock(return_value=chunks)), \
         patch("routers.kb.suggest_kb_tags_via_llm", new=AsyncMock(return_value=["Integration"])), \
         patch("routers.kb.summarize_section", new=AsyncMock(return_value=None)), \
         patch("routers.kb.state") as mock_state, \
         patch("routers.kb.db") as mock_db:
        mock_state.kb_collection = mock_kb_col
        mock_state.summaries_col = mock_summaries_col
        mock_state.kb_docs = {}
        mock_state.kb_chunks = {}
        mock_db.kb_documents_col = None

        client.post(
            "/api/v1/kb/upload",
            files={"file": ("test.md", b"# Section\n\nContent.", "text/markdown")},
        )

    assert captured_metadatas, "ChromaDB upsert was not called"
    _SEMANTIC_FIELDS = {
        "semantic_type", "entity_names", "field_names",
        "rule_markers", "integration_keywords", "source_modality",
    }
    for meta in captured_metadatas[0]:
        missing = _SEMANTIC_FIELDS - set(meta.keys())
        assert not missing, f"Chunk metadata missing ADR-044 fields: {missing}"
        # All semantic values must be strings (ChromaDB constraint)
        for field in _SEMANTIC_FIELDS:
            assert isinstance(meta[field], str), f"Field '{field}' is not a string: {meta[field]!r}"


def test_upload_includes_figure_chunks_in_bm25_corpus(client):
    """Figure chunk captions are included in state.kb_chunks for BM25 indexing."""
    chunks = _make_docling_chunks()

    mock_kb_col = MagicMock()
    mock_summaries_col = MagicMock()
    captured_kb_chunks: dict = {}

    with patch("routers.kb.parse_with_docling", new=AsyncMock(return_value=chunks)), \
         patch("routers.kb.suggest_kb_tags_via_llm", new=AsyncMock(return_value=["Integration"])), \
         patch("routers.kb.summarize_section", new=AsyncMock(return_value=None)), \
         patch("routers.kb.hybrid_retriever") as mock_retriever, \
         patch("routers.kb.state") as mock_state, \
         patch("routers.kb.db") as mock_db:
        mock_state.kb_collection = mock_kb_col
        mock_state.summaries_col = mock_summaries_col
        mock_state.kb_docs = {}
        mock_state.kb_chunks = captured_kb_chunks
        mock_db.kb_documents_col = None

        client.post(
            "/api/v1/kb/upload",
            files={"file": ("test.md", b"# Section\n\nContent.", "text/markdown")},
        )

    # All 4 chunks (including figure) should be in BM25 corpus
    all_texts = []
    for texts in captured_kb_chunks.values():
        all_texts.extend(texts)

    figure_caption = "[FIGURE: Flow diagram showing sync between PLM and PIM.]"
    assert figure_caption in all_texts, "Figure caption missing from BM25 corpus"
