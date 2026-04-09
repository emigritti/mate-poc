"""
Requirements Router — upload, finalize, list endpoints.

Extracted from main.py (R15).
Supports CSV and Markdown (.md) requirement files.
"""

import csv
import io
import re
import uuid

from fastapi import APIRouter, Body, File, HTTPException, UploadFile
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
    "text/markdown", "text/x-markdown",
})
_MAX_BYTES = 1_048_576  # 1 MB


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_csv(text: str) -> list[Requirement]:
    reader = csv.DictReader(io.StringIO(text))
    reqs = []
    for row in reader:
        reqs.append(Requirement(
            req_id=row.get("ReqID", f"R-{uuid.uuid4().hex[:6].upper()}"),
            source_system=row.get("Source", "Unknown"),
            target_system=row.get("Target", "Unknown"),
            category=row.get("Category", "Sync"),
            description=row.get("Description", ""),
            mandatory=str(row.get("Mandatory", "")).strip().lower() in ("true", "yes", "1"),
        ))
    return reqs


def _parse_markdown(text: str, filename: str = "unknown.md") -> list[Requirement]:
    """Parse a Markdown integration requirements file into Requirement objects.

    Expected format:
        ---
        source: ERP
        target: Salsify
        ---

        ## Mandatory Requirements
        - REQ-M01 | Product Collection | Sync daily articles from ERP to PLM

        ## Non-Mandatory Requirements
        - REQ-O01 | Reporting | Generate weekly sync status report

    Rules:
    - YAML frontmatter (---...---) provides source/target.
      Fallback: filename stem split on "-to-", "→", or "->".
    - Section heading containing "mandatory" but NOT "non" → mandatory=True.
    - Bullet items: [REQ-ID |] [Category |] Description  (1–3 pipe parts).
    """
    source, target = "Unknown", "Unknown"

    # ── Extract YAML frontmatter ──────────────────────────────────────────────
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n?', text, re.DOTALL)
    body = text[fm_match.end():] if fm_match else text

    if fm_match:
        fm = fm_match.group(1)
        m = re.search(r'^source:\s*(.+)$', fm, re.MULTILINE | re.IGNORECASE)
        if m:
            source = m.group(1).strip()
        m = re.search(r'^target:\s*(.+)$', fm, re.MULTILINE | re.IGNORECASE)
        if m:
            target = m.group(1).strip()
    else:
        # Fallback: parse "erp-to-salsify.md" or "erp→salsify.md"
        stem = re.sub(r'\.md$', '', filename, flags=re.IGNORECASE)
        parts = re.split(r'\s*-to-\s*|\s*→\s*|\s*->\s*', stem, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2:
            source, target = parts[0].strip(), parts[1].strip()

    # ── Parse sections + bullet items ─────────────────────────────────────────
    reqs = []
    current_mandatory = False

    for line in body.splitlines():
        stripped = line.strip()

        # Section heading detection
        heading = re.match(r'^#{1,4}\s+(.+)$', stripped)
        if heading:
            h = heading.group(1).lower()
            is_non = bool(re.search(r'\bnon[-\s]?mandatory\b|\boptional\b', h))
            current_mandatory = bool(re.search(r'\bmandatory\b', h)) and not is_non
            continue

        # Bullet item detection
        bullet = re.match(r'^[-*+]\s+(.+)$', stripped)
        if not bullet:
            continue

        item = bullet.group(1).strip()
        parts = [p.strip() for p in item.split('|')]

        if len(parts) >= 3:
            req_id, category, description = parts[0], parts[1], '|'.join(parts[2:]).strip()
        elif len(parts) == 2:
            req_id = f"R-{uuid.uuid4().hex[:6].upper()}"
            category, description = parts[0], parts[1]
        else:
            req_id = f"R-{uuid.uuid4().hex[:6].upper()}"
            category = "General"
            description = parts[0]

        if not req_id:
            req_id = f"R-{uuid.uuid4().hex[:6].upper()}"

        reqs.append(Requirement(
            req_id=req_id,
            source_system=source,
            target_system=target,
            category=category,
            description=description,
            mandatory=current_mandatory,
        ))

    return reqs


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/requirements/upload")
async def upload_requirements(file: UploadFile = File(...)) -> dict:
    """Parse a CSV or Markdown file of integration requirements."""
    filename = file.filename or ""
    is_markdown = filename.lower().endswith(".md")

    if not is_markdown and file.content_type not in _ALLOWED_CSV_MIME:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported media type '{file.content_type}'. "
                "Only CSV (.csv) and Markdown (.md) files are accepted."
            ),
        )

    content = await file.read()

    if len(content) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the 1 MB limit ({len(content):,} bytes received).",
        )

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")

    state.parsed_requirements.clear()

    if is_markdown:
        state.parsed_requirements.extend(_parse_markdown(text, filename))
    else:
        state.parsed_requirements.extend(_parse_csv(text))

    seen: dict[str, dict] = {}
    for r in state.parsed_requirements:
        key = f"{r.source_system}|||{r.target_system}"
        if key not in seen:
            seen[key] = {"source": r.source_system, "target": r.target_system}

    logger.info(
        "[UPLOAD] Parsed %d requirements from %s, %d integration pair(s) detected.",
        len(state.parsed_requirements),
        "markdown" if is_markdown else "CSV",
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
            detail="No parsed requirements in memory. Upload a CSV or Markdown file first.",
        )

    project_id = body.project_id.upper().strip()
    project = state.projects.get(project_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{project_id}' not found. Create it first via POST /api/v1/projects.",
        )

    # Apply user-supplied field overrides (source/target corrections from the UI modal)
    overrides = body.field_overrides or {}
    resolved: list[Requirement] = []
    for r in state.parsed_requirements:
        ov = overrides.get(r.req_id, {})
        updates = {
            k: v for k, v in ov.items()
            if k in ("source_system", "target_system") and v and v.strip()
        }
        resolved.append(r.model_copy(update=updates) if updates else r)

    # Persist corrected values back into state so GET /requirements reflects them
    for i, r in enumerate(resolved):
        state.parsed_requirements[i] = r

    groups: dict[str, list[Requirement]] = {}
    for r in resolved:
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


@router.patch("/requirements/{req_id}")
async def patch_requirement(
    req_id: str,
    mandatory: bool = Body(..., embed=True),
) -> dict:
    """Toggle the mandatory flag on an in-memory parsed requirement."""
    for i, r in enumerate(state.parsed_requirements):
        if r.req_id == req_id:
            state.parsed_requirements[i] = r.model_copy(update={"mandatory": mandatory})
            logger.info("[PATCH] Requirement '%s' mandatory set to %s.", req_id, mandatory)
            return {"status": "success", "req_id": req_id, "mandatory": mandatory}
    raise HTTPException(status_code=404, detail=f"Requirement '{req_id}' not found.")
