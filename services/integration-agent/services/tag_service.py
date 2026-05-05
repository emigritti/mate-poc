"""
Tag Service — tag extraction, LLM suggestion, KB tag suggestion.

Extracted from main.py (R15).
"""

import json
import logging
import re
from typing import Callable

from services.llm_service import generate_with_retry, llm_overrides
from config import settings

logger = logging.getLogger(__name__)


def extract_category_tags(reqs) -> list[str]:
    """Return unique, whitespace-stripped category values from requirements (max 5)."""
    seen: list[str] = []
    for r in reqs:
        tag = r.category.strip()
        if tag and tag not in seen:
            seen.append(tag)
        if len(seen) >= 5:
            break
    return seen


async def suggest_tags_via_llm(
    source: str,
    target: str,
    req_text: str,
    *,
    log_fn: Callable[[str], None] | None = None,
) -> list[str]:
    """Call LLM with a lightweight prompt to suggest up to 2 integration tags.

    Returns empty list on any failure (timeout, parse error, etc.) so the
    caller can safely ignore LLM tags and fall back to category-only tags.
    """
    short_req = req_text[:500]
    prompt = (
        f"Given this integration between {source} and {target} "
        f"with these requirements:\n{short_req}\n"
        "Suggest up to 2 short tags (1-3 words each) that best categorize "
        "this integration.\n"
        'Reply with a JSON array only. Example: ["Data Sync", "Real-time"]'
    )
    try:
        raw = await generate_with_retry(
            prompt,
            provider=llm_overrides.get("tag_provider", "ollama"),
            model=llm_overrides.get("tag_model",          settings.tag_model),
            num_predict=llm_overrides.get("tag_num_predict",    settings.tag_num_predict),
            timeout=llm_overrides.get("tag_timeout_seconds", settings.tag_timeout_seconds),
            temperature=llm_overrides.get("tag_temperature",    settings.tag_temperature),
            think=False,
            log_fn=log_fn,
        )
        # Extract JSON array from response (LLM may wrap it in prose)
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if not match:
            return []
        tags = json.loads(match.group())
        if not isinstance(tags, list):
            return []
        return [str(t).strip() for t in tags if str(t).strip()][:2]
    except Exception as exc:
        logger.warning("[Tags] LLM tag suggestion failed: %s", exc)
        return []


async def suggest_kb_tags_via_llm(
    text_preview: str,
    filename: str,
    *,
    log_fn: Callable[[str], None] | None = None,
) -> list[str]:
    """Call LLM to suggest tags for a KB document.

    Uses the same lightweight LLM settings as suggest_tags_via_llm (ADR-020).
    Returns empty list on any failure.
    """
    short_text = text_preview[:600]
    prompt = (
        f"Given this document '{filename}' with the following content preview:\n"
        f"{short_text}\n\n"
        "Suggest up to 3 short tags (1-3 words each) that best categorize "
        "this best-practice or reference document.\n"
        'Reply with a JSON array only. Example: ["Data Mapping", "Integration Pattern", "Error Handling"]'
    )
    try:
        raw = await generate_with_retry(
            prompt,
            provider=llm_overrides.get("tag_provider", "ollama"),
            model=llm_overrides.get("tag_model",          settings.tag_model),
            num_predict=llm_overrides.get("tag_num_predict",    settings.tag_num_predict),
            timeout=llm_overrides.get("tag_timeout_seconds", settings.tag_timeout_seconds),
            temperature=llm_overrides.get("tag_temperature",    settings.tag_temperature),
            think=False,
            log_fn=log_fn,
        )
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if not match:
            return []
        tags = json.loads(match.group())
        if not isinstance(tags, list):
            return []
        return [str(t).strip()[:50] for t in tags if str(t).strip()][:3]
    except Exception as exc:
        logger.warning("[KB] LLM tag suggestion failed for %s: %s", filename, exc)
        return []
