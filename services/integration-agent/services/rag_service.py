"""
RAG Service — ChromaDB querying and context assembly.

Extracted from main.py (R15).
Handles:
  - Approved integrations RAG (tag-filtered + similarity fallback)
  - Knowledge Base RAG (file chunks + URL live fetch)
  - Context fusion and truncation
"""

import logging
import re
from typing import Callable
from urllib.parse import urlparse

import httpx

from config import settings
from services.llm_service import llm_overrides
from services.retriever import TAGS_CSV_FIELD, ScoredChunk

logger = logging.getLogger(__name__)


def _filter_docs_by_tag(all_docs: list[str], metas: list, tag: str) -> list[str]:
    """Return docs whose ``TAGS_CSV_FIELD`` metadata contains *tag* as a substring.

    Replaces the ChromaDB ``$contains`` metadata operator (not supported in
    ChromaDB 0.5.x).  ``metas`` is the parallel list returned by
    ``collection.query(include=["metadatas"])``.
    """
    return [d for d, m in zip(all_docs, metas) if tag in (m or {}).get(TAGS_CSV_FIELD, "")]


def build_rag_context(docs: list[str]) -> str:
    """Join docs and truncate to prevent prompt overflow on CPU instances."""
    raw = "\n---\n".join(docs)
    max_chars = llm_overrides.get("rag_max_chars", settings.ollama_rag_max_chars)
    if len(raw) > max_chars:
        logger.info("[RAG] Context truncated to %d chars (was %d).", max_chars, len(raw))
        return raw[:max_chars]
    return raw


async def query_rag_with_tags(
    query_text: str,
    tags: list[str],
    collection,
    *,
    log_fn: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """Query ChromaDB with tag filter, falling back to similarity search.

    Returns:
        (rag_context, source_label)
        source_label: "tag_filtered" | "similarity_fallback" | "none"
    """
    _log = log_fn or (lambda msg: logger.info(msg))

    if not collection:
        return "", "none"

    # Step 1: tag-filtered query using primary tag.
    # Python post-filter on tags_csv — ChromaDB 0.5.x metadata 'where' does
    # not support $contains on string fields (R12 / ADR-019).
    if tags:
        try:
            results = collection.query(
                query_texts=[query_text],
                n_results=10,
                include=["documents", "metadatas"],
            )
            all_docs = (results or {}).get("documents", [[]])[0]
            metas    = (results or {}).get("metadatas",  [[]])[0]
            docs     = _filter_docs_by_tag(all_docs, metas, tags[0])
            if docs:
                return build_rag_context(docs[:2]), "tag_filtered"
        except Exception as exc:
            _log(f"[RAG] Tag-filtered query failed: {exc}")

        _log(f"[RAG] No tagged examples for {tags} — fallback to similarity search.")

    # Step 2: similarity fallback (no metadata filter)
    try:
        results = collection.query(query_texts=[query_text], n_results=2)
        docs = (results or {}).get("documents", [[]])[0]
        if docs:
            return build_rag_context(docs), "similarity_fallback"
    except Exception as exc:
        _log(f"[ERROR] ChromaDB similarity query failed: {exc}")

    return "", "none"


async def query_kb_context(
    query_text: str,
    tags: list[str],
    kb_collection,
    *,
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """Query the Knowledge Base collection for relevant best-practice context.

    Returns a string of joined KB chunks (truncated to kb_max_rag_chars).
    Returns empty string if KB is unavailable or has no results.
    """
    _log = log_fn or (lambda msg: logger.info(msg))

    if not kb_collection:
        return ""

    # Tag-filtered query first, then similarity fallback.
    # Python post-filter on tags_csv — ChromaDB 0.5.x metadata 'where' does
    # not support $contains on string fields (R12 / ADR-019).
    for attempt_label, filter_tag in [
        ("tag_filtered", tags[0] if tags else None),
        ("similarity", None),
    ]:
        if attempt_label == "tag_filtered" and not filter_tag:
            continue
        try:
            n_results = 15 if filter_tag else 3
            include   = ["documents", "metadatas"] if filter_tag else ["documents"]
            results = kb_collection.query(
                query_texts=[query_text],
                n_results=n_results,
                include=include,
            )
            all_docs = (results or {}).get("documents", [[]])[0]
            if filter_tag:
                metas = (results or {}).get("metadatas", [[]])[0]
                docs  = _filter_docs_by_tag(all_docs, metas, filter_tag)
            else:
                docs = all_docs
            if docs:
                raw = "\n---\n".join(docs)
                max_chars = settings.kb_max_rag_chars
                if len(raw) > max_chars:
                    _log(f"[KB-RAG] Context truncated to {max_chars} chars (was {len(raw)}).")
                    raw = raw[:max_chars]
                _log(f"[KB-RAG] Found {len(docs)} relevant chunk(s) via {attempt_label}.")
                return raw
        except Exception as exc:
            _log(f"[KB-RAG] {attempt_label} query failed: {exc}")

    return ""


def _extract_text_from_html(html: str) -> str:
    """Strip HTML tags and collapse whitespace to produce plain text."""
    import bleach
    plain = bleach.clean(html, tags=[], strip=True)
    return " ".join(plain.split())


async def fetch_url_kb_context(
    tags: list[str],
    kb_docs: dict,
    *,
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """Fetch live content from KB URL entries whose tags overlap with the given tags.

    Returns a concatenated string of fetched content, one block per URL.
    Unavailable URLs are represented as '[URL unavailable: <url>]' so the LLM
    is aware of the missing source.
    """
    _log = log_fn or (lambda msg: logger.info(msg))

    matched = [
        doc for doc in kb_docs.values()
        if doc.source_type == "url"
        and doc.tags
        and any(t in doc.tags for t in tags)
    ]
    if not matched:
        return ""

    parts: list[str] = []
    max_per = settings.kb_url_max_chars_per_source
    timeout = settings.kb_url_fetch_timeout_seconds

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for doc in matched:
            try:
                resp = await client.get(doc.url)
                resp.raise_for_status()
                text = _extract_text_from_html(resp.text)[:max_per]
                parts.append(f"[Source: {doc.url}]\n{text}")
                _log(f"[KB-URL] Fetched {len(text)} chars from {doc.url}")
            except Exception as exc:
                logger.warning("[KB-URL] Fetch failed for %s: %s", doc.url, exc)
                parts.append(f"[URL unavailable: {doc.url}]")

    return "\n\n".join(parts)


class ContextAssembler:
    """Unified context fusion from multiple RAG sources (R10 / ADR-029).

    Collects ScoredChunks from approved integrations, KB files, and KB URLs,
    orders by relevance score, applies a char budget, and formats with source
    section headers so the LLM can distinguish pattern types.

    Output format:
        ## PAST APPROVED EXAMPLES (use as style reference):
        ### Source: approved · score: 0.92
        [chunk]

        ## BEST PRACTICE PATTERNS (follow these patterns in your output):
        ### Source: kb_file · score: 0.87
        [chunk]
    """

    def assemble(
        self,
        approved_chunks: list[ScoredChunk],
        kb_chunks: list[ScoredChunk],
        url_chunks: list[ScoredChunk],
        max_chars: int,
        *,
        summary_chunks: list[ScoredChunk] | None = None,
        summary_max_chars: int | None = None,
    ) -> str:
        """Assemble a structured context string for the LLM prompt.

        Args:
            approved_chunks:    Chunks from approved_integrations ChromaDB collection.
            kb_chunks:          Chunks from knowledge_base ChromaDB collection.
            url_chunks:         Chunks from live-fetched URL KB entries.
            max_chars:          Hard character budget for approved + KB sections.
            summary_chunks:     RAPTOR-lite document summaries (ADR-032). Inserted
                                as the first section when provided and non-empty.
            summary_max_chars:  Char budget for the DOCUMENT SUMMARIES section.
                                Defaults to settings.rag_summary_max_chars.

        Returns:
            Formatted context string, or empty string if no chunks provided.
        """
        _summary_max = summary_max_chars if summary_max_chars is not None else settings.rag_summary_max_chars

        all_empty = (
            not approved_chunks
            and not kb_chunks
            and not url_chunks
            and not summary_chunks
        )
        if all_empty:
            return ""

        sections: list[str] = []
        chars_used = 0

        # ── DOCUMENT SUMMARIES (ADR-032 — RAPTOR-lite) — first section ────────
        if summary_chunks:
            summary_sorted = sorted(summary_chunks, key=lambda c: c.score, reverse=True)
            header = "## DOCUMENT SUMMARIES (overview context):"
            section_parts = [header]
            summary_chars = 0
            for chunk in summary_sorted:
                entry = f"### Source: summary · score: {chunk.score:.2f}\n{chunk.text}"
                if summary_chars + len(entry) > _summary_max:
                    break
                section_parts.append(entry)
                summary_chars += len(entry)
                chars_used += len(entry)
            if len(section_parts) > 1:
                sections.append("\n\n".join(section_parts))

        # Sort all chunks by score descending within each section
        approved_sorted = sorted(approved_chunks, key=lambda c: c.score, reverse=True)
        kb_sorted       = sorted(kb_chunks + url_chunks, key=lambda c: c.score, reverse=True)

        if approved_sorted and chars_used < max_chars:
            header = "## PAST APPROVED EXAMPLES (use as style reference):"
            section_parts = [header]
            for chunk in approved_sorted:
                entry = f"### Source: approved · score: {chunk.score:.2f}\n{chunk.text}"
                if chars_used + len(entry) > max_chars:
                    break
                section_parts.append(entry)
                chars_used += len(entry)
            if len(section_parts) > 1:
                sections.append("\n\n".join(section_parts))

        if kb_sorted and chars_used < max_chars:
            header = "## BEST PRACTICE PATTERNS (follow these patterns in your output):"
            section_parts = [header]
            for chunk in kb_sorted:
                label = "kb_url" if chunk.source_label == "kb_url" else "kb_file"
                entry = f"### Source: {label} · score: {chunk.score:.2f}\n{chunk.text}"
                if chars_used + len(entry) > max_chars:
                    break
                section_parts.append(entry)
                chars_used += len(entry)
            if len(section_parts) > 1:
                sections.append("\n\n".join(section_parts))

        return "\n\n".join(sections)
