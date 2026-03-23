# ADR-034 — Docling Layout-Aware Parser + LLaVA Vision Captioning

| Field        | Value                                                        |
|--------------|--------------------------------------------------------------|
| **Status**   | Accepted                                                     |
| **Date**     | 2026-03-23                                                   |
| **Tags**     | document-parser, vision, docling, llava, kb, phase4          |

## Context

The previous document parser (`document_parser.py`) used LangChain
`RecursiveCharacterTextSplitter` (ADR-030) on raw text extracted with `python-docx` /
`PyMuPDF`. This approach has two critical gaps that degrade generated integration document
quality:

1. **Layout information is discarded** — page numbers, section headings, and document
   structure are not preserved in the chunk metadata, preventing section-level summarisation
   (ADR-035) and making cross-reference assembly harder.
2. **Visual content is silently dropped** — charts, architecture diagrams, and data-flow
   figures embedded in PDFs/DOCX are not analysed. Integration documents frequently use
   diagrams to convey field mappings and data flows, so omitting them is a material quality gap.

All processing must remain 100 % local to comply with Accenture data-privacy requirements.
No content may be sent to external APIs.

## Alternatives Considered

### Alt A — PyMuPDF + Tesseract OCR for figures
- PyMuPDF extracts text natively and can render page regions as images.
- Tesseract OCR would produce text from figure regions.
- **Rejected**: Tesseract is optimised for printed text, not diagrams with arrows/labels.
  Integration architecture diagrams contain sparse, non-linear text that OCR renders poorly.
  Table detection would require additional heuristics. Integration complexity outweighs benefit.

### Alt B — IBM Docling (chosen)
- Docling produces a structured `DoclingDocument` with `TextItem`, `TableItem`, and
  `PictureItem` elements, each annotated with page number, bounding-box, and section heading.
- Tables are exported as markdown (column alignment preserved).
- `PictureItem` exposes raw image bytes, which are passed to a local vision LLM.
- Fallback: if `docling` is not installed, the existing `parse_document()` + `semantic_chunk()`
  path is used transparently (no feature regression).

### Alt C — Unstructured.io
- Similar layout-aware parsing with `partition_pdf()`.
- Requires Docker image or remote API for best accuracy.
- **Rejected**: Docker dependency adds operational overhead; remote API violates data-privacy
  constraint.

## Decision

Replace per-format text extractors in `document_parser.py` with `parse_with_docling()` which:

1. Converts the uploaded file via `docling.document_converter.DocumentConverter`.
2. Iterates `doc.iterate_items()` to produce `DoclingChunk` instances:
   - `TextItem` → `chunk_type="text"`
   - `TableItem` → `chunk_type="table"`, text = markdown table export
   - `PictureItem` → `chunk_type="figure"`, text = caption from `vision_service.caption_figure()`
3. Preserves `page_num` and `section_header` on every chunk for RAPTOR-lite grouping (ADR-035).
4. Falls back to `_docling_fallback()` (legacy path) on `ImportError`.

**Vision captioning** uses `llava:7b` via the Ollama `/api/chat` endpoint with base64-encoded
image bytes. The call is governed by `settings.vision_captioning_enabled` (default `True`) and
`settings.vision_model_name` (default `"llava:7b"`). When disabled or on any network/model
error, `caption_figure()` returns `"[FIGURE: no caption available]"` — no exception propagates
to the upload handler.

Figure chunks are included in the BM25 index so that keyword queries on diagram labels
(e.g. "field mapping", "REST endpoint") can match captions.

## New Dataclass

```python
@dataclass
class DoclingChunk:
    text: str
    chunk_type: str      # "text" | "table" | "figure"
    page_num: int
    section_header: str
    index: int
    metadata: dict
```

`ParseResult` (returned by the legacy `parse_document()`) is unchanged for backward compat.

## Dependencies

| Package             | Version   | Purpose                                  |
|---------------------|-----------|------------------------------------------|
| `docling`           | ≥ 2.0     | Layout-aware PDF/DOCX parsing            |
| `httpx`             | existing  | Ollama `/api/chat` calls (vision)        |

## Configuration

| Setting                       | Default     | Purpose                                    |
|-------------------------------|-------------|--------------------------------------------|
| `vision_captioning_enabled`   | `True`      | Enable/disable LLaVA captioning            |
| `vision_model_name`           | `"llava:7b"` | Ollama model used for figure captioning   |

## Validation Plan

- `tests/test_document_parser_docling.py` — 7 tests:
  - `DoclingChunk` fields populated correctly per item type
  - Table chunks contain markdown table text
  - Figure chunks call `caption_figure()` (mocked)
  - Fallback path triggered on `ImportError`
  - Empty document returns empty list
- `tests/test_vision_service.py` — 5 tests:
  - Caption returned on successful Ollama call
  - `vision_captioning_enabled=False` returns placeholder
  - `TimeoutException` returns placeholder
  - `ConnectError` returns placeholder
  - `HTTPStatusError` returns placeholder
- `tests/test_advanced_rag_pipeline_integration.py`:
  - Scenario 1: upload with text+table+figure → all 3 `chunk_type` values in ChromaDB metadata
  - Scenario 4: vision disabled → figure chunk stored with placeholder caption, no crash

## Rollback

1. Set `VISION_CAPTIONING_ENABLED=false` in `.env` → captions become placeholder strings immediately.
2. If `parse_with_docling()` must be reverted entirely: change `routers/kb.py` to call
   `parse_document()` + `semantic_chunk()`. `DoclingChunk`s already in ChromaDB remain
   queryable; BM25 is rebuilt from existing metadata on next restart.
3. Remove `docling` from `requirements.txt`; uninstall with `pip uninstall docling`.

No database migration required.

## Accenture Compliance

All processing is performed locally:
- Docling runs in-process (CPU/GPU via local Python package).
- LLaVA captioning calls the local Ollama daemon (`OLLAMA_HOST` env var, default `localhost`).
- No bytes leave the server boundary at any stage.
