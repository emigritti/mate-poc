"""
Ingestion Platform — IndexingService

Writes CanonicalChunk objects into the shared ChromaDB kb_collection.
Chunk IDs use "src_{source_code}-chunk-{i}" prefix — never collides with
integration-agent IDs (which use "{doc_id}-chunk-{n}").

Design contract:
- Only this service writes to ChromaDB on behalf of ingestion-platform
- Claude outputs are NEVER written directly — always go through IndexingService
- After upsert, callers are responsible for triggering BM25 rebuild
  in integration-agent (via /api/v1/kb/rebuild-index webhook — Phase 5)
"""
import logging
from typing import Optional

from models.capability import CanonicalChunk

logger = logging.getLogger(__name__)


class IndexingService:
    def __init__(self, kb_collection) -> None:
        """
        Args:
            kb_collection: ChromaDB Collection object (real or mock).
                           Shared with integration-agent's kb_collection.
        """
        self._col = kb_collection

    # ── Static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def build_chunk_ids(chunks: list[CanonicalChunk]) -> list[str]:
        """Build ChromaDB IDs using the src_ prefix convention."""
        return [c.chunk_id() for c in chunks]

    # ── Write operations ──────────────────────────────────────────────────────

    def upsert_chunks(
        self,
        chunks: list[CanonicalChunk],
        snapshot_id: str,
    ) -> int:
        """
        Upsert chunks into the shared kb_collection.

        Args:
            chunks: CanonicalChunk list from any collector.
            snapshot_id: Links chunks to the current snapshot for versioning.

        Returns:
            Number of chunks upserted.
        """
        if not chunks:
            return 0

        ids = self.build_chunk_ids(chunks)
        documents = [c.text for c in chunks]
        metadatas = [c.to_chroma_metadata(snapshot_id=snapshot_id) for c in chunks]

        self._col.upsert(ids=ids, documents=documents, metadatas=metadatas)
        logger.info(
            "upserted %d chunks for snapshot=%s source=%s",
            len(chunks), snapshot_id, chunks[0].source_code if chunks else "?",
        )
        return len(chunks)

    def delete_source_chunks(self, source_code: str) -> int:
        """
        Delete all ChromaDB chunks belonging to a source.

        Uses ChromaDB `where` filter on source_code metadata field.
        Returns number of deleted chunks.
        """
        result = self._col.get(where={"source_code": source_code})
        ids_to_delete = result.get("ids", [])
        if ids_to_delete:
            self._col.delete(ids=ids_to_delete)
            logger.info("deleted %d chunks for source_code=%s", len(ids_to_delete), source_code)
        return len(ids_to_delete)
