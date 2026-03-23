"""
OpenAPI Collector — Chunker

Converts CanonicalCapability objects into CanonicalChunk objects ready for ChromaDB.
Generates one chunk per endpoint/schema capability + one overview chunk per spec.
"""
import logging
from typing import Any

from models.capability import CanonicalCapability, CanonicalChunk

logger = logging.getLogger(__name__)


class OpenAPIChunker:
    """
    Produces CanonicalChunk list from a list of CanonicalCapability objects.

    Strategy:
    - overview chunk: API title + description + server URLs
    - endpoint chunks: one per operation (method + path + params + response codes)
    - schema chunks: one per component schema definition
    Index is sequential across all chunk types.
    """

    def chunk(
        self,
        capabilities: list[CanonicalCapability],
        source_code: str,
        tags: list[str],
        spec_overview: dict | None = None,
    ) -> list[CanonicalChunk]:
        chunks: list[CanonicalChunk] = []
        idx = 0

        # 1. Overview chunk — prefer OVERVIEW capability from normalizer
        overview_text = self._build_overview(capabilities, spec_overview, source_code)
        # Skip OVERVIEW capabilities in per-capability chunks (already in overview_text)
        non_overview_caps = [c for c in capabilities if c.kind.value != "overview"]
        chunks.append(CanonicalChunk(
            text=overview_text,
            index=idx,
            source_code=source_code,
            source_type="openapi",
            capability_kind="overview",
            section_header="API Overview",
            tags=tags,
        ))
        idx += 1

        # 2. One chunk per capability (endpoint + schema), skip overview (already in chunk 0)
        for cap in non_overview_caps:
            text = self._capability_to_text(cap)
            chunks.append(CanonicalChunk(
                text=text,
                index=idx,
                source_code=source_code,
                source_type="openapi",
                capability_kind=cap.kind.value,
                section_header=cap.name,
                page_url=cap.source_trace.page_url,
                tags=tags,
                confidence=cap.confidence,
            ))
            idx += 1

        return chunks

    def _capability_to_text(self, cap: CanonicalCapability) -> str:
        lines = [f"[{cap.kind.value.upper()}] {cap.name}", cap.description]
        lines.append(f"Source: {cap.source_trace.origin_pointer}")
        return "\n".join(filter(None, lines))

    def _build_overview(
        self,
        capabilities: list[CanonicalCapability],
        spec_overview: dict | None,
        source_code: str,
    ) -> str:
        # Prefer OVERVIEW capability produced by normalizer (carries title + servers)
        overview_cap = next((c for c in capabilities if c.kind.value == "overview"), None)
        if overview_cap:
            lines = [overview_cap.description]
        elif spec_overview:
            title = spec_overview.get("info", {}).get("title", source_code)
            desc = spec_overview.get("info", {}).get("description", "")
            servers = [s.get("url", "") for s in spec_overview.get("servers", [])]
            lines = [f"API: {title}"]
            if desc:
                lines.append(desc)
            if servers:
                lines.append(f"Servers: {', '.join(servers)}")
        else:
            lines = [f"API: {source_code}"]

        endpoint_names = [c.name for c in capabilities if c.kind.value == "endpoint"]
        if endpoint_names:
            lines.append(f"Operations ({len(endpoint_names)}): {', '.join(endpoint_names)}")

        return "\n".join(lines)
