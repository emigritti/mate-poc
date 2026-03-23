"""
TDD — IndexingService Unit Tests (RED phase)

Tests ChromaDB writer logic BEFORE services/indexing_service.py exists.
ChromaDB collection is mocked — no real vector DB required.
"""
import pytest
from unittest.mock import MagicMock, patch, call

from models.capability import CanonicalChunk


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_chunks(source_code: str, n: int, source_type: str = "openapi") -> list[CanonicalChunk]:
    return [
        CanonicalChunk(
            text=f"chunk text {i}",
            index=i,
            source_code=source_code,
            source_type=source_type,
            capability_kind="endpoint",
            tags=["test"],
        )
        for i in range(n)
    ]


# ── Chunk ID convention ───────────────────────────────────────────────────────

class TestChunkIdConvention:
    def test_chunk_ids_use_src_prefix(self):
        from services.indexing_service import IndexingService
        chunks = _make_chunks("payment_api", 3)
        ids = IndexingService.build_chunk_ids(chunks)
        assert ids == [
            "src_payment_api-chunk-0",
            "src_payment_api-chunk-1",
            "src_payment_api-chunk-2",
        ]

    def test_chunk_ids_never_collide_with_kb_pattern(self):
        from services.indexing_service import IndexingService
        chunks = _make_chunks("my_source", 1)
        ids = IndexingService.build_chunk_ids(chunks)
        # integration-agent uses "{doc_id}-chunk-{n}" (no "src_" prefix)
        assert all(id.startswith("src_") for id in ids)

    def test_different_sources_have_different_ids(self):
        from services.indexing_service import IndexingService
        chunks_a = _make_chunks("source_a", 2)
        chunks_b = _make_chunks("source_b", 2)
        ids_a = IndexingService.build_chunk_ids(chunks_a)
        ids_b = IndexingService.build_chunk_ids(chunks_b)
        assert set(ids_a).isdisjoint(set(ids_b))


# ── Metadata correctness ──────────────────────────────────────────────────────

class TestChunkMetadata:
    def test_metadata_has_source_type(self):
        chunk = CanonicalChunk(
            text="GET /pets", index=0, source_code="petstore",
            source_type="openapi", capability_kind="endpoint", tags=["pets"],
        )
        meta = chunk.to_chroma_metadata(snapshot_id="snap_001")
        assert meta["source_type"] == "openapi"

    def test_metadata_has_source_code(self):
        chunk = CanonicalChunk(
            text="Tool: create_ticket", index=0, source_code="jira_mcp",
            source_type="mcp", capability_kind="tool", tags=["jira"],
        )
        meta = chunk.to_chroma_metadata(snapshot_id="snap_002")
        assert meta["source_code"] == "jira_mcp"

    def test_metadata_tags_csv_joined_correctly(self):
        chunk = CanonicalChunk(
            text="Auth scheme", index=0, source_code="auth_api",
            source_type="openapi", capability_kind="auth",
            tags=["auth", "security", "oauth2"],
        )
        meta = chunk.to_chroma_metadata(snapshot_id="snap_003")
        assert meta["tags_csv"] == "auth,security,oauth2"

    def test_metadata_empty_tags_produces_empty_csv(self):
        chunk = CanonicalChunk(
            text="Some chunk", index=0, source_code="no_tags_src",
            source_type="html", capability_kind="guide_step",
        )
        meta = chunk.to_chroma_metadata(snapshot_id="snap_004")
        assert meta["tags_csv"] == ""

    def test_metadata_low_confidence_flag_set_below_threshold(self):
        chunk = CanonicalChunk(
            text="Unclear capability", index=0, source_code="html_docs",
            source_type="html", capability_kind="endpoint",
            confidence=0.5,
        )
        meta = chunk.to_chroma_metadata(snapshot_id="snap_005")
        assert meta["low_confidence"] is True

    def test_metadata_low_confidence_flag_false_above_threshold(self):
        chunk = CanonicalChunk(
            text="Clear capability", index=0, source_code="openapi_source",
            source_type="openapi", capability_kind="endpoint",
            confidence=0.9,
        )
        meta = chunk.to_chroma_metadata(snapshot_id="snap_006")
        assert meta["low_confidence"] is False

    def test_metadata_compatible_with_kb_collection_schema(self):
        """All fields expected by integration-agent retriever.py must be present."""
        chunk = CanonicalChunk(
            text="Some text", index=3, source_code="test_api",
            source_type="openapi", capability_kind="schema",
            section_header="Authentication",
        )
        meta = chunk.to_chroma_metadata(snapshot_id="snap_007")
        required_fields = {"document_id", "chunk_index", "tags_csv", "section_header", "chunk_type", "page_num"}
        assert required_fields.issubset(set(meta.keys()))


# ── IndexingService.upsert_chunks ─────────────────────────────────────────────

class TestIndexingServiceUpsert:
    def test_upsert_calls_chroma_upsert(self, mock_chroma_collection):
        from services.indexing_service import IndexingService
        svc = IndexingService(kb_collection=mock_chroma_collection)
        chunks = _make_chunks("payment_api", 2)
        svc.upsert_chunks(chunks, snapshot_id="snap_001")
        assert mock_chroma_collection.upsert.called

    def test_upsert_passes_correct_ids(self, mock_chroma_collection):
        from services.indexing_service import IndexingService
        svc = IndexingService(kb_collection=mock_chroma_collection)
        chunks = _make_chunks("payment_api", 2)
        svc.upsert_chunks(chunks, snapshot_id="snap_001")
        call_kwargs = mock_chroma_collection.upsert.call_args
        ids = call_kwargs[1]["ids"] if call_kwargs[1] else call_kwargs[0][0]
        assert "src_payment_api-chunk-0" in ids
        assert "src_payment_api-chunk-1" in ids

    def test_upsert_passes_documents(self, mock_chroma_collection):
        from services.indexing_service import IndexingService
        svc = IndexingService(kb_collection=mock_chroma_collection)
        chunks = _make_chunks("payment_api", 1)
        svc.upsert_chunks(chunks, snapshot_id="snap_001")
        call_kwargs = mock_chroma_collection.upsert.call_args
        docs = call_kwargs[1].get("documents") or call_kwargs[0][1]
        assert "chunk text 0" in docs

    def test_upsert_empty_chunks_does_not_call_chroma(self, mock_chroma_collection):
        from services.indexing_service import IndexingService
        svc = IndexingService(kb_collection=mock_chroma_collection)
        svc.upsert_chunks([], snapshot_id="snap_001")
        mock_chroma_collection.upsert.assert_not_called()


# ── IndexingService.delete_source_chunks ─────────────────────────────────────

class TestIndexingServiceDelete:
    def test_delete_source_chunks_calls_chroma_delete(self, mock_chroma_collection):
        from services.indexing_service import IndexingService
        mock_chroma_collection.get.return_value = {
            "ids": ["src_payment_api-chunk-0", "src_payment_api-chunk-1"],
            "documents": [],
            "metadatas": [],
        }
        svc = IndexingService(kb_collection=mock_chroma_collection)
        svc.delete_source_chunks("payment_api")
        assert mock_chroma_collection.delete.called

    def test_delete_uses_where_filter_on_source_code(self, mock_chroma_collection):
        from services.indexing_service import IndexingService
        mock_chroma_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        svc = IndexingService(kb_collection=mock_chroma_collection)
        svc.delete_source_chunks("payment_api")
        get_kwargs = mock_chroma_collection.get.call_args
        where = get_kwargs[1].get("where") or (get_kwargs[0][0] if get_kwargs[0] else None)
        assert where == {"source_code": "payment_api"}
