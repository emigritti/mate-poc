"""
Ingestion Platform — DiffService

Compares two source snapshots to detect changes.
Uses content hash for fast equality check + operation set comparison for severity.
Optionally generates a human-readable summary via Claude Haiku (ADR-037).
"""
import logging
from typing import Any, Optional

from collectors.openapi.differ import OpenAPIDiffer

logger = logging.getLogger(__name__)


class DiffService:
    """
    Detects changes between source snapshot versions.
    Source-type agnostic: delegates format-specific diff logic to collector differs.
    """

    def __init__(self, claude_service=None) -> None:
        self._claude = claude_service
        self._openapi_differ = OpenAPIDiffer()

    def compute_openapi_diff(
        self,
        source_name: str,
        old_hash: Optional[str],
        new_spec: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Compare current OpenAPI spec against previous snapshot hash.

        Returns:
            dict with keys: changed (bool), severity, added, removed, new_hash
        """
        new_hash = self._openapi_differ.compute_hash(new_spec)
        if old_hash and not self._openapi_differ.has_changed(old_hash, new_hash):
            return {
                "changed": False,
                "severity": None,
                "added": set(),
                "removed": set(),
                "new_hash": new_hash,
                "diff_summary": "No changes detected.",
            }

        # Extract operation IDs for semantic classification
        new_ops = self._openapi_differ.extract_operation_ids(new_spec)
        old_ops: set[str] = set()  # unknown for first run
        classification = self._openapi_differ.classify_changes(old_ops, new_ops)

        return {
            "changed": True,
            "severity": classification["severity"],
            "added": classification["added"],
            "removed": classification["removed"],
            "new_hash": new_hash,
            "diff_summary": None,  # filled asynchronously by summarize()
        }

    async def summarize(
        self,
        source_name: str,
        old_ops: set[str],
        new_ops: set[str],
    ) -> str:
        """
        Generate a human-readable diff summary using Claude Haiku (if available).
        Falls back to a plain-text summary if Claude is unavailable.
        """
        if self._claude:
            return await self._claude.summarize_diff(source_name, old_ops, new_ops)
        added = new_ops - old_ops
        removed = old_ops - new_ops
        parts = []
        if added:
            parts.append(f"Added: {', '.join(sorted(added))}")
        if removed:
            parts.append(f"Removed: {', '.join(sorted(removed))}")
        return ". ".join(parts) if parts else "No changes."
