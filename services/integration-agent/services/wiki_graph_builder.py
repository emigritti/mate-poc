"""
Wiki Graph Builder — orchestrates entity/relationship extraction and idempotent
upsert into MongoDB wiki_entities / wiki_relationships collections (ADR-052).

Used by:
  • routers/kb.py  — background task after KB document upload
  • routers/wiki.py — POST /api/v1/wiki/rebuild  (async job)
  • scripts/build_wiki_graph.py — standalone CLI

All upserts are idempotent: doc_ids, chunk_ids, semantic_types, and
source_modalities are $addToSet merged so running the builder twice produces
no duplicates.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

import motor.motor_asyncio

from services.wiki_extractor import (
    RelationshipCandidate,
    WikiEntity,
    extract_entities_from_chunk,
    extract_relationships_rule_based,
    merge_entity_candidates,
    enrich_relationships_with_llm,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rel_id(from_id: str, to_id: str, rel_type: str) -> str:
    """Stable deterministic rel_id from edge endpoints + type."""
    key = f"{from_id}|{to_id}|{rel_type}"
    return "REL-" + hashlib.sha1(key.encode()).hexdigest()[:12]


class WikiGraphBuilder:
    """
    Builds / rebuilds the wiki knowledge graph from ChromaDB chunk metadata.

    Parameters
    ----------
    entities_col, relationships_col : AsyncIOMotorCollection
        Must already exist (created by db.init_db).
    kb_collection : chromadb Collection
        Used to fetch chunks (via .get(include=...)).
    ollama_host : str
        Required only when llm_assist=True.
    llm_model : str
        Model name for LLM-assisted relation enrichment.
    llm_assist : bool
        When True, enrich RELATED_TO edges via LLM.
    typed_edges_only : bool
        When True, store RELATED_TO edges only if no typed alternative exists.
    """

    def __init__(
        self,
        entities_col: motor.motor_asyncio.AsyncIOMotorCollection,
        relationships_col: motor.motor_asyncio.AsyncIOMotorCollection,
        kb_collection,
        ollama_host: str = "",
        llm_model: str = "qwen3:8b",
        llm_assist: bool = False,
        typed_edges_only: bool = True,
    ) -> None:
        self.entities_col = entities_col
        self.relationships_col = relationships_col
        self.kb_collection = kb_collection
        self.ollama_host = ollama_host
        self.llm_model = llm_model
        self.llm_assist = llm_assist
        self.typed_edges_only = typed_edges_only

    # ── Public API ────────────────────────────────────────────────────────────

    async def build(self, force: bool = False) -> dict:
        """Process all chunks in kb_collection and build the graph."""
        result = await self.kb_collection.get(include=["documents", "metadatas", "ids"])
        return await self._process_chunks(
            result.get("ids", []),
            result.get("documents", []),
            result.get("metadatas", []),
            force=force,
        )

    async def build_for_document(self, doc_id: str, force: bool = False) -> dict:
        """Rebuild graph for a single KB document (partial rebuild)."""
        result = await self.kb_collection.get(
            where={"document_id": doc_id},
            include=["documents", "metadatas", "ids"],
        )
        return await self._process_chunks(
            result.get("ids", []),
            result.get("documents", []),
            result.get("metadatas", []),
            force=force,
        )

    async def delete_for_document(self, doc_id: str) -> int:
        """
        Remove all entities and relationships sourced exclusively from doc_id.

        Entities referenced by other documents have doc_id pulled from their
        doc_ids array rather than being deleted entirely.
        Returns count of fully-deleted entities.
        """
        # Pull doc_id from entities that still have other sources
        await self.entities_col.update_many(
            {"doc_ids": doc_id},
            {"$pull": {"doc_ids": doc_id, "chunk_ids": {"$regex": f"^{doc_id}-"}}},
        )
        # Delete entities with no remaining doc_ids
        del_result = await self.entities_col.delete_many({"doc_ids": {"$size": 0}})
        deleted_entities = del_result.deleted_count

        # Collect orphaned entity_ids
        # Also cascade-delete relationships where both endpoints are gone
        orphan_ids_cursor = self.entities_col.find(
            {"doc_ids": {"$size": 0}}, {"entity_id": 1}
        )
        orphan_ids = [doc["entity_id"] async for doc in orphan_ids_cursor]

        await self.relationships_col.delete_many(
            {
                "$or": [
                    {"doc_ids": doc_id},
                    {"from_entity_id": {"$in": orphan_ids}},
                    {"to_entity_id": {"$in": orphan_ids}},
                ]
            }
        )
        logger.info(
            "[WikiBuilder] Deleted %d entities for doc %s", deleted_entities, doc_id
        )
        return deleted_entities

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _process_chunks(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict],
        force: bool = False,
    ) -> dict:
        stats = {
            "chunks_processed": 0,
            "entities_upserted": 0,
            "relationships_upserted": 0,
            "errors": [],
        }

        if not ids:
            return stats

        # Collect entity candidates across all chunks
        all_entity_candidates = []
        all_rel_candidates: list[RelationshipCandidate] = []

        for chunk_id, text, meta in zip(ids, documents, metadatas):
            try:
                candidates = extract_entities_from_chunk(chunk_id, text or "", meta or {})
                all_entity_candidates.extend(candidates)

                rels = extract_relationships_rule_based(chunk_id, meta or {})
                if self.llm_assist and text:
                    rels = await enrich_relationships_with_llm(
                        rels, text, self.ollama_host, self.llm_model
                    )
                all_rel_candidates.extend(rels)
                stats["chunks_processed"] += 1
            except Exception as exc:
                logger.warning("[WikiBuilder] chunk %s error: %s", chunk_id, exc)
                stats["errors"].append(str(exc))

        # Merge candidates into WikiEntity list
        entities = merge_entity_candidates(all_entity_candidates)
        stats["entities_upserted"] = await self._upsert_entities(entities, force)

        # Filter relationships: drop RELATED_TO when typed_edges_only
        if self.typed_edges_only:
            typed_pairs: set[tuple[str, str]] = {
                (c.from_entity_id, c.to_entity_id)
                for c in all_rel_candidates
                if c.rel_type != "RELATED_TO"
            }
            all_rel_candidates = [
                c for c in all_rel_candidates
                if c.rel_type != "RELATED_TO"
                or (c.from_entity_id, c.to_entity_id) not in typed_pairs
            ]

        stats["relationships_upserted"] = await self._upsert_relationships(
            all_rel_candidates, force
        )

        logger.info(
            "[WikiBuilder] built: %d chunks → %d entities, %d rels",
            stats["chunks_processed"],
            stats["entities_upserted"],
            stats["relationships_upserted"],
        )
        return stats

    async def _upsert_entities(self, entities: list[WikiEntity], force: bool) -> int:
        count = 0
        now = _now_iso()
        for e in entities:
            if force:
                # Full replace
                await self.entities_col.replace_one(
                    {"entity_id": e.entity_id},
                    {
                        "entity_id": e.entity_id,
                        "name": e.name,
                        "entity_type": e.entity_type,
                        "aliases": e.aliases,
                        "doc_ids": e.doc_ids,
                        "chunk_ids": e.chunk_ids,
                        "semantic_types": e.semantic_types,
                        "tags_csv": e.tags_csv,
                        "chunk_count": e.chunk_count,
                        "source_modalities": e.source_modalities,
                        "first_seen_at": now,
                        "updated_at": now,
                    },
                    upsert=True,
                )
            else:
                # Incremental merge: $addToSet for arrays, $set for scalars
                await self.entities_col.update_one(
                    {"entity_id": e.entity_id},
                    {
                        "$setOnInsert": {
                            "entity_id": e.entity_id,
                            "name": e.name,
                            "entity_type": e.entity_type,
                            "first_seen_at": now,
                        },
                        "$set": {"updated_at": now, "tags_csv": e.tags_csv},
                        "$addToSet": {
                            "doc_ids": {"$each": e.doc_ids},
                            "chunk_ids": {"$each": e.chunk_ids},
                            "semantic_types": {"$each": e.semantic_types},
                            "source_modalities": {"$each": e.source_modalities},
                            "aliases": {"$each": e.aliases},
                        },
                        "$inc": {"chunk_count": e.chunk_count},
                    },
                    upsert=True,
                )
            count += 1
        return count

    async def _upsert_relationships(
        self, candidates: list[RelationshipCandidate], force: bool
    ) -> int:
        count = 0
        now = _now_iso()
        seen_ids: set[str] = set()

        for c in candidates:
            if c.from_entity_id == c.to_entity_id:
                continue  # skip self-loops
            rid = _rel_id(c.from_entity_id, c.to_entity_id, c.rel_type)
            if rid in seen_ids:
                continue
            seen_ids.add(rid)

            if force:
                await self.relationships_col.replace_one(
                    {"rel_id": rid},
                    {
                        "rel_id": rid,
                        "from_entity_id": c.from_entity_id,
                        "to_entity_id": c.to_entity_id,
                        "rel_type": c.rel_type,
                        "label": c.label,
                        "weight": c.weight,
                        "evidence_chunk_ids": [c.chunk_id],
                        "extraction_method": c.extraction_method,
                        "doc_ids": [c.doc_id],
                        "created_at": now,
                    },
                    upsert=True,
                )
            else:
                await self.relationships_col.update_one(
                    {"rel_id": rid},
                    {
                        "$setOnInsert": {
                            "rel_id": rid,
                            "from_entity_id": c.from_entity_id,
                            "to_entity_id": c.to_entity_id,
                            "rel_type": c.rel_type,
                            "label": c.label,
                            "weight": c.weight,
                            "extraction_method": c.extraction_method,
                            "created_at": now,
                        },
                        "$addToSet": {
                            "evidence_chunk_ids": c.chunk_id,
                            "doc_ids": c.doc_id,
                        },
                    },
                    upsert=True,
                )
            count += 1
        return count
