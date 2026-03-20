"""
Projects Router — CRUD for client projects (ADR-025).

Extracted from main.py (R15).
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

import db
import state
from auth import require_token
from schemas import Project, ProjectCreateRequest
from utils import _now_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["projects"])


@router.post("/projects")
async def create_project(
    body: ProjectCreateRequest,
    _token: str = Depends(require_token),
) -> dict:
    """Create a new project or return existing if prefix + client_name match."""
    prefix = body.prefix.upper().strip()
    existing = state.projects.get(prefix)
    if existing:
        if existing.client_name.lower() == body.client_name.lower():
            return {"status": "ok", "data": existing.model_dump()}
        raise HTTPException(
            status_code=409,
            detail=f"Prefix '{prefix}' already used by project '{existing.client_name}'.",
        )

    project = Project(
        prefix=prefix,
        client_name=body.client_name,
        domain=body.domain,
        description=body.description,
        accenture_ref=body.accenture_ref,
        created_at=_now_iso(),
    )
    state.projects[prefix] = project
    if db.projects_col is not None:
        await db.projects_col.replace_one(
            {"prefix": prefix}, project.model_dump(), upsert=True
        )
    logger.info("[PROJECT] Created project '%s' for client '%s'.", prefix, project.client_name)
    return {"status": "created", "data": project.model_dump()}


@router.get("/projects")
async def list_projects() -> dict:
    return {"status": "success", "data": [p.model_dump() for p in state.projects.values()]}


@router.get("/projects/{prefix}")
async def get_project(prefix: str) -> dict:
    prefix = prefix.upper().strip()
    project = state.projects.get(prefix)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{prefix}' not found.")
    return {"status": "success", "data": project.model_dump()}
