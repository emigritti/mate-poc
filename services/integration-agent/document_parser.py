"""
Integration Agent — Document Parser
Extracts text content from uploaded best-practice documents for Knowledge Base ingestion.

Supported formats:
  - PDF  (via PyMuPDF / fitz)
  - DOCX (via python-docx)
  - XLSX (via openpyxl)
  - PPTX (via python-pptx)
  - MD   (plain text read)

Each parser returns the full text content as a string.  The chunker then
splits the text into overlapping fragments ready for ChromaDB insertion.
"""

import io
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── MIME type mapping ─────────────────────────────────────────────────────────
ALLOWED_KB_MIME: dict[str, str] = {
    # PDF
    "application/pdf": "pdf",
    # Word
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "docx",
    # Excel
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xlsx",
    # PowerPoint
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.ms-powerpoint": "pptx",
    # Markdown / plain text
    "text/markdown": "md",
    "text/plain": "md",
    "text/x-markdown": "md",
}

# Also accept by file extension (fallback when MIME is unreliable)
ALLOWED_KB_EXTENSIONS: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".pptx": "pptx",
    ".ppt": "pptx",
    ".md": "md",
    ".txt": "md",
}


# ── Exceptions ────────────────────────────────────────────────────────────────

class DocumentParseError(ValueError):
    """Raised when a document cannot be parsed."""


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ParseResult:
    """Result of document parsing."""
    text: str
    file_type: str
    page_count: int  # pages/slides/sheets depending on format


@dataclass
class TextChunk:
    """A single chunk of text ready for vector insertion."""
    text: str
    index: int       # 0-based chunk position
    metadata: dict   # {source_page, ...}


# ── Format-specific parsers ───────────────────────────────────────────────────

def _parse_pdf(data: bytes) -> ParseResult:
    """Extract text from PDF using PyMuPDF."""
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise DocumentParseError(f"Failed to open PDF: {exc}") from exc

    pages: list[str] = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            pages.append(text.strip())

    doc.close()

    if not pages:
        raise DocumentParseError("PDF contains no extractable text.")

    return ParseResult(
        text="\n\n".join(pages),
        file_type="pdf",
        page_count=len(pages),
    )


def _parse_docx(data: bytes) -> ParseResult:
    """Extract text from DOCX using python-docx."""
    from docx import Document as DocxDocument

    try:
        doc = DocxDocument(io.BytesIO(data))
    except Exception as exc:
        raise DocumentParseError(f"Failed to open DOCX: {exc}") from exc

    paragraphs: list[str] = []

    # Extract paragraphs
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            paragraphs.append(text)

    # Extract tables
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                paragraphs.append(" | ".join(cells))

    if not paragraphs:
        raise DocumentParseError("DOCX contains no extractable text.")

    return ParseResult(
        text="\n\n".join(paragraphs),
        file_type="docx",
        page_count=1,  # DOCX doesn't have a simple page concept
    )


def _parse_xlsx(data: bytes) -> ParseResult:
    """Extract text from XLSX using openpyxl."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise DocumentParseError(f"Failed to open XLSX: {exc}") from exc

    sheets: list[str] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows: list[str] = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            sheets.append(f"## Sheet: {sheet_name}\n" + "\n".join(rows))

    wb.close()

    if not sheets:
        raise DocumentParseError("XLSX contains no extractable text.")

    return ParseResult(
        text="\n\n".join(sheets),
        file_type="xlsx",
        page_count=len(sheets),
    )


def _parse_pptx(data: bytes) -> ParseResult:
    """Extract text from PPTX using python-pptx."""
    from pptx import Presentation

    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as exc:
        raise DocumentParseError(f"Failed to open PPTX: {exc}") from exc

    slides: list[str] = []
    for i, slide in enumerate(prs.slides, 1):
        texts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if text:
                        texts.append(text)
        # Also extract notes
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            for para in slide.notes_slide.notes_text_frame.paragraphs:
                note = para.text.strip()
                if note:
                    texts.append(f"[Note] {note}")
        if texts:
            slides.append(f"--- Slide {i} ---\n" + "\n".join(texts))

    if not slides:
        raise DocumentParseError("PPTX contains no extractable text.")

    return ParseResult(
        text="\n\n".join(slides),
        file_type="pptx",
        page_count=len(slides),
    )


def _parse_markdown(data: bytes) -> ParseResult:
    """Read markdown/plain text as-is."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise DocumentParseError(f"Cannot decode text file: {exc}") from exc

    if not text.strip():
        raise DocumentParseError("Markdown file is empty.")

    return ParseResult(
        text=text.strip(),
        file_type="md",
        page_count=1,
    )


# ── Parser dispatch ───────────────────────────────────────────────────────────

_PARSERS: dict[str, callable] = {
    "pdf": _parse_pdf,
    "docx": _parse_docx,
    "xlsx": _parse_xlsx,
    "pptx": _parse_pptx,
    "md": _parse_markdown,
}


def detect_file_type(filename: str, content_type: str | None) -> str:
    """Determine file type from MIME type or extension.

    Returns one of: pdf, docx, xlsx, pptx, md.
    Raises DocumentParseError if not supported.
    """
    # Try MIME type first
    if content_type and content_type in ALLOWED_KB_MIME:
        return ALLOWED_KB_MIME[content_type]

    # Fallback to extension
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ALLOWED_KB_EXTENSIONS:
        return ALLOWED_KB_EXTENSIONS[ext]

    raise DocumentParseError(
        f"Unsupported file type: MIME='{content_type}', filename='{filename}'. "
        f"Supported: PDF, DOCX, XLSX, PPTX, MD."
    )


def parse_document(data: bytes, filename: str, content_type: str | None) -> ParseResult:
    """Extract text from a document file.

    Args:
        data:         Raw file bytes.
        filename:     Original filename (used for extension fallback).
        content_type: MIME type from the upload (may be None or unreliable).

    Returns:
        ParseResult with extracted text, detected file type, and page count.

    Raises:
        DocumentParseError: if the file cannot be parsed or is empty.
    """
    file_type = detect_file_type(filename, content_type)
    parser = _PARSERS[file_type]

    logger.info("[KB] Parsing %s as %s (%d bytes)...", filename, file_type, len(data))

    result = parser(data)

    logger.info(
        "[KB] Parsed %s: %d chars, %d pages/sections.",
        filename, len(result.text), result.page_count,
    )
    return result


# ── Chunker ───────────────────────────────────────────────────────────────────

def chunk_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[TextChunk]:
    """Split text into overlapping chunks for vector store insertion.

    Uses sentence-aware splitting: tries to break at sentence boundaries
    (period + space) to avoid cutting mid-sentence.

    Args:
        text:          Full document text.
        chunk_size:    Target characters per chunk.
        chunk_overlap: Characters of overlap between consecutive chunks.

    Returns:
        List of TextChunk objects with text and positional metadata.
    """
    if not text.strip():
        return []

    # Normalise whitespace
    clean = re.sub(r"\n{3,}", "\n\n", text.strip())

    chunks: list[TextChunk] = []
    start = 0

    while start < len(clean):
        end = start + chunk_size

        # If not at the end, try to break at a sentence boundary
        if end < len(clean):
            # Look for last sentence-ending punctuation in the chunk
            for sep in [". ", ".\n", "\n\n", "\n", " "]:
                last_sep = clean.rfind(sep, start + chunk_size // 2, end)
                if last_sep != -1:
                    end = last_sep + len(sep)
                    break

        chunk_text_str = clean[start:end].strip()
        if chunk_text_str:
            chunks.append(TextChunk(
                text=chunk_text_str,
                index=len(chunks),
                metadata={"char_start": start, "char_end": end},
            ))

        # Advance by chunk_size - overlap
        start = max(start + 1, end - chunk_overlap)

    logger.info("[KB] Chunked text into %d chunks (size=%d, overlap=%d).", len(chunks), chunk_size, chunk_overlap)
    return chunks
