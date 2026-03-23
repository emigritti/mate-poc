"""
Ingestion Platform — Source Registry Router

CRUD endpoints for managing ingestion sources (OpenAPI, HTML, MCP).
All mutations require an API key when API_KEY env var is set.
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status

import state
from models.source import Source, SourceCreate, SourceState, SourceStatus

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


def _now() -> str:
    return datetime.utcnow().isoformat()


def _doc_to_source(doc: dict) -> Source:
    """Convert a MongoDB document to a Source model."""
    doc.setdefault("id", str(doc.get("_id", "")))
    status_raw = doc.get("status", {})
    if isinstance(status_raw, dict):
        doc["status"] = SourceStatus(**status_raw)
    return Source(**{k: v for k, v in doc.items() if k != "_id"})


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Source)
async def create_source(body: SourceCreate) -> Source:
    source_id = f"src_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow()
    doc = {
        "_id": source_id,
        "id": source_id,
        **body.model_dump(),
        "status": SourceStatus().model_dump(),
        "created_at": now,
        "updated_at": now,
    }
    await state.sources_col.insert_one(doc)
    return _doc_to_source(doc)


@router.get("", response_model=list[Source])
async def list_sources() -> list[Source]:
    docs = await state.sources_col.find({}).to_list(length=1000)
    return [_doc_to_source(d) for d in docs]


@router.get("/{source_id}", response_model=Source)
async def get_source(source_id: str) -> Source:
    doc = await state.sources_col.find_one({"id": source_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
    return _doc_to_source(doc)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: str) -> None:
    doc = await state.sources_col.find_one({"id": source_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
    await state.sources_col.delete_one({"id": source_id})


@router.put("/{source_id}/pause", response_model=Source)
async def pause_source(source_id: str) -> Source:
    doc = await state.sources_col.find_one({"id": source_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
    source = _doc_to_source(doc)
    source.status.state = SourceState.PAUSED
    source.updated_at = datetime.utcnow()
    updated_doc = source.model_dump()
    updated_doc["_id"] = source_id
    await state.sources_col.replace_one({"id": source_id}, updated_doc)
    return source


@router.put("/{source_id}/activate", response_model=Source)
async def activate_source(source_id: str) -> Source:
    doc = await state.sources_col.find_one({"id": source_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
    source = _doc_to_source(doc)
    source.status.state = SourceState.ACTIVE
    source.updated_at = datetime.utcnow()
    updated_doc = source.model_dump()
    updated_doc["_id"] = source_id
    await state.sources_col.replace_one({"id": source_id}, updated_doc)
    return source
