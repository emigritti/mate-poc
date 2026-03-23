"""
Unit tests for services.summarizer_service (ADR-032 — RAPTOR-lite).

TDD: tests written before implementation.

Covers:
  - SummaryChunk dataclass has expected fields
  - summarize_section returns SummaryChunk with LLM-generated text
  - summarize_section returns None when raptor_summarization_enabled=False
  - summarize_section returns None when fewer than 3 chunks provided (min threshold)
  - summarize_section returns None on LLM failure (graceful degradation)
  - summarize_section includes section_header and document_id in result
  - summarize_section sends a concise prompt containing chunk texts
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from document_parser import DoclingChunk


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_chunks(n: int, section: str = "## Field Mapping") -> list[DoclingChunk]:
    return [
        DoclingChunk(
            text=f"Chunk text {i}: product_id maps to sku_{i}.",
            chunk_type="text",
            page_num=i + 1,
            section_header=section,
            index=i,
            metadata={},
        )
        for i in range(n)
    ]


def _mock_settings(enabled: bool = True):
    mock = MagicMock()
    mock.raptor_summarization_enabled = enabled
    return mock


# ── SummaryChunk dataclass ────────────────────────────────────────────────────

def test_summary_chunk_dataclass_fields():
    """SummaryChunk has text, document_id, section_header, and tags fields."""
    from services.summarizer_service import SummaryChunk

    sc = SummaryChunk(
        text="This section covers PLM to PIM field mapping rules.",
        document_id="KB-abc123",
        section_header="## Field Mapping",
        tags=["Integration", "PLM"],
    )
    assert sc.text == "This section covers PLM to PIM field mapping rules."
    assert sc.document_id == "KB-abc123"
    assert sc.section_header == "## Field Mapping"
    assert sc.tags == ["Integration", "PLM"]


# ── summarize_section ─────────────────────────────────────────────────────────

def test_summarize_section_returns_summary_chunk_with_llm_text():
    """summarize_section returns a SummaryChunk with text from generate_with_retry."""
    from services.summarizer_service import summarize_section

    chunks = _make_chunks(4)
    llm_summary = "Section covers product_id to sku mapping across 4 integration patterns."

    with patch("services.summarizer_service.settings", _mock_settings()), \
         patch("services.summarizer_service.generate_with_retry",
               new=AsyncMock(return_value=llm_summary)):
        result = asyncio.run(summarize_section(chunks, doc_id="KB-001"))

    assert result is not None
    assert result.text == llm_summary
    assert result.document_id == "KB-001"


def test_summarize_section_returns_none_when_disabled():
    """summarize_section returns None when raptor_summarization_enabled=False."""
    from services.summarizer_service import summarize_section

    chunks = _make_chunks(5)

    with patch("services.summarizer_service.settings", _mock_settings(enabled=False)):
        result = asyncio.run(summarize_section(chunks, doc_id="KB-001"))

    assert result is None


def test_summarize_section_returns_none_for_fewer_than_3_chunks():
    """summarize_section returns None when chunk count is below minimum threshold (3)."""
    from services.summarizer_service import summarize_section

    chunks = _make_chunks(2)  # below threshold

    with patch("services.summarizer_service.settings", _mock_settings()):
        result = asyncio.run(summarize_section(chunks, doc_id="KB-001"))

    assert result is None


def test_summarize_section_returns_none_on_llm_failure():
    """summarize_section returns None gracefully when LLM raises an exception."""
    from services.summarizer_service import summarize_section

    chunks = _make_chunks(4)

    with patch("services.summarizer_service.settings", _mock_settings()), \
         patch("services.summarizer_service.generate_with_retry",
               new=AsyncMock(side_effect=httpx.ConnectError("ollama down"))):
        result = asyncio.run(summarize_section(chunks, doc_id="KB-001"))

    assert result is None


def test_summarize_section_preserves_section_header():
    """SummaryChunk.section_header matches the chunks' section_header."""
    from services.summarizer_service import summarize_section

    chunks = _make_chunks(3, section="## Error Handling Patterns")

    with patch("services.summarizer_service.settings", _mock_settings()), \
         patch("services.summarizer_service.generate_with_retry",
               new=AsyncMock(return_value="Summary of error handling.")):
        result = asyncio.run(summarize_section(chunks, doc_id="KB-002"))

    assert result is not None
    assert result.section_header == "## Error Handling Patterns"


def test_summarize_section_prompt_contains_chunk_texts():
    """summarize_section builds a prompt containing the text of all chunks."""
    from services.summarizer_service import summarize_section

    chunks = _make_chunks(3)
    captured_prompt: list[str] = []

    async def _capture(prompt, **kwargs):
        captured_prompt.append(prompt)
        return "summary text"

    with patch("services.summarizer_service.settings", _mock_settings()), \
         patch("services.summarizer_service.generate_with_retry", new=_capture):
        asyncio.run(summarize_section(chunks, doc_id="KB-003"))

    assert captured_prompt, "generate_with_retry was not called"
    prompt = captured_prompt[0]
    for chunk in chunks:
        assert chunk.text in prompt, f"Chunk text '{chunk.text}' missing from prompt"
