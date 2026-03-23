"""
HTML Collector — Relevance Filter

Uses Claude Haiku to decide whether a cleaned HTML page is technically
relevant (documents APIs, auth, integration flows, data schemas).

Guardrails:
- Conservative default: returns True if Claude is unavailable
- Returns True on API error (do not silently discard pages)
- Binary output: relevant / not relevant
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class HTMLRelevanceFilter:
    """
    Lightweight relevance gate using Claude Haiku.
    Called BEFORE the more expensive Sonnet extraction step.
    """

    def __init__(self, claude_service=None) -> None:
        self._claude = claude_service

    async def is_relevant(self, page_text: str, page_url: str) -> bool:
        """
        Returns True if the page is technically relevant for KB ingestion.
        Conservative default (True) when Claude is unavailable.
        """
        if self._claude is None:
            logger.debug("Claude unavailable — treating page as relevant: %s", page_url)
            return True
        return await self._claude.filter_relevance(page_text, page_url)
