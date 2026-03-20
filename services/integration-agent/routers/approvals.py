"""
Approvals Router — HITL approve/reject endpoints.

Extracted from main.py (R15).
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

import db
import state
from auth import require_token
from output_guard import sanitize_human_content
from schemas import ApproveRequest, Document, RejectRequest
from utils import _now_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["approvals"])


@router.get("/approvals/pending")
async def get_pending_approvals() -> dict:
    pending = [a.model_dump() for a in state.approvals.values() if a.status == "PENDING"]
    return {"status": "success", "data": pending}


@router.post("/approvals/{id}/approve")
async def approve_doc(
    id: str,
    body: ApproveRequest,
    _token: str = Depends(require_token),
) -> dict:
    """
    Approve a pending document.

    ADR-023: ChromaDB write removed. Approved documents are staged in MongoDB
             with kb_status='staged'. Use POST /api/v1/documents/{id}/promote-to-kb
             to promote to the RAG Knowledge Base.
    """
    if id not in state.approvals:
        raise HTTPException(status_code=404, detail="Approval not found.")

    app_entry = state.approvals[id]
    if app_entry.status == "APPROVED":
        raise HTTPException(status_code=409, detail="Document already approved.")

    safe_md = sanitize_human_content(body.final_markdown)

    app_entry.status  = "APPROVED"
    app_entry.content = safe_md
    if db.approvals_col is not None:
        await db.approvals_col.replace_one(
            {"id": id}, app_entry.model_dump(), upsert=True
        )

    doc_id = f"{app_entry.integration_id}-{app_entry.doc_type}"
    doc = Document(
        id=doc_id,
        integration_id=app_entry.integration_id,
        doc_type=app_entry.doc_type,
        content=safe_md,
        generated_at=_now_iso(),
        kb_status="staged",
    )
    state.documents[doc_id] = doc
    if db.documents_col is not None:
        await db.documents_col.replace_one(
            {"id": doc_id}, doc.model_dump(), upsert=True
        )

    return {"status": "success", "message": "Approved and staged. Use 'Promote to KB' to add to RAG."}


@router.post("/approvals/{id}/reject")
async def reject_doc(
    id: str,
    body: RejectRequest,
    _token: str = Depends(require_token),
) -> dict:
    """Reject a pending document."""
    if id not in state.approvals:
        raise HTTPException(status_code=404, detail="Approval not found.")

    if state.approvals[id].status != "PENDING":
        raise HTTPException(
            status_code=409,
            detail=f"Only PENDING approvals can be rejected (current: {state.approvals[id].status}).",
        )

    state.approvals[id].status   = "REJECTED"
    state.approvals[id].feedback = body.feedback
    if db.approvals_col is not None:
        await db.approvals_col.replace_one(
            {"id": id}, state.approvals[id].model_dump(), upsert=True
        )

    return {"status": "success", "message": "Rejected. Feedback stored for agent retry context."}
