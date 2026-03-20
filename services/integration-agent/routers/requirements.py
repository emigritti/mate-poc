"""
Requirements Router — upload, finalize, list endpoints.

Extracted from main.py (R15).
"""

import csv
import io
import re
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
import logging

import db
import state
from config import settings
from schemas import CatalogEntry, FinalizeRequirementsRequest, Requirement
from log_helpers import log_agent
from utils import _now_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["requirements"])

# ── Constants ─────────────────────────────────────────────────────────────────
_ALLOWED_CSV_MIME = frozenset({
    "text/csv", "application/csv", "text/plain", "application/vnd.ms-excel",
})
_CSV_MAX_BYTES = 1_048_576  # 1 MB


@router.post("/requirements/upload")
async def upload_requirements(file: UploadFile = File(...)) -> dict:
    """Parse a CSV file of integration requirements."""
    if file.content_type not in _ALLOWED_CSV_MIME:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported media type '{file.content_type}'. Only CSV files accepted.",
        )

    content = await file.read()

    if len(content) > _CSV_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the 1 MB limit ({len(content):,} bytes received).",
        )

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.")

    reader = csv.DictReader(io.StringIO(text))
    state.parsed_requirements.clear()
    for row in reader:
        req = Requirement(
            req_id=row.get("ReqID", f"R-{uuid.uuid4().hex[:6]}"),
            source_system=row.get("Source", "Unknown"),
            target_system=row.get("Target", "Unknown"),
            category=row.get("Category", "Sync"),
            description=row.get("Description", ""),
        )
        state.parsed_requirements.append(req)

    seen: dict[str, dict] = {}
    for r in state.parsed_requirements:
        key = f"{r.source_system}|||{r.target_system}"
        if key not in seen:
            seen[key] = {"source": r.source_system, "target": r.target_system}

    logger.info(
        "[UPLOAD] Parsed %d requirements, %d integration pair(s) detected.",
        len(state.parsed_requirements),
        len(seen),
    )
    return {
        "status": "parsed",
        "total_parsed": len(state.parsed_requirements),
        "preview": list(seen.values()),
    }


@router.post("/requirements/finalize")
async def finalize_requirements(body: FinalizeRequirementsRequest) -> dict:
    """Create CatalogEntries for the current parsed_requirements under a given project."""
    if not state.parsed_requirements:
        raise HTTPException(
            status_code=400,
            detail="No parsed requirements in memory. Upload a CSV first.",
        )

    project_id = body.project_id.upper().strip()
    project = state.projects.get(project_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{project_id}' not found. Create it first via POST /api/v1/projects.",
        )

    groups: dict[str, list[Requirement]] = {}
    for r in state.parsed_requirements:
        key = f"{r.source_system}|||{r.target_system}"
        groups.setdefault(key, []).append(r)

    created = 0
    for _key, reqs in groups.items():
        source = reqs[0].source_system
        target = reqs[0].target_system
        entry_id = f"{project_id}-{uuid.uuid4().hex[:6].upper()}"
        entry = CatalogEntry(
            id=entry_id,
            name=f"{source} to {target} Integration",
            type="Auto-discovered",
            source={"system": source},
            target={"system": target},
            requirements=[r.req_id for r in reqs],
            status="PENDING_TAG_REVIEW",
            tags=[],
            project_id=project_id,
            created_at=_now_iso(),
        )
        state.catalog[entry_id] = entry
        if db.catalog_col is not None:
            await db.catalog_col.replace_one(
                {"id": entry_id}, entry.model_dump(), upsert=True
            )
        created += 1

    logger.info(
        "[FINALIZE] Created %d CatalogEntry(ies) under project '%s'.",
        created,
        project_id,
    )
    return {"status": "success", "integrations_created": created, "project_id": project_id}


@router.get("/requirements")
async def get_requirements() -> dict:
    return {"status": "success", "data": [r.model_dump() for r in state.parsed_requirements]}
