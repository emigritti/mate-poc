"""
HTML Collector — Agentic Semantic Extractor (ADR-037)

Uses Claude Sonnet to extract structured capabilities from cleaned HTML text.
Output: list of raw capability dicts validated by HTMLNormalizer.

Guardrails (CLAUDE.md §11):
- Returns [] when Claude is unavailable (graceful degradation)
- Low confidence items (< 0.7) are kept but not discarded
- All outputs validated by HTMLNormalizer before DB write
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class HTMLAgentExtractor:
    """
    Extracts CanonicalCapability-compatible dicts from HTML documentation.
    Delegates to ClaudeService.extract_capabilities() for the actual LLM call.
    """

    def __init__(self, claude_service=None) -> None:
        self._claude = claude_service

    async def extract(self, page_text: str, page_url: str) -> list[dict[str, Any]]:
        """
        Extract capabilities from a single cleaned HTML page.

        Args:
            page_text: Cleaned text from HTMLCleaner (no raw HTML).
            page_url: Source URL for citation in source_trace.

        Returns:
            List of raw capability dicts (validated by HTMLNormalizer).
            Returns [] if Claude is unavailable or on error.
        """
        if self._claude is None:
            logger.debug("Claude unavailable — skipping extraction for %s", page_url)
            return []
        return await self._claude.extract_capabilities(page_text, page_url)
