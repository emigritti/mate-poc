"""Claude Haiku LLM-judge reranker — opt-in (ADR-X3).

Compliance (CLAUDE.md §1):
  - Sends chunks to Claude API (public network) ⇒ MUST be opt-in.
  - Use only with synthetic / public / Accenture-Internal data.
  - Prompt-cached system message reduces costs by ~90%.
"""
from __future__ import annotations
import json
import logging
import os
import re

from config import settings
from services.retriever import ScoredChunk

logger = logging.getLogger(__name__)

_SYSTEM_TEMPLATE = (
    "You are a retrieval relevance judge.  Score each chunk 0-1 for the QUERY.\n"
    "Output JSON only: [{\"idx\": int, \"score\": float}, ...] in original input order.\n"
    "Do not invent chunks; do not skip any.  Be terse."
)


def _api_key() -> str | None:
    return settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")


async def llm_judge_rerank(
    query: str,
    chunks: list[ScoredChunk],
) -> list[ScoredChunk]:
    if not settings.llm_judge_enabled or not chunks:
        return chunks
    key = _api_key()
    if not key:
        logger.info("[LLM-judge] disabled — no ANTHROPIC_API_KEY.")
        return chunks
    try:
        import anthropic
    except ImportError:
        return chunks

    client = anthropic.Anthropic(api_key=key)
    user = "QUERY: " + query + "\n\nCHUNKS:\n" + "\n".join(
        f"[{i}] {c.text[:600]}" for i, c in enumerate(chunks)
    )
    try:
        msg = client.messages.create(
            model=settings.llm_judge_model,
            max_tokens=400,
            system=[
                {"type": "text", "text": _SYSTEM_TEMPLATE,
                 "cache_control": {"type": "ephemeral"}},
            ],
            messages=[{"role": "user", "content": user}],
        )
    except Exception as exc:
        logger.warning("[LLM-judge] Claude error — bypassing: %s", exc)
        return chunks

    raw = msg.content[0].text.strip()
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return chunks
    try:
        scores: list[dict] = json.loads(match.group())
    except Exception:
        return chunks

    rescored: list[ScoredChunk] = []
    for entry in scores:
        idx = entry.get("idx")
        sc = entry.get("score")
        if not isinstance(idx, int) or idx < 0 or idx >= len(chunks):
            continue
        c = chunks[idx]
        rescored.append(ScoredChunk(
            text=c.text, score=float(sc),
            source_label=c.source_label, tags=c.tags,
            doc_id=c.doc_id, semantic_type=c.semantic_type,
        ))
    return sorted(rescored, key=lambda c: c.score, reverse=True) or chunks
