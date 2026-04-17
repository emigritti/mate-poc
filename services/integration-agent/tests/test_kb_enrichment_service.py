"""Unit tests for services/kb_enrichment_service.py — ADR-048."""
from unittest.mock import MagicMock, call
import pytest

from services.kb_enrichment_service import (
    BatchEnrichmentResult,
    EnrichmentResult,
    _csv_to_list,
    _infer_modality_from_filename,
    enrich_all_documents,
    enrich_document,
)


# ── _csv_to_list ──────────────────────────────────────────────────────────────

class TestCsvToList:
    def test_empty_string(self):
        assert _csv_to_list("") == []

    def test_single_value(self):
        assert _csv_to_list("erp") == ["erp"]

    def test_multiple_values(self):
        assert _csv_to_list("erp,order,plm") == ["erp", "order", "plm"]

    def test_strips_whitespace(self):
        assert _csv_to_list(" erp , order ") == ["erp", "order"]


# ── _infer_modality_from_filename ─────────────────────────────────────────────

class TestInferModality:
    def test_pdf(self):
        assert _infer_modality_from_filename("doc.pdf") == "pdf"

    def test_docx(self):
        assert _infer_modality_from_filename("spec.docx") == "docx"

    def test_image(self):
        assert _infer_modality_from_filename("fig.png") == "image"

    def test_unknown_extension(self):
        assert _infer_modality_from_filename("file.xyz") == "unknown"

    def test_no_extension(self):
        assert _infer_modality_from_filename("noextension") == "unknown"

    def test_empty_filename(self):
        assert _infer_modality_from_filename("") == "unknown"


# ── EnrichmentResult ─────────────────────────────────────────────────────────

class TestEnrichmentResult:
    def test_success_when_no_errors(self):
        r = EnrichmentResult(doc_id="KB-001")
        assert r.success is True

    def test_failure_when_errors(self):
        r = EnrichmentResult(doc_id="KB-001", errors=["something went wrong"])
        assert r.success is False


# ── enrich_document ───────────────────────────────────────────────────────────

def _mock_collection(ids, documents, metadatas):
    col = MagicMock()
    col.get.return_value = {"ids": ids, "documents": documents, "metadatas": metadatas}
    return col


class TestEnrichDocument:
    def test_enriches_v1_chunks(self):
        col = _mock_collection(
            ids=["KB-001-chunk-0"],
            documents=["The order_id is mandatory."],
            metadatas=[{"document_id": "KB-001", "chunk_type": "text", "filename": "spec.pdf"}],
        )
        result = enrich_document("KB-001", col)
        assert result.success
        assert result.chunks_processed == 1
        assert result.chunks_skipped_already_v2 == 0
        col.upsert.assert_called_once()

    def test_skips_already_v2_without_force(self):
        col = _mock_collection(
            ids=["KB-001-chunk-0"],
            documents=["Some text."],
            metadatas=[{"document_id": "KB-001", "chunk_type": "text", "kb_schema_version": "v2"}],
        )
        result = enrich_document("KB-001", col)
        assert result.chunks_skipped_already_v2 == 1
        assert result.chunks_processed == 0
        col.upsert.assert_not_called()

    def test_force_re_enriches_v2_chunks(self):
        col = _mock_collection(
            ids=["KB-001-chunk-0"],
            documents=["Some text."],
            metadatas=[{"document_id": "KB-001", "chunk_type": "text", "kb_schema_version": "v2"}],
        )
        result = enrich_document("KB-001", col, force=True)
        assert result.chunks_processed == 1
        col.upsert.assert_called_once()

    def test_empty_collection_returns_zero_processed(self):
        col = _mock_collection(ids=[], documents=[], metadatas=[])
        result = enrich_document("KB-MISSING", col)
        assert result.chunks_processed == 0
        assert result.success

    def test_chroma_get_failure_returns_error(self):
        col = MagicMock()
        col.get.side_effect = RuntimeError("Connection failed")
        result = enrich_document("KB-001", col)
        assert not result.success
        assert len(result.errors) == 1

    def test_upsert_failure_returns_error(self):
        col = _mock_collection(
            ids=["KB-001-chunk-0"],
            documents=["Mandatory validation must be applied."],
            metadatas=[{"document_id": "KB-001", "chunk_type": "text"}],
        )
        col.upsert.side_effect = RuntimeError("Upsert failed")
        result = enrich_document("KB-001", col)
        assert not result.success

    def test_extra_legacy_fields_preserved(self):
        col = _mock_collection(
            ids=["KB-001-chunk-0"],
            documents=["Some text."],
            metadatas=[{
                "document_id": "KB-001",
                "chunk_type": "text",
                "source_type": "openapi",
                "custom_legacy_field": "value123",
            }],
        )
        enrich_document("KB-001", col)
        _, upsert_kwargs = col.upsert.call_args
        written_meta = col.upsert.call_args[1]["metadatas"][0] if col.upsert.call_args[1] else col.upsert.call_args[0][2][0]
        # Check via the positional or keyword call
        upsert_call = col.upsert.call_args
        meta_written = (upsert_call.kwargs or {}).get("metadatas") or upsert_call.args[2] if upsert_call.args else []
        if meta_written:
            assert meta_written[0].get("custom_legacy_field") == "value123"


# ── enrich_all_documents ──────────────────────────────────────────────────────

class TestEnrichAllDocuments:
    def test_processes_multiple_documents(self):
        col = MagicMock()
        col.get.side_effect = [
            # First call: listing all metadatas
            {"metadatas": [
                {"document_id": "KB-001"},
                {"document_id": "KB-001"},
                {"document_id": "KB-002"},
            ]},
            # Second call: enrich_document("KB-001")
            {"ids": ["KB-001-chunk-0"], "documents": ["text1"], "metadatas": [{"document_id": "KB-001", "chunk_type": "text"}]},
            # Third call: enrich_document("KB-002")
            {"ids": ["KB-002-chunk-0"], "documents": ["text2"], "metadatas": [{"document_id": "KB-002", "chunk_type": "text"}]},
        ]
        summary = enrich_all_documents(col)
        assert summary.documents_processed == 2
        assert summary.total_chunks_enriched == 2

    def test_max_docs_respected(self):
        col = MagicMock()
        col.get.side_effect = [
            {"metadatas": [
                {"document_id": "KB-001"},
                {"document_id": "KB-002"},
                {"document_id": "KB-003"},
            ]},
            {"ids": ["KB-001-chunk-0"], "documents": ["t"], "metadatas": [{"document_id": "KB-001", "chunk_type": "text"}]},
        ]
        summary = enrich_all_documents(col, max_docs=1)
        assert summary.documents_processed == 1

    def test_listing_failure_returns_empty(self):
        col = MagicMock()
        col.get.side_effect = RuntimeError("DB down")
        summary = enrich_all_documents(col)
        assert summary.documents_processed == 0
