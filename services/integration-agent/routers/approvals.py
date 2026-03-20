"""
Approvals Router — HITL approve/reject endpoints.

Extracted from main.py (R15).
"""

import logging
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException

import db
import state
from auth import require_token
from output_guard import sanitize_human_content, LLMOutputValidationError
from schemas import Approval, ApproveRequest, Document, RejectRequest
from services.agent_service import generate_integration_doc
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


@router.post("/approvals/{id}/regenerate")
async def regenerate_doc(
    id: str,
    _token: str = Depends(require_token),
) -> dict:
    """
    Regenerate a REJECTED document using stored reviewer feedback.

    R16: Creates a new PENDING Approval for the same integration, with the
    rejection feedback injected into the prompt via build_prompt(reviewer_feedback=...).

    Raises:
        404: Approval not found.
        409: Approval is not REJECTED, or has no feedback stored.
        422: Regenerated output failed the structural output guard.
        503: LLM unavailable during regeneration.
    """
    if id not in state.approvals:
        raise HTTPException(status_code=404, detail="Approval not found.")

    app_entry = state.approvals[id]
    if app_entry.status != "REJECTED":
        raise HTTPException(
            status_code=409,
            detail=f"Only REJECTED approvals can be regenerated (current: {app_entry.status}).",
        )
    if not app_entry.feedback:
        raise HTTPException(
            status_code=409,
            detail="Cannot regenerate: no rejection feedback stored for this approval.",
        )

    entry = state.catalog.get(app_entry.integration_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"Catalog entry '{app_entry.integration_id}' not found — cannot regenerate.",
        )
    requirements = [r for r in state.parsed_requirements if r.req_id in entry.requirements]

    try:
        new_content = await generate_integration_doc(
            entry=entry,
            requirements=requirements,
            reviewer_feedback=app_entry.feedback,
            log_fn=logger.info,
        )
    except LLMOutputValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Regenerated output failed structural guard: {exc}",
        )
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"LLM unavailable during regeneration: {exc}",
        )

    new_id = f"APP-{uuid.uuid4().hex[:6].upper()}"
    new_approval = Approval(
        id=new_id,
        integration_id=app_entry.integration_id,
        doc_type=app_entry.doc_type,
        content=new_content,
        status="PENDING",
        generated_at=_now_iso(),
    )
    state.approvals[new_id] = new_approval
    if db.approvals_col is not None:
        await db.approvals_col.replace_one(
            {"id": new_id}, new_approval.model_dump(), upsert=True
        )

    logger.info(
        "[REGEN] New approval %s created from rejected %s (feedback: %d chars)",
        new_id, id, len(app_entry.feedback),
    )
    return {
        "status": "success",
        "message": f"Regenerated from feedback. New approval {new_id} is PENDING.",
        "data": {"new_approval_id": new_id, "previous_approval_id": id},
    }
