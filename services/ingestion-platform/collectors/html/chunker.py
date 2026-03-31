"""
HTML Collector — Chunker

Converts CanonicalCapability objects (from HTMLNormalizer) into
CanonicalChunk objects ready for ChromaDB indexing.

One chunk per capability. Mirrors the interface and ID scheme of
OpenAPIChunker so IndexingService needs zero changes.
"""
import logging

from models.capability import CanonicalCapability, CanonicalChunk

logger = logging.getLogger(__name__)


class HTMLChunker:
    """
    Produces one CanonicalChunk per CanonicalCapability.

    Chunk text format:
        [KIND] Name
        Description
        Source: <page_url>
        Section: <section>   (if present)
    """

    def chunk(
        self,
        capabilities: list[CanonicalCapability],
        source_code: str,
        tags: list[str],
    ) -> list[CanonicalChunk]:
        """
        Args:
            capabilities: Validated CanonicalCapability list from HTMLNormalizer.
            source_code: Source identifier (e.g. "payment_docs").
            tags: List of tags for RAG filtering.

        Returns:
            List of CanonicalChunk ready for IndexingService.upsert_chunks().
        """
        chunks: list[CanonicalChunk] = []
        for idx, cap in enumerate(capabilities):
            chunks.append(CanonicalChunk(
                text=self._capability_to_text(cap),
                index=idx,
                source_code=source_code,
                source_type="html",
                capability_kind=cap.kind.value,
                section_header=cap.name,
                page_url=cap.source_trace.page_url,
                tags=tags,
                confidence=cap.confidence,
            ))
        return chunks

    def _capability_to_text(self, cap: CanonicalCapability) -> str:
        lines = [f"[{cap.kind.value.upper()}] {cap.name}", cap.description]
        if cap.source_trace.page_url:
            lines.append(f"Source: {cap.source_trace.page_url}")
        if cap.source_trace.section:
            lines.append(f"Section: {cap.source_trace.section}")
        return "\n".join(filter(None, lines))
