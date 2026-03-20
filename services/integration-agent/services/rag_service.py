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

logger = logging.getLogger(__name__)


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

    # Step 1: tag-filtered query using primary tag
    if tags:
        try:
            results = collection.query(
                query_texts=[query_text],
                n_results=2,
                where={"tags_csv": {"$contains": tags[0]}},
            )
            docs = (results or {}).get("documents", [[]])[0]
            if docs:
                return build_rag_context(docs), "tag_filtered"
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

    # Tag-filtered query first, then similarity fallback
    for attempt_label, where_filter in [
        ("tag_filtered", {"tags_csv": {"$contains": tags[0]}} if tags else None),
        ("similarity", None),
    ]:
        if attempt_label == "tag_filtered" and not tags:
            continue
        try:
            kwargs: dict = {"query_texts": [query_text], "n_results": 3}
            if where_filter:
                kwargs["where"] = where_filter
            results = kb_collection.query(**kwargs)
            docs = (results or {}).get("documents", [[]])[0]
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
