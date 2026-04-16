"""
HTML Collector — Cross-Page Capability Reconciler (ADR-037)

Uses Claude Sonnet to consolidate near-duplicate capabilities extracted
from multiple HTML pages. Sparse capabilities (described partially across
several pages) are merged into coherent, complete entries.

Guardrails (CLAUDE.md §11):
- Returns input unchanged when Claude is unavailable (graceful degradation)
- Returns input unchanged on API error (never silently discard)
- Processes in batches of _BATCH_SIZE to stay within token limits
- All outputs re-validated by HTMLNormalizer before returning
"""
import logging

from models.capability import CanonicalCapability

logger = logging.getLogger(__name__)

_BATCH_SIZE = 30  # max capabilities per Sonnet call


class HTMLReconciler:
    """
    Deduplicates and merges near-duplicate capabilities across pages.
    Applied after HTMLNormalizer accumulates all pages, before HTMLChunker.

    When Claude is unavailable the input list is returned as-is — the pipeline
    continues with unmerged (but valid) capabilities.
    """

    def __init__(self, claude_service=None) -> None:
        self._claude = claude_service

    async def reconcile(
        self,
        capabilities: list[CanonicalCapability],
        source_code: str,
    ) -> list[CanonicalCapability]:
        """
        Merge near-duplicate capabilities extracted from multiple pages.

        Args:
            capabilities: Validated CanonicalCapability list (all pages combined).
            source_code: Source identifier — passed to HTMLNormalizer for re-validation.

        Returns:
            Deduplicated list. Returns input unchanged if Claude unavailable or on error.
        """
        if self._claude is None:
            logger.debug("Claude unavailable — skipping reconciliation (passthrough)")
            return capabilities

        if len(capabilities) <= 1:
            return capabilities

        result: list[CanonicalCapability] = []
        for i in range(0, len(capabilities), _BATCH_SIZE):
            batch = capabilities[i : i + _BATCH_SIZE]
            merged = await self._reconcile_batch(batch, source_code)
            result.extend(merged)

        logger.info(
            "HTMLReconciler: %d capabilities → %d after reconciliation (source=%s)",
            len(capabilities), len(result), source_code,
        )
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _reconcile_batch(
        self,
        batch: list[CanonicalCapability],
        source_code: str,
    ) -> list[CanonicalCapability]:
        """Reconcile a single batch via Claude Sonnet."""
        raw_list = await self._claude.reconcile_capabilities(
            [self._cap_to_dict(c) for c in batch]
        )

        if raw_list is None:
            # API error — return batch unchanged (guardrail: never discard)
            logger.warning("Reconciler: Claude returned None — using original batch unchanged")
            return batch

        from collectors.html.normalizer import HTMLNormalizer
        normalizer = HTMLNormalizer()
        merged = normalizer.normalize(raw_list, source_code=source_code)

        if not merged:
            logger.warning("Reconciler: re-normalization returned empty — using original batch")
            return batch

        return merged

    @staticmethod
    def _cap_to_dict(cap: CanonicalCapability) -> dict:
        return {
            "name": cap.name,
            "kind": cap.kind.value,
            "description": cap.description,
            "confidence": cap.confidence,
            "source_trace": {
                "page_url": cap.source_trace.page_url or "",
                "section": cap.source_trace.section or "",
            },
        }
