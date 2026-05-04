"""Contextual Retrieval (ADR-X4) — Anthropic Sept-2024 pattern.

Prepends a 50-100 token "situating annotation" to each chunk before embedding.
Anthropic reports +35% recall@20 with embeddings only, +49% with BM25 + reranker.

Provider selection:
  - Claude (default) — uses prompt caching aggressively (system + full doc cached
    once per ingestion, then iterates per chunk).
  - Ollama (fallback) — degraded but offline.

Compliance (CLAUDE.md §1):
  - Doc text is sent to Claude API → only synthetic / public / Accenture-Internal data.
"""
from __future__ import annotations
import asyncio
import logging
import os
from typing import Optional

import httpx

from config import settings
from document_parser import DoclingChunk

logger = logging.getLogger(__name__)

_SITUATING_SYSTEM = (
    "You contextualize text chunks for retrieval.\n"
    "Given a full document and one chunk, write 1-2 sentences (≤100 tokens) that "
    "describe where this chunk sits in the document and what it is about.\n"
    "Output ONLY the situating annotation, no preface, no XML tags."
)

_OLLAMA_PROMPT = (
    "<document>\n{doc}\n</document>\n\n"
    "<chunk>\n{chunk}\n</chunk>\n\n"
    "Situate the chunk in the document in 1-2 sentences (≤100 tokens). "
    "Output the situating annotation only."
)


def _claude_key() -> str | None:
    return settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")


def _wrap(situating: str, original: str) -> str:
    return f"<situating>\n{situating.strip()}\n</situating>\n\n<original>\n{original}\n</original>"


async def _call_claude_for_context(
    client, doc_text: str, chunk_text: str,
) -> str:
    msg = await asyncio.to_thread(
        client.messages.create,
        model=settings.contextual_model_claude,
        max_tokens=settings.contextual_max_tokens,
        system=[
            {"type": "text", "text": _SITUATING_SYSTEM,
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": f"<document>\n{doc_text}\n</document>",
             "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user",
                   "content": f"<chunk>\n{chunk_text}\n</chunk>"}],
    )
    return msg.content[0].text.strip()


async def _call_ollama_for_context(doc_text: str, chunk_text: str) -> str:
    payload = {
        "model": settings.contextual_model_ollama,
        "prompt": _OLLAMA_PROMPT.format(doc=doc_text[:8000], chunk=chunk_text[:2000]),
        "stream": False,
        "options": {"num_predict": settings.contextual_max_tokens, "temperature": 0.0},
    }
    async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as http:
        r = await http.post(f"{settings.ollama_host}/api/generate", json=payload)
        r.raise_for_status()
        return (r.json().get("response") or "").strip()


async def add_context_to_chunks(
    doc_text: str,
    chunks: list[DoclingChunk],
) -> list[DoclingChunk]:
    if not settings.contextual_retrieval_enabled or not chunks:
        return chunks

    use_claude = settings.contextual_provider == "claude" and _claude_key()
    client = None
    if use_claude:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=_claude_key())
        except Exception as exc:
            logger.warning("[Ctx-Retrieval] anthropic init failed (%s) — using Ollama.", exc)
            use_claude = False

    out: list[DoclingChunk] = []
    for c in chunks:
        situating: Optional[str] = None
        try:
            if use_claude and client is not None:
                situating = await _call_claude_for_context(client, doc_text, c.text)
            else:
                situating = await _call_ollama_for_context(doc_text, c.text)
        except Exception as exc:
            logger.warning("[Ctx-Retrieval] failed for chunk %d (%s) — keeping original.",
                           c.index, exc)
        if situating:
            out.append(DoclingChunk(
                text=_wrap(situating, c.text),
                chunk_type=c.chunk_type,
                page_num=c.page_num,
                section_header=c.section_header,
                index=c.index,
                metadata={**c.metadata, "contextualized": True},
            ))
        else:
            out.append(c)
    return out
