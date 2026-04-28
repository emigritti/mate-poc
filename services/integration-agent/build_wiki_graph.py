#!/usr/bin/env python3
"""
CLI: Build or rebuild the LLM Wiki knowledge graph from ChromaDB chunk metadata.

Reads all chunks (or a single document) from the ChromaDB knowledge_base
collection, extracts entities and relationships via wiki_extractor, then
upserts them into MongoDB wiki_entities / wiki_relationships.

Usage:
    python scripts/build_wiki_graph.py [options]

Options:
    --force           Replace existing entities/rels (default: incremental merge)
    --llm-assist      Use qwen3:8b to upgrade RELATED_TO edges (slow)
    --doc-id KB-...   Rebuild only a single KB document (partial rebuild)

Environment variables (same as the integration-agent service):
    MONGO_URI, MONGO_DB, OLLAMA_HOST, TAG_MODEL, etc.
    (Read from .env in the working directory, or set in the shell.)

Exit codes:
    0  success
    1  error (logged to stderr)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure the integration-agent source is on sys.path.
# When run from repo root (scripts/build_wiki_graph.py) the source is two levels up;
# when run from inside the container (/app) the script is co-located with the source.
_here = Path(__file__).parent.resolve()
for _candidate in [_here, _here.parent.parent / "services" / "integration-agent"]:
    if (_candidate / "config.py").exists() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))
        break

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("build_wiki_graph")


async def main(args: argparse.Namespace) -> int:
    # Late imports so sys.path is patched first
    import chromadb
    import motor.motor_asyncio
    from config import settings
    from services.wiki_graph_builder import WikiGraphBuilder

    # ── MongoDB ───────────────────────────────────────────────────────────────
    logger.info("Connecting to MongoDB at %s …", settings.mongo_uri)
    client = motor.motor_asyncio.AsyncIOMotorClient(
        settings.mongo_uri, serverSelectionTimeoutMS=10_000
    )
    db = client[settings.mongo_db]

    # Ensure collections + indexes exist (idempotent)
    entities_col = db["wiki_entities"]
    relationships_col = db["wiki_relationships"]
    for idx_args in [
        ({"entity_id": 1}, {"unique": True}),
        ([("name", "text"), ("aliases", "text")], {"name": "wiki_entities_text"}),
        ({"entity_type": 1}, {}),
        ({"doc_ids": 1}, {}),
        ({"tags_csv": 1}, {}),
    ]:
        try:
            await entities_col.create_index(*idx_args[0] if isinstance(idx_args[0], list) else [idx_args[0]], **idx_args[1])
        except Exception:
            pass  # index already exists or type mismatch — ignore
    for idx_args in [
        ({"rel_id": 1}, {"unique": True}),
        ([("from_entity_id", 1), ("to_entity_id", 1)], {}),
        ({"rel_type": 1}, {}),
        ({"doc_ids": 1}, {}),
        ({"evidence_chunk_ids": 1}, {}),
    ]:
        try:
            await relationships_col.create_index(*idx_args[0] if isinstance(idx_args[0], list) else [idx_args[0]], **idx_args[1])
        except Exception:
            pass

    # ── ChromaDB ──────────────────────────────────────────────────────────────
    logger.info("Connecting to ChromaDB at %s:%s …", settings.chroma_host, settings.chroma_port)
    chroma = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    try:
        kb_col = chroma.get_collection("knowledge_base")
    except Exception as exc:
        logger.error("ChromaDB knowledge_base collection not found: %s", exc)
        client.close()
        return 1

    count = kb_col.count()
    logger.info("ChromaDB knowledge_base: %d chunks", count)
    if count == 0:
        logger.warning("No chunks found — graph will be empty.")
        client.close()
        return 0

    # ── Build ─────────────────────────────────────────────────────────────────
    builder = WikiGraphBuilder(
        entities_col=entities_col,
        relationships_col=relationships_col,
        kb_collection=kb_col,
        ollama_host=settings.ollama_host,
        llm_model=settings.tag_model,
        llm_assist=args.llm_assist,
        typed_edges_only=settings.wiki_graph_typed_edges_only,
    )

    if args.doc_id:
        logger.info("Partial rebuild for document: %s", args.doc_id)
        stats = await builder.build_for_document(args.doc_id, force=args.force)
    else:
        logger.info("Full rebuild (force=%s) …", args.force)
        stats = await builder.build(force=args.force)

    logger.info(
        "Done — %d chunks processed, %d entities upserted, %d relationships upserted",
        stats["chunks_processed"],
        stats["entities_upserted"],
        stats["relationships_upserted"],
    )
    if stats["errors"]:
        logger.warning("%d errors during build (first: %s)", len(stats["errors"]), stats["errors"][0])

    client.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build LLM Wiki knowledge graph from ChromaDB chunk metadata."
    )
    parser.add_argument("--force", action="store_true", help="Replace existing entities/rels")
    parser.add_argument("--llm-assist", action="store_true", help="Use LLM to enrich RELATED_TO edges")
    parser.add_argument("--doc-id", metavar="KB-XXXX", help="Rebuild only this document")
    args = parser.parse_args()

    sys.exit(asyncio.run(main(args)))
