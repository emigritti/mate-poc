"""
Ingestion Platform — Runs & Snapshots Router

Read-only endpoints for querying ingestion run history and source snapshots.
Used by the web dashboard (polling after trigger) and n8n WF-02 (run status polling).
"""
from fastapi import APIRouter, HTTPException

import state
from models.source import SourceRun, SourceSnapshot

router = APIRouter(prefix="/api/v1", tags=["runs"])


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
