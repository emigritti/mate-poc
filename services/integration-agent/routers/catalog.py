"""
Catalog Router — list, suggest-tags, confirm-tags endpoints.

Extracted from main.py (R15).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import db
import state
from auth import require_token
from schemas import ConfirmTagsRequest, SuggestTagsResponse
from services.tag_service import extract_category_tags, suggest_tags_via_llm
from services.event_logger import record_event
from log_helpers import log_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["catalog"])


@router.get("/catalog/integrations")
async def get_catalog(
    project_id: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    accenture_ref: Optional[str] = Query(None),
) -> dict:
    """List catalog entries with optional project-level filtering."""
    items = list(state.catalog.values())

    if project_id:
        pid = project_id.upper().strip()
        items = [i for i in items if i.project_id == pid]

    if domain:
        low = domain.lower().strip()
        items = [
            i for i in items
            if (p := state.projects.get(i.project_id)) and low in p.domain.lower()
        ]

    if accenture_ref:
        low = accenture_ref.lower().strip()
        items = [
            i for i in items
            if (p := state.projects.get(i.project_id))
            and p.accenture_ref
            and low in p.accenture_ref.lower()
        ]

    result = []
    for i in items:
        d = i.model_dump()
        proj = state.projects.get(i.project_id)
        d["_project"] = {
            "client_name": proj.client_name,
            "domain": proj.domain,
            "accenture_ref": proj.accenture_ref,
        } if proj else None
        result.append(d)

    return {"status": "success", "data": result}


@router.get("/catalog/integrations/{id}/integration-spec")
async def get_integration_spec(id: str) -> dict:
    """Return the approved Integration Spec document for a catalog entry."""
    doc = state.documents.get(f"{id}-integration")
    if not doc:
        return {"status": "error", "message": "Integration Spec not approved yet or not found."}
    return {"status": "success", "data": doc.model_dump()}


@router.get("/catalog/integrations/{id}/suggest-tags")
async def suggest_tags(id: str) -> dict:
    """Propose tags for an integration from requirement categories + LLM."""
    if id not in state.catalog:
        raise HTTPException(status_code=404, detail="Integration not found.")

    entry = state.catalog[id]
    reqs = [r for r in state.parsed_requirements if r.req_id in entry.requirements]

    category_tags = extract_category_tags(reqs)

    req_text = " ".join(r.description for r in reqs)
    llm_tags = await suggest_tags_via_llm(
        entry.source.get("system", ""), entry.target.get("system", ""), req_text,
        log_fn=log_agent,
    )

    merged: list[str] = list(category_tags)
    for t in llm_tags:
        if t not in merged:
            merged.append(t)
    suggested = merged

    return SuggestTagsResponse(
        integration_id=id,
        suggested_tags=suggested,
        source={
            "from_categories": category_tags,
            "from_llm": [t for t in llm_tags if t not in category_tags],
        },
    ).model_dump()


@router.post("/catalog/integrations/{id}/confirm-tags")
async def confirm_tags(
    id: str,
    body: ConfirmTagsRequest,
    _token: str = Depends(require_token),
) -> dict:
    """Confirm integration tags and transition status to TAG_CONFIRMED."""
    if id not in state.catalog:
        raise HTTPException(status_code=404, detail="Integration not found.")

    entry = state.catalog[id]
    if entry.status != "PENDING_TAG_REVIEW":
        raise HTTPException(
            status_code=409,
            detail=f"Tags already confirmed or entry is in status '{entry.status}'.",
        )

    clean_tags = [t.strip()[:50] for t in body.tags if t.strip()]
    if not clean_tags:
        raise HTTPException(status_code=422, detail="No valid tags after stripping whitespace.")

    entry.tags = clean_tags
    entry.status = "TAG_CONFIRMED"
    if db.catalog_col is not None:
        await db.catalog_col.replace_one(
            {"id": id}, entry.model_dump(), upsert=True
        )

    await record_event("catalog.tags_confirmed", {"integration_id": id, "tags": clean_tags})

    return {
        "status": "success",
        "integration_id": id,
        "confirmed_tags": clean_tags,
    }
