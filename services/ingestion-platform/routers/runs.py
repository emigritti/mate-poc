"""
Ingestion Platform — Runs, Snapshots & Chunk Preview Router

Read-only endpoints for querying ingestion run history, source snapshots,
and ChromaDB chunk preview (what was actually indexed for a given source).
"""
from typing import Any

import chromadb
from fastapi import APIRouter, HTTPException

import state
from config import settings
from models.source import SourceRun, SourceSnapshot

router = APIRouter(prefix="/api/v1", tags=["runs"])

CHUNK_TEXT_PREVIEW_LEN = 300


def _get_chroma_collection():
    """Open a ChromaDB HTTP client and return the shared kb_collection."""
    from routers.ingest import _make_doc_embedder
    client = chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
    )
    return client.get_or_create_collection(
        "kb_collection",
        embedding_function=_make_doc_embedder(),
    )


def _doc_to_run(doc: dict) -> SourceRun:
    """Convert a MongoDB document to a SourceRun model."""
    doc.setdefault("id", str(doc.get("_id", "")))
    return SourceRun(**{k: v for k, v in doc.items() if k != "_id"})


def _doc_to_snapshot(doc: dict) -> SourceSnapshot:
    """Convert a MongoDB document to a SourceSnapshot model."""
    doc.setdefault("id", str(doc.get("_id", "")))
    return SourceSnapshot(**{k: v for k, v in doc.items() if k != "_id"})


@router.get("/runs/{run_id}", response_model=SourceRun)
async def get_run(run_id: str) -> SourceRun:
    """Get a single ingestion run by ID. Used for polling after trigger."""
    doc = await state.runs_col.find_one({"id": run_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return _doc_to_run(doc)


@router.get("/sources/{source_id}/runs", response_model=list[SourceRun])
async def get_source_runs(source_id: str) -> list[SourceRun]:
    """List the last 20 runs for a source, most recent first."""
    docs = await state.runs_col.find(
        {"source_id": source_id}
    ).sort("started_at", -1).limit(20).to_list(length=20)
    return [_doc_to_run(d) for d in docs]


@router.get("/sources/{source_id}/snapshots", response_model=list[SourceSnapshot])
async def get_source_snapshots(source_id: str) -> list[SourceSnapshot]:
    """List the last 10 snapshots for a source, most recent first."""
    docs = await state.snapshots_col.find(
        {"source_id": source_id}
    ).sort("captured_at", -1).limit(10).to_list(length=10)
    return [_doc_to_snapshot(d) for d in docs]


@router.get("/sources/{source_id}/chunks", response_model=list[dict[str, Any]])
async def get_source_chunks(source_id: str) -> list[dict[str, Any]]:
    """
    Return all ChromaDB chunks currently indexed for this source.

    Each item contains:
      - id: ChromaDB chunk ID (e.g. src_plm_api_v1-chunk-3)
      - text_preview: first 300 chars of the chunk text
      - capability_kind: endpoint | schema | overview | auth | ...
      - section_header: human-readable chunk title
      - low_confidence: bool — True if extraction confidence < 0.7
      - chunk_index: position within the source
      - snapshot_id: snapshot this chunk belongs to
    """
    # Resolve source_id → source_code (needed for ChromaDB where filter)
    source_doc = await state.sources_col.find_one({"id": source_id})
    if source_doc is None:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
    source_code = source_doc["code"]

    try:
        kb_col = _get_chroma_collection()
        result = kb_col.get(
            where={"source_code": source_code},
            include=["documents", "metadatas"],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"ChromaDB unavailable: {exc}",
        )

    ids       = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []

    chunks = []
    for chunk_id, text, meta in zip(ids, documents, metadatas):
        meta = meta or {}
        chunks.append({
            "id":               chunk_id,
            "text_preview":     (text or "")[:CHUNK_TEXT_PREVIEW_LEN],
            "text_full":        text or "",
            "capability_kind":  meta.get("capability_kind", "unknown"),
            "section_header":   meta.get("section_header", ""),
            "low_confidence":   bool(meta.get("low_confidence", False)),
            "chunk_index":      meta.get("chunk_index", 0),
            "snapshot_id":      meta.get("snapshot_id", ""),
            "tags":             (meta.get("tags_csv") or "").split(",") if meta.get("tags_csv") else [],
        })

    # Sort by chunk_index for stable display order
    chunks.sort(key=lambda c: c["chunk_index"])
    return chunks
