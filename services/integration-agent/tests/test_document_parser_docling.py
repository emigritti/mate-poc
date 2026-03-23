"""
Unit tests for document_parser.parse_with_docling (ADR-031).

TDD: tests written before implementation.

Covers:
  - TextItem items produce DoclingChunk(chunk_type="text") with page_num and section_header
  - TableItem items produce DoclingChunk(chunk_type="table")
  - PictureItem items produce DoclingChunk(chunk_type="figure") via vision_service
  - SectionHeader items update section_header for subsequent chunks
  - DoclingChunk index is sequential (0-based)
  - Fallback to legacy parse_document when Docling raises ImportError
"""
import asyncio
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers to build fake Docling items ──────────────────────────────────────

def _make_text_item(text: str, page_no: int = 1, is_header: bool = False):
    item = MagicMock()
    item.text = text
    item.prov = [MagicMock(page_no=page_no)]
    # label mimics DocItemLabel
    item.label = MagicMock()
    item.label.value = "section_header" if is_header else "text"
    item.export_to_markdown = MagicMock(return_value=None)  # not a table
    item.__class__.__name__ = "TextItem"
    return item


def _make_table_item(markdown: str, page_no: int = 1):
    item = MagicMock()
    item.text = ""
    item.prov = [MagicMock(page_no=page_no)]
    item.label = MagicMock()
    item.label.value = "table"
    item.export_to_markdown = MagicMock(return_value=markdown)
    item.__class__.__name__ = "TableItem"
    return item


def _make_picture_item(page_no: int = 2):
    item = MagicMock()
    item.text = ""
    item.prov = [MagicMock(page_no=page_no)]
    item.label = MagicMock()
    item.label.value = "picture"
    item.__class__.__name__ = "PictureItem"
    # get_image returns a fake PIL image
    fake_pil = MagicMock()
    item.get_image = MagicMock(return_value=fake_pil)
    return item


def _build_mock_converter(items: list):
    """Return a mock DocumentConverter whose convert() yields the given items."""
    mock_doc = MagicMock()
    mock_doc.iterate_items = MagicMock(return_value=iter([(i, 0) for i in items]))

    mock_result = MagicMock()
    mock_result.document = mock_doc

    mock_converter_instance = MagicMock()
    mock_converter_instance.convert = MagicMock(return_value=mock_result)

    mock_converter_cls = MagicMock(return_value=mock_converter_instance)
    return mock_converter_cls, mock_doc


def _inject_docling_mock(converter_cls):
    """Inject fake docling modules into sys.modules so the import inside parse_with_docling succeeds."""
    docling_mod = ModuleType("docling")
    dc_mod = ModuleType("docling.document_converter")
    dc_mod.DocumentConverter = converter_cls
    stream_mod = ModuleType("docling.datamodel")
    base_mod = ModuleType("docling.datamodel.base_models")

    class _DocumentStream:
        def __init__(self, name, stream):
            self.name = name
            self.stream = stream

    base_mod.DocumentStream = _DocumentStream

    sys.modules["docling"] = docling_mod
    sys.modules["docling.document_converter"] = dc_mod
    sys.modules["docling.datamodel"] = stream_mod
    sys.modules["docling.datamodel.base_models"] = base_mod
    return base_mod


def _remove_docling_mock():
    for key in list(sys.modules.keys()):
        if key.startswith("docling"):
            del sys.modules[key]


# ── DoclingChunk dataclass ─────────────────────────────────────────────────

def test_docling_chunk_dataclass_fields():
    """DoclingChunk has text, chunk_type, page_num, section_header, index, metadata."""
    from document_parser import DoclingChunk

    chunk = DoclingChunk(
        text="Field mapping from PLM to PIM.",
        chunk_type="text",
        page_num=1,
        section_header="## Integration Overview",
        index=0,
        metadata={"source": "test"},
    )
    assert chunk.text == "Field mapping from PLM to PIM."
    assert chunk.chunk_type == "text"
    assert chunk.page_num == 1
    assert chunk.section_header == "## Integration Overview"
    assert chunk.index == 0
    assert chunk.metadata == {"source": "test"}


# ── parse_with_docling ────────────────────────────────────────────────────────

def test_parse_with_docling_text_item_produces_text_chunk():
    """TextItem items produce DoclingChunk with chunk_type='text' and correct page_num."""
    from document_parser import parse_with_docling

    text_item = _make_text_item("PLM sends product data to PIM.", page_no=1)
    converter_cls, mock_doc = _build_mock_converter([text_item])
    _inject_docling_mock(converter_cls)

    try:
        with patch("services.vision_service.caption_figure", new=AsyncMock(return_value="caption")):
            chunks = asyncio.run(parse_with_docling(b"fake pdf bytes", "pdf"))
    finally:
        _remove_docling_mock()

    assert len(chunks) == 1
    assert chunks[0].chunk_type == "text"
    assert chunks[0].text == "PLM sends product data to PIM."
    assert chunks[0].page_num == 1


def test_parse_with_docling_table_item_produces_table_chunk():
    """TableItem items produce DoclingChunk with chunk_type='table' and markdown text."""
    from document_parser import parse_with_docling

    table_item = _make_table_item("| Field | Type |\n| product_id | string |", page_no=2)
    converter_cls, _ = _build_mock_converter([table_item])
    _inject_docling_mock(converter_cls)

    try:
        with patch("services.vision_service.caption_figure", new=AsyncMock(return_value="caption")):
            chunks = asyncio.run(parse_with_docling(b"fake pdf bytes", "pdf"))
    finally:
        _remove_docling_mock()

    assert len(chunks) == 1
    assert chunks[0].chunk_type == "table"
    assert "product_id" in chunks[0].text
    assert chunks[0].page_num == 2


def test_parse_with_docling_picture_item_produces_figure_chunk():
    """PictureItem items produce DoclingChunk with chunk_type='figure' and LLaVA caption."""
    from document_parser import parse_with_docling

    picture_item = _make_picture_item(page_no=3)
    converter_cls, _ = _build_mock_converter([picture_item])
    _inject_docling_mock(converter_cls)

    try:
        with patch("services.vision_service.caption_figure", new=AsyncMock(return_value="Flow diagram of PLM sync.")):
            chunks = asyncio.run(parse_with_docling(b"fake pdf bytes", "pdf"))
    finally:
        _remove_docling_mock()

    assert len(chunks) == 1
    assert chunks[0].chunk_type == "figure"
    assert chunks[0].text == "Flow diagram of PLM sync."
    assert chunks[0].page_num == 3


def test_parse_with_docling_section_header_propagates_to_subsequent_chunks():
    """Section header text is captured and applied to following chunks as section_header."""
    from document_parser import parse_with_docling

    header_item = _make_text_item("## Field Mapping Rules", page_no=1, is_header=True)
    body_item = _make_text_item("product_id maps to sku.", page_no=1)
    converter_cls, _ = _build_mock_converter([header_item, body_item])
    _inject_docling_mock(converter_cls)

    try:
        with patch("services.vision_service.caption_figure", new=AsyncMock(return_value="caption")):
            chunks = asyncio.run(parse_with_docling(b"fake pdf bytes", "pdf"))
    finally:
        _remove_docling_mock()

    # Header item itself should not produce a chunk (it's metadata)
    assert len(chunks) == 1
    assert chunks[0].section_header == "## Field Mapping Rules"


def test_parse_with_docling_chunk_index_is_sequential():
    """DoclingChunk.index values are 0-based and sequential across all chunk types."""
    from document_parser import parse_with_docling

    items = [
        _make_text_item("First paragraph.", page_no=1),
        _make_table_item("| A | B |", page_no=1),
        _make_text_item("Second paragraph.", page_no=2),
    ]
    converter_cls, _ = _build_mock_converter(items)
    _inject_docling_mock(converter_cls)

    try:
        with patch("services.vision_service.caption_figure", new=AsyncMock(return_value="caption")):
            chunks = asyncio.run(parse_with_docling(b"fake pdf bytes", "pdf"))
    finally:
        _remove_docling_mock()

    assert [c.index for c in chunks] == [0, 1, 2]


def test_parse_with_docling_fallback_when_docling_unavailable():
    """parse_with_docling falls back to legacy parser when Docling is not installed."""
    # Remove any injected docling mock so ImportError is raised
    _remove_docling_mock()

    from document_parser import parse_with_docling, TextChunk

    # Use a simple markdown payload (no PDF parsing needed for fallback)
    md_bytes = b"# Overview\n\nThis is a test document with enough content to chunk."

    chunks = asyncio.run(parse_with_docling(md_bytes, "md"))

    # Fallback returns TextChunks wrapped as DoclingChunks
    assert len(chunks) > 0
    assert all(c.chunk_type == "text" for c in chunks)
