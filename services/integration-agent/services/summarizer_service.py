"""
Summarizer Service — RAPTOR-lite section summarization (ADR-032).

Provides:
  - summarize_section(chunks, doc_id): generate a section summary via llama3.1:8b.

RAPTOR-lite groups document chunks by section_header and summarizes sections
with >= 3 chunks. Summaries are stored in a separate ChromaDB collection
(summaries_col) enabling multi-granularity retrieval (detail + overview).

Fallback-first: any LLM failure returns None — the upload flow continues
without a summary rather than crashing. Summaries are best-effort enrichment.

All processing is local — llama3.1:8b via Ollama (no external APIs).
"""

import logging
from dataclasses import dataclass, field

from config import settings
from services.llm_service import generate_with_retry

logger = logging.getLogger(__name__)

# Minimum number of chunks in a section to warrant summarization.
_MIN_CHUNKS_FOR_SUMMARY = 3

_SUMMARY_PROMPT_TEMPLATE = """\
You are a technical documentation assistant. Summarize the following document \
section in 2-3 sentences for use as a retrieval context in an integration document system.
Focus on: key integration patterns, field mappings, system names, and data flows.
Be concise and factual.

--- Section content ---
{content}
--- End of section ---

Summary:"""


@dataclass
class SummaryChunk:
    """A RAPTOR-lite section summary ready for ChromaDB insertion (ADR-032)."""
    text: str
    document_id: str
    section_header: str
    tags: list[str] = field(default_factory=list)


async def summarize_section(
    chunks: list,   # list[DoclingChunk] — typed as list to avoid circular import
    doc_id: str,
    tags: list[str] | None = None,
) -> SummaryChunk | None:
    """
    Generate a summary for a group of document chunks (one section).

    Returns a SummaryChunk on success, or None when:
      - raptor_summarization_enabled=False
      - fewer than _MIN_CHUNKS_FOR_SUMMARY chunks
      - LLM call fails (timeout, connection error, etc.)

    Args:
        chunks:  List of DoclingChunk objects from the same section.
        doc_id:  KB document ID (e.g. "KB-abc123").
        tags:    Optional tag list for the SummaryChunk (mirrors the KB document tags).
    """
    if not settings.raptor_summarization_enabled:
        return None

    if len(chunks) < _MIN_CHUNKS_FOR_SUMMARY:
        return None

    section_header = chunks[0].section_header if chunks else ""
    content = "\n\n".join(c.text for c in chunks)
    prompt = _SUMMARY_PROMPT_TEMPLATE.format(content=content)

    try:
        summary_text = await generate_with_retry(
            prompt,
            num_predict=150,    # summaries are short — cap tokens for speed
            temperature=0.1,    # near-deterministic for reproducible summaries
        )
        summary_text = summary_text.strip()
        if not summary_text:
            logger.warning("[Summarizer] LLM returned empty summary for doc=%s section='%s'.", doc_id, section_header)
            return None

        logger.info(
            "[Summarizer] Summary generated for doc=%s section='%s' (%d chars).",
            doc_id, section_header, len(summary_text),
        )
        return SummaryChunk(
            text=summary_text,
            document_id=doc_id,
            section_header=section_header,
            tags=tags or [],
        )
    except Exception as exc:
        logger.warning(
            "[Summarizer] Failed to summarize doc=%s section='%s': %s — skipping.",
            doc_id, section_header, exc,
        )
        return None
