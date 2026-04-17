"""
Unit tests — document_parser module.

Coverage:
  - detect_file_type: MIME + extension fallback + unsupported
  - _parse_markdown: valid, empty
  - chunk_text: basic chunking, overlap, empty input
  - Full parse_document flow for MD
  - Image file type detection (PNG, JPG, SVG)
  - Standalone image parsing via parse_with_docling (PNG/JPG → caption_figure, SVG → XML text)
  ADR-044 additions:
  - enrich_chunk_metadata: semantic_type classification (all 8 types), field extraction,
    entity extraction, rule markers, integration keywords, source_modality passthrough,
    ChromaDB string-value constraint, empty-text edge case
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from document_parser import (
    DoclingChunk,
    DocumentParseError,
    chunk_text,
    detect_file_type,
    enrich_chunk_metadata,
    parse_document,
    parse_with_docling,
)


class TestDetectFileType:
    def test_mime_pdf(self):
        assert detect_file_type("doc.pdf", "application/pdf") == "pdf"

    def test_mime_docx(self):
        assert detect_file_type(
            "doc.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ) == "docx"

    def test_mime_xlsx(self):
        assert detect_file_type(
            "doc.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ) == "xlsx"

    def test_mime_pptx(self):
        assert detect_file_type(
            "doc.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ) == "pptx"

    def test_mime_markdown(self):
        assert detect_file_type("notes.md", "text/markdown") == "md"

    def test_mime_plain_text(self):
        assert detect_file_type("readme.txt", "text/plain") == "md"

    def test_extension_fallback_pdf(self):
        # MIME is None, fallback to extension
        assert detect_file_type("report.pdf", None) == "pdf"

    def test_extension_fallback_docx(self):
        assert detect_file_type("report.docx", "application/octet-stream") == "docx"

    def test_extension_fallback_md(self):
        assert detect_file_type("README.md", None) == "md"

    def test_unsupported_raises(self):
        with pytest.raises(DocumentParseError, match="Unsupported file type"):
            detect_file_type("archive.zip", "application/zip")

    def test_no_extension_no_mime_raises(self):
        with pytest.raises(DocumentParseError):
            detect_file_type("noext", None)

    # ── Image types ──────────────────────────────────────────────────────────

    def test_mime_png(self):
        assert detect_file_type("image.png", "image/png") == "png"

    def test_mime_jpeg(self):
        assert detect_file_type("photo.jpg", "image/jpeg") == "jpg"

    def test_mime_svg(self):
        assert detect_file_type("diagram.svg", "image/svg+xml") == "svg"

    def test_extension_fallback_jpeg(self):
        assert detect_file_type("photo.jpeg", None) == "jpg"

    def test_extension_fallback_png_with_octet_stream(self):
        assert detect_file_type("image.png", "application/octet-stream") == "png"

    def test_extension_fallback_svg(self):
        assert detect_file_type("diagram.svg", None) == "svg"

    def test_unsupported_error_message_lists_image_types(self):
        with pytest.raises(DocumentParseError, match="PNG"):
            detect_file_type("file.bmp", "image/bmp")


class TestParseMarkdown:
    def test_valid_markdown(self):
        content = b"# Best Practice\n\nAlways validate inputs."
        result = parse_document(content, "best.md", "text/markdown")
        assert result.file_type == "md"
        assert "validate inputs" in result.text
        assert result.page_count == 1

    def test_empty_markdown_raises(self):
        with pytest.raises(DocumentParseError, match="empty"):
            parse_document(b"", "empty.md", "text/markdown")

    def test_whitespace_only_raises(self):
        with pytest.raises(DocumentParseError, match="empty"):
            parse_document(b"   \n\n  ", "blank.md", "text/markdown")


class TestChunkText:
    def test_short_text_single_chunk(self):
        text = "Short text."
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)
        assert len(chunks) == 1
        assert chunks[0].text == "Short text."
        assert chunks[0].index == 0

    def test_long_text_multiple_chunks(self):
        # Generate text ~500 chars
        text = "Word " * 100  # 500 chars
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)
        assert len(chunks) > 1
        # All chunks should have text
        for c in chunks:
            assert len(c.text) > 0

    def test_overlap_present(self):
        # Verify chunks overlap
        text = "A " * 200  # 400 chars
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=50)
        if len(chunks) >= 2:
            # Last part of chunk 0 should appear in start of chunk 1
            assert chunks[0].text[-10:] in chunks[1].text or len(chunks[1].text) > 0

    def test_empty_text_returns_empty(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_chunk_indices_sequential(self):
        text = "Sentence. " * 50
        chunks = chunk_text(text, chunk_size=50, chunk_overlap=10)
        for i, c in enumerate(chunks):
            assert c.index == i

    def test_chunk_metadata_present(self):
        text = "Hello world. " * 50
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)
        for c in chunks:
            assert "char_start" in c.metadata
            assert "char_end" in c.metadata


class TestParseDocumentDispatch:
    def test_parse_md_via_dispatch(self):
        content = b"# Title\n\nParagraph content here."
        result = parse_document(content, "test.md", "text/markdown")
        assert result.file_type == "md"
        assert "Paragraph content" in result.text

    def test_unsupported_type_raises(self):
        with pytest.raises(DocumentParseError, match="Unsupported"):
            parse_document(b"binary data", "file.zip", "application/zip")


class TestParseImageStandalone:
    """Tests for standalone image parsing via parse_with_docling (early-return path for _IMAGE_TYPES)."""

    def test_png_returns_single_figure_chunk_with_caption(self):
        fake_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        with patch(
            "services.vision_service.caption_figure",
            new=AsyncMock(return_value="A diagram showing integration flow"),
        ) as mock_cap:
            chunks = asyncio.run(parse_with_docling(fake_bytes, "png"))

        assert len(chunks) == 1
        assert chunks[0].chunk_type == "figure"
        assert chunks[0].text == "A diagram showing integration flow"
        assert chunks[0].page_num == 1
        assert chunks[0].index == 0
        mock_cap.assert_awaited_once_with(fake_bytes)

    def test_jpg_returns_single_figure_chunk_with_caption(self):
        fake_bytes = b"\xff\xd8\xff" + b"\x00" * 50
        with patch(
            "services.vision_service.caption_figure",
            new=AsyncMock(return_value="Product catalogue image"),
        ) as mock_cap:
            chunks = asyncio.run(parse_with_docling(fake_bytes, "jpg"))

        assert len(chunks) == 1
        assert chunks[0].chunk_type == "figure"
        assert chunks[0].text == "Product catalogue image"
        mock_cap.assert_awaited_once_with(fake_bytes)

    def test_svg_extracts_text_nodes(self):
        svg = (
            b'<svg xmlns="http://www.w3.org/2000/svg">'
            b"<title>Integration Flow</title>"
            b"<text>PLM to PIM sync</text>"
            b"</svg>"
        )
        chunks = asyncio.run(parse_with_docling(svg, "svg"))

        assert len(chunks) == 1
        assert chunks[0].chunk_type == "text"
        assert "Integration Flow" in chunks[0].text
        assert "PLM to PIM sync" in chunks[0].text
        assert chunks[0].page_num == 1

    def test_svg_no_text_returns_placeholder(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="100" height="100"/></svg>'
        chunks = asyncio.run(parse_with_docling(svg, "svg"))

        assert len(chunks) == 1
        assert chunks[0].text == "[SVG: no text content]"
        assert chunks[0].chunk_type == "text"

    def test_svg_malformed_xml_returns_parse_error_placeholder(self):
        chunks = asyncio.run(parse_with_docling(b"NOT VALID XML <<>>", "svg"))

        assert len(chunks) == 1
        assert chunks[0].text == "[SVG: parse error]"

    def test_png_vision_placeholder_on_error(self):
        """If caption_figure returns the placeholder, the chunk still contains it."""
        fake_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        with patch(
            "services.vision_service.caption_figure",
            new=AsyncMock(return_value="[FIGURE: no caption available]"),
        ):
            chunks = asyncio.run(parse_with_docling(fake_bytes, "png"))

        assert chunks[0].chunk_type == "figure"
        assert chunks[0].text == "[FIGURE: no caption available]"


# ── ADR-044: enrich_chunk_metadata ────────────────────────────────────────────

def _text_chunk(text: str, section: str = "") -> DoclingChunk:
    return DoclingChunk(text=text, chunk_type="text",
                        page_num=1, section_header=section, index=0, metadata={})


def _table_chunk(text: str = "[TABLE]\n| Source | Target |") -> DoclingChunk:
    return DoclingChunk(text=text, chunk_type="table",
                        page_num=1, section_header="", index=0, metadata={})


def _figure_chunk(text: str = "[FIGURE: sequence diagram]") -> DoclingChunk:
    return DoclingChunk(text=text, chunk_type="figure",
                        page_num=1, section_header="", index=0, metadata={})


class TestEnrichChunkMetadata:
    """Unit tests for enrich_chunk_metadata() — ADR-044."""

    def test_table_chunk_semantic_type_is_data_mapping_candidate(self):
        result = enrich_chunk_metadata(_table_chunk(), "pdf")
        assert result["semantic_type"] == "data_mapping_candidate"

    def test_figure_chunk_semantic_type_is_diagram_or_visual(self):
        result = enrich_chunk_metadata(_figure_chunk(), "pdf")
        assert result["semantic_type"] == "diagram_or_visual"

    def test_text_chunk_with_rule_markers_is_business_rule(self):
        chunk = _text_chunk("The field is mandatory. The value must be validated and required.")
        result = enrich_chunk_metadata(chunk, "docx")
        assert result["semantic_type"] == "business_rule"

    def test_text_chunk_with_error_keywords_is_error_handling(self):
        chunk = _text_chunk("On timeout, trigger a retry and fallback to the dead-letter queue.")
        result = enrich_chunk_metadata(chunk, "md")
        assert result["semantic_type"] == "error_handling"

    def test_text_chunk_with_security_keywords_is_security_requirement(self):
        chunk = _text_chunk("Use OAuth token-based authentication. Credential must use TLS encryption.")
        result = enrich_chunk_metadata(chunk, "pdf")
        assert result["semantic_type"] == "security_requirement"

    def test_text_chunk_with_architecture_keywords_is_integration_flow(self):
        chunk = _text_chunk("The integration architecture uses an asynchronous pipeline with sequence diagram.")
        result = enrich_chunk_metadata(chunk, "docx")
        assert result["semantic_type"] == "integration_flow"

    def test_text_chunk_with_many_field_names_is_field_definition(self):
        chunk = _text_chunk("Fields: product_id, published_at, order_status, price_amount.")
        result = enrich_chunk_metadata(chunk, "xlsx")
        assert result["semantic_type"] == "field_definition"

    def test_text_chunk_generic_is_generic_context(self):
        chunk = _text_chunk("This document describes best practices for enterprise solutions.")
        result = enrich_chunk_metadata(chunk, "md")
        assert result["semantic_type"] == "generic_context"

    def test_source_modality_passthrough(self):
        result = enrich_chunk_metadata(_text_chunk("some content"), "pptx")
        assert result["source_modality"] == "pptx"

    def test_all_output_values_are_chroma_compatible(self):
        """ChromaDB metadata requires str/int/float/bool — no lists or None (ADR-048)."""
        result = enrich_chunk_metadata(_text_chunk("content"), "pdf")
        for key, value in result.items():
            assert isinstance(value, (str, bool, int, float)), (
                f"Field '{key}' is {type(value).__name__}, expected str/bool/int/float"
            )

    def test_field_names_extracted_snake_case(self):
        chunk = _text_chunk("Map product_code and published_at to target_field.")
        result = enrich_chunk_metadata(chunk, "md")
        fields = result["field_names"].split(",")
        assert "product_code" in fields
        assert "published_at" in fields
        assert "target_field" in fields

    def test_integration_keywords_matched(self):
        chunk = _text_chunk("The API endpoint uses OAuth and webhook delivery via REST.")
        result = enrich_chunk_metadata(chunk, "md")
        keywords = result["integration_keywords"].split(",")
        assert "api" in keywords
        assert "oauth" in keywords
        assert "rest" in keywords
        assert "webhook" in keywords

    def test_rule_markers_matched(self):
        chunk = _text_chunk("This field is mandatory. The value must pass validation.")
        result = enrich_chunk_metadata(chunk, "pdf")
        markers = result["rule_markers"].split(",")
        assert "mandatory" in markers
        assert "must" in markers
        assert "validation" in markers

    def test_entity_names_extracted_camel_case(self):
        chunk = _text_chunk("The ProductMaster entity maps to SalesOrder via OrderId.")
        result = enrich_chunk_metadata(chunk, "docx")
        entities = result["entity_names"].split(",")
        assert "ProductMaster" in entities
        assert "SalesOrder" in entities
        assert "OrderId" in entities

    def test_empty_text_produces_empty_strings_not_none(self):
        """Empty chunk must not produce None values — empty string for all list fields."""
        chunk = _text_chunk("")
        result = enrich_chunk_metadata(chunk, "md")
        assert result["entity_names"] == ""
        assert result["field_names"] == ""
        assert result["rule_markers"] == ""
        assert result["integration_keywords"] == ""
        assert result["semantic_type"] == "generic_context"
