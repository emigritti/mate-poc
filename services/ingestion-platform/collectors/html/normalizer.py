"""
HTML Collector — Normalizer

Converts raw capability dicts (from Claude extraction) to CanonicalCapability objects.
Validates required fields and applies fallbacks for optional fields.

Valid kinds (from extraction schema):
  endpoint, tool, resource, schema, auth, integration_flow, guide_step, event
Unknown kinds → guide_step (safe fallback).
"""
import logging
from typing import Any

from models.capability import CanonicalCapability, CapabilityKind, SourceTrace

logger = logging.getLogger(__name__)

_VALID_KINDS = {k.value for k in CapabilityKind}


class HTMLNormalizer:
    """
    Converts Claude extraction output dicts to validated CanonicalCapability objects.
    Applied after HTMLAgentExtractor — this is the final validation gate.
    """

    def normalize(
        self,
        raw_capabilities: list[dict[str, Any]],
        source_code: str,
    ) -> list[CanonicalCapability]:
        """
        Args:
            raw_capabilities: List of dicts from Claude extraction (or mocked).
            source_code: Source identifier for capability_id generation.

        Returns:
            List of CanonicalCapability objects. Invalid entries are logged and skipped.
        """
        result: list[CanonicalCapability] = []
        for i, raw in enumerate(raw_capabilities):
            cap = self._to_capability(raw, source_code, index=i)
            if cap is not None:
                result.append(cap)
        return result

    def _to_capability(
        self,
        raw: dict[str, Any],
        source_code: str,
        index: int,
    ) -> CanonicalCapability | None:
        name = raw.get("name", "").strip()
        if not name:
            logger.warning("Skipping capability with missing name at index %d", index)
            return None

        # Normalize kind — unknown kinds fall back to guide_step
        kind_raw = raw.get("kind", "guide_step")
        if kind_raw not in _VALID_KINDS:
            logger.debug("Unknown kind '%s' for '%s' → guide_step", kind_raw, name)
            kind_raw = "guide_step"
        kind = CapabilityKind(kind_raw)

        description = raw.get("description", "")
        confidence = float(raw.get("confidence", 1.0))

        # Source trace — required fields from Claude schema
        trace_raw = raw.get("source_trace", {})
        page_url = trace_raw.get("page_url", "")
        section = trace_raw.get("section", "")

        # UI semantic context — optional, only for ui_screen capabilities (ADR-045)
        ui_context = raw.get("ui_context")
        metadata: dict[str, Any] = {}
        if ui_context and isinstance(ui_context, dict):
            metadata["ui_context"] = ui_context

        return CanonicalCapability(
            capability_id=f"{source_code}__html__{kind_raw}__{name.replace(' ', '_')[:40]}_{index}",
            kind=kind,
            name=name,
            description=description,
            source_code=source_code,
            source_trace=SourceTrace(
                origin_type="html",
                origin_pointer=f"page:{page_url} section:{section}",
                page_url=page_url,
                section=section,
            ),
            confidence=confidence,
            metadata=metadata,
        )
