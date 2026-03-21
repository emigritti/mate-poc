"""
Documents Router — list documents, promote to KB.

Extracted from main.py (R15).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

import db
import state
from auth import require_token
from schemas import Document
from services.event_logger import record_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["documents"])


@router.get("/documents", response_model=list[Document])
async def list_documents(_user: str = Depends(require_token)):
    """Return all approved documents with their KB promotion status."""
    return list(state.documents.values())


@router.post("/documents/{doc_id}/promote-to-kb")
async def promote_document_to_kb(doc_id: str, _user: str = Depends(require_token)):
    """Promote a staged document to the RAG Knowledge Base (ChromaDB)."""
    doc = state.documents.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found.")

    if doc.kb_status == "promoted":
        raise HTTPException(
            status_code=409,
            detail=f"Document '{doc_id}' is already promoted to the Knowledge Base.",
        )

    if state.collection is not None:
        try:
            cat_entry = state.catalog.get(doc.integration_id)
            tags_csv = ",".join(cat_entry.tags) if cat_entry else ""
            state.collection.upsert(
                documents=[doc.content],
                metadatas=[{
                    "integration_id": doc.integration_id,
                    "type": doc.doc_type,
                    "tags_csv": tags_csv,
                }],
                ids=[doc_id],
            )
            logger.info("[RAG] Promoted %s to ChromaDB (tags: %s).", doc_id, tags_csv)
        except Exception as exc:
            logger.warning("[RAG] ChromaDB promote failed for %s: %s", doc_id, exc)
            raise HTTPException(
                status_code=500,
                detail=f"ChromaDB write failed: {exc}",
            )
    else:
        logger.warning("[RAG] ChromaDB unavailable — cannot promote %s.", doc_id)
        raise HTTPException(
            status_code=503,
            detail="ChromaDB is unavailable. Cannot promote document to Knowledge Base.",
        )

    doc.kb_status = "promoted"
    state.documents[doc_id] = doc
    if db.documents_col is not None:
        await db.documents_col.update_one(
            {"id": doc_id},
            {"$set": {"kb_status": "promoted"}},
        )

    await record_event("document.promoted", {"doc_id": doc_id})

    return {
        "status": "success",
        "doc_id": doc_id,
        "message": f"Document '{doc_id}' promoted to Knowledge Base.",
    }
