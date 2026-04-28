"""
Wiki / Graph RAG Router — ADR-052

Endpoints:
  GET  /api/v1/wiki/entities          list entities (search, filter, paginate)
  GET  /api/v1/wiki/entities/{id}     entity detail + edges + chunk preview
  GET  /api/v1/wiki/graph             subgraph JSON for React Flow
  GET  /api/v1/wiki/stats             aggregate stats
  GET  /api/v1/wiki/search            full-text search on name + aliases
  POST /api/v1/wiki/rebuild           [Token] trigger async graph rebuild job
  GET  /api/v1/wiki/rebuild/{job_id}  poll job status
  DELETE /api/v1/wiki/entities/{id}   [Token] delete entity + cascade edges
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

import db
import state
from config import settings
from routers.admin import require_token
from services.wiki_graph_builder import WikiGraphBuilder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/wiki", tags=["wiki"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_entities_col():
    if db.wiki_entities_col is None:
        raise HTTPException(503, "Wiki graph not available (MongoDB unavailable)")
    return db.wiki_entities_col


def _require_relationships_col():
    if db.wiki_relationships_col is None:
        raise HTTPException(503, "Wiki graph not available (MongoDB unavailable)")
    return db.wiki_relationships_col


async def _run_rebuild_job(job_id: str, force: bool, llm_assist: bool) -> None:
    """Background task: run full graph rebuild and update job status in state."""
    state.wiki_build_jobs[job_id]["status"] = "running"
    try:
        builder = WikiGraphBuilder(
            entities_col=db.wiki_entities_col,
            relationships_col=db.wiki_relationships_col,
            kb_collection=state.kb_collection,
            ollama_host=settings.ollama_host,
            llm_model=settings.tag_model,
            llm_assist=llm_assist,
            typed_edges_only=settings.wiki_graph_typed_edges_only,
        )
        stats = await builder.build(force=force)
        state.wiki_build_jobs[job_id].update({
            "status": "done",
            "finished_at": _now_iso(),
            "stats": stats,
        })
        logger.info("[Wiki] Rebuild job %s done: %s", job_id, stats)
    except Exception as exc:
        state.wiki_build_jobs[job_id].update({
            "status": "error",
            "finished_at": _now_iso(),
            "error": str(exc),
        })
        logger.error("[Wiki] Rebuild job %s failed: %s", job_id, exc)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/entities")
async def list_entities(
    q: str | None = Query(None, description="Full-text search on name"),
    entity_type: str | None = Query(None),
    tags: str | None = Query(None, description="Comma-separated tag filter"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List entities with optional search and filters."""
    col = _require_entities_col()

    filt: dict = {}
    if entity_type:
        filt["entity_type"] = entity_type
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            filt["tags_csv"] = {"$regex": "|".join(tag_list), "$options": "i"}
    if q:
        filt["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"aliases": {"$regex": q, "$options": "i"}},
        ]

    total = await col.count_documents(filt)
    cursor = col.find(filt, {"_id": 0}).skip(offset).limit(limit)
    entities = [doc async for doc in cursor]

    return {"entities": entities, "total": total, "limit": limit, "offset": offset}


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: str):
    """Entity detail: node + outgoing/incoming edges + chunk previews."""
    col = _require_entities_col()
    rel_col = _require_relationships_col()

    entity = await col.find_one({"entity_id": entity_id}, {"_id": 0})
    if entity is None:
        raise HTTPException(404, f"Entity '{entity_id}' not found")

    # Outgoing edges
    out_cursor = rel_col.find({"from_entity_id": entity_id}, {"_id": 0})
    outgoing = [doc async for doc in out_cursor]

    # Incoming edges
    in_cursor = rel_col.find({"to_entity_id": entity_id}, {"_id": 0})
    incoming = [doc async for doc in in_cursor]

    # Chunk previews (first 3 chunk_ids)
    chunk_ids: list[str] = entity.get("chunk_ids", [])[:3]
    chunk_previews: list[dict] = []
    if state.kb_collection is not None and chunk_ids:
        try:
            result = state.kb_collection.get(
                ids=chunk_ids, include=["documents", "metadatas"]
            )
            for cid, text, meta in zip(
                result.get("ids", []),
                result.get("documents", []),
                result.get("metadatas", []),
            ):
                chunk_previews.append({
                    "chunk_id": cid,
                    "text": (text or "")[:400],
                    "semantic_type": (meta or {}).get("semantic_type", ""),
                })
        except Exception as exc:
            logger.warning("[Wiki] chunk preview error: %s", exc)

    return {
        "entity": entity,
        "outgoing_edges": outgoing,
        "incoming_edges": incoming,
        "chunk_previews": chunk_previews,
    }


@router.get("/graph")
async def get_graph(
    entity_id: str | None = Query(None, description="Seed entity for subgraph"),
    depth: int = Query(2, ge=1, le=4),
    rel_types: str | None = Query(None, description="Comma-separated rel_type filter"),
    limit_nodes: int = Query(50, ge=1, le=200),
):
    """
    Return a subgraph as {nodes, edges} suitable for React Flow.

    If entity_id is None, returns the top limit_nodes entities by chunk_count.
    """
    col = _require_entities_col()
    rel_col = _require_relationships_col()

    rel_type_filter: list[str] | None = None
    if rel_types:
        rel_type_filter = [t.strip().upper() for t in rel_types.split(",") if t.strip()]

    if entity_id:
        # $graphLookup traversal from seed entity
        pipeline = [
            {"$match": {"entity_id": entity_id}},
            {
                "$graphLookup": {
                    "from": "wiki_relationships",
                    "startWith": "$entity_id",
                    "connectFromField": "entity_id",
                    "connectToField": "from_entity_id",
                    "as": "_traversed_rels",
                    "maxDepth": depth,
                    "depthField": "_depth",
                }
            },
        ]
        cursor = col.aggregate(pipeline)
        seed_doc = None
        traversed_rels = []
        async for doc in cursor:
            seed_doc = doc
            traversed_rels = doc.pop("_traversed_rels", [])
            break

        if seed_doc is None:
            raise HTTPException(404, f"Entity '{entity_id}' not found")

        # Collect neighbour entity_ids
        neighbour_ids: set[str] = {entity_id}
        for rel in traversed_rels:
            if rel_type_filter and rel.get("rel_type") not in rel_type_filter:
                continue
            neighbour_ids.add(rel.get("from_entity_id", ""))
            neighbour_ids.add(rel.get("to_entity_id", ""))
        neighbour_ids.discard("")
        neighbour_ids = set(list(neighbour_ids)[:limit_nodes])

        # Fetch entities
        ent_cursor = col.find(
            {"entity_id": {"$in": list(neighbour_ids)}}, {"_id": 0}
        )
        entities = [doc async for doc in ent_cursor]

        # Fetch edges between found entities
        edge_filt: dict = {
            "from_entity_id": {"$in": list(neighbour_ids)},
            "to_entity_id": {"$in": list(neighbour_ids)},
        }
        if rel_type_filter:
            edge_filt["rel_type"] = {"$in": rel_type_filter}
        edge_cursor = rel_col.find(edge_filt, {"_id": 0})
        edges = [doc async for doc in edge_cursor]
    else:
        # Full graph: top entities by chunk_count
        ent_cursor = (
            col.find({}, {"_id": 0})
            .sort("chunk_count", -1)
            .limit(limit_nodes)
        )
        entities = [doc async for doc in ent_cursor]
        entity_ids = [e["entity_id"] for e in entities]

        edge_filt = {
            "from_entity_id": {"$in": entity_ids},
            "to_entity_id": {"$in": entity_ids},
        }
        if rel_type_filter:
            edge_filt["rel_type"] = {"$in": rel_type_filter}
        edge_cursor = rel_col.find(edge_filt, {"_id": 0})
        edges = [doc async for doc in edge_cursor]

    # Transform to React Flow format
    nodes = [
        {
            "id": e["entity_id"],
            "data": {
                "label": e.get("name", e["entity_id"]),
                "entity_type": e.get("entity_type", "generic"),
                "chunk_count": e.get("chunk_count", 0),
                "tags_csv": e.get("tags_csv", ""),
            },
            "position": {"x": 0, "y": 0},  # layout handled by React Flow / Dagre
        }
        for e in entities
    ]
    rf_edges = [
        {
            "id": r["rel_id"],
            "source": r["from_entity_id"],
            "target": r["to_entity_id"],
            "label": r.get("label", r.get("rel_type", "")),
            "data": {
                "rel_type": r.get("rel_type"),
                "weight": r.get("weight", 0.8),
            },
        }
        for r in edges
    ]
    return {"nodes": nodes, "edges": rf_edges}


@router.get("/stats")
async def get_wiki_stats():
    """Aggregate counts: total entities, relationships, top entity types."""
    col = _require_entities_col()
    rel_col = _require_relationships_col()

    total_entities = await col.count_documents({})
    total_relationships = await rel_col.count_documents({})

    # Top entity types
    type_pipeline = [
        {"$group": {"_id": "$entity_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    type_cursor = col.aggregate(type_pipeline)
    entity_types = [{"type": d["_id"], "count": d["count"]} async for d in type_cursor]

    # Top entities by chunk_count
    top_cursor = col.find({}, {"entity_id": 1, "name": 1, "entity_type": 1, "chunk_count": 1, "_id": 0}).sort("chunk_count", -1).limit(5)
    top_entities = [doc async for doc in top_cursor]

    return {
        "total_entities": total_entities,
        "total_relationships": total_relationships,
        "entity_types": entity_types,
        "top_entities": top_entities,
    }


@router.get("/search")
async def search_wiki(
    q: str = Query(..., min_length=1, description="Full-text search query"),
    limit: int = Query(10, ge=1, le=50),
):
    """Full-text search over entity names and aliases."""
    col = _require_entities_col()
    results = col.find(
        {"$text": {"$search": q}},
        {"_id": 0, "score": {"$meta": "textScore"}},
    ).sort([("score", {"$meta": "textScore"})]).limit(limit)
    entities = [doc async for doc in results]
    return {"entities": entities, "query": q}


@router.post("/rebuild", status_code=202)
async def trigger_rebuild(
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Replace existing entities/rels"),
    llm_assist: bool = Query(False, description="Use LLM to upgrade RELATED_TO edges"),
    _token: None = Depends(require_token),
):
    """Trigger an async full graph rebuild. Returns a job_id for polling."""
    if db.wiki_entities_col is None or db.wiki_relationships_col is None:
        raise HTTPException(503, "Wiki graph not available (MongoDB unavailable)")
    if state.kb_collection is None:
        raise HTTPException(503, "ChromaDB knowledge_base not available")

    job_id = str(uuid.uuid4())
    state.wiki_build_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "started_at": _now_iso(),
        "finished_at": None,
        "stats": None,
        "error": None,
    }
    background_tasks.add_task(_run_rebuild_job, job_id, force, llm_assist)
    logger.info("[Wiki] Rebuild job %s queued (force=%s, llm_assist=%s)", job_id, force, llm_assist)
    return {"job_id": job_id, "status": "queued"}


@router.get("/rebuild/{job_id}")
async def get_rebuild_status(job_id: str):
    """Poll the status of a previously submitted rebuild job."""
    job = state.wiki_build_jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"Job '{job_id}' not found")
    return job


@router.delete("/entities/{entity_id}", status_code=200)
async def delete_entity(
    entity_id: str,
    _token: None = Depends(require_token),
):
    """Delete an entity and cascade-remove all its relationships."""
    col = _require_entities_col()
    rel_col = _require_relationships_col()

    entity = await col.find_one({"entity_id": entity_id})
    if entity is None:
        raise HTTPException(404, f"Entity '{entity_id}' not found")

    await col.delete_one({"entity_id": entity_id})
    del_result = await rel_col.delete_many(
        {"$or": [{"from_entity_id": entity_id}, {"to_entity_id": entity_id}]}
    )
    return {
        "entity_id": entity_id,
        "relationships_removed": del_result.deleted_count,
    }
