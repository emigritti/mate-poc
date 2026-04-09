"""
Requirements Router — upload, finalize, list endpoints.

Extracted from main.py (R15).
Supports CSV (.csv), Markdown (.md), plain text (.txt), and Word (.docx) files.

Unstructured documents (prose, no bullet lists) are parsed by grouping content
at the first sub-heading level:
  - H1 + H2 present → each H2 section = one requirement
  - Only H1 (or no headings) → each H1 section (or paragraph) = one requirement
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
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_MAX_BYTES = 1_048_576  # 1 MB


# ── Parsers ───────────────────────────────────────────────────────────────────

def _mandatory_from_heading(heading: str) -> bool:
    """Return True if a heading signals mandatory requirements."""
    h = heading.lower()
    is_non = bool(re.search(r'\bnon[-\s]?mandatory\b|\boptional\b', h))
    return bool(re.search(r'\bmandatory\b', h)) and not is_non


def _is_unstructured(body: str) -> bool:
    """Return True if body contains no bullet items (purely prose document)."""
    for line in body.splitlines():
        if re.match(r'^[-*+]\s+', line.strip()):
            return False
    return True


def _parse_paragraphs_as_requirements(
    body: str, source: str, target: str
) -> list[Requirement]:
    """Fallback: each blank-line-separated paragraph becomes one requirement."""
    reqs: list[Requirement] = []
    current_lines: list[str] = []

    def _flush() -> None:
        text = ' '.join(current_lines).strip()
        if text:
            reqs.append(Requirement(
                req_id=f"R-{uuid.uuid4().hex[:6].upper()}",
                source_system=source,
                target_system=target,
                category="General",
                description=text,
                mandatory=False,
            ))
        current_lines.clear()

    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            current_lines.append(stripped)
        else:
            _flush()

    _flush()
    return reqs


def _parse_prose_requirements(
    body: str, source: str, target: str
) -> list[Requirement]:
    """Parse a prose (non-bullet) markdown/text document into requirements.

    Groups content at the first sub-heading level:
    - H1 + H2 in document → each H2 section = one requirement
    - Only H1 → each H1 section = one requirement
    - No headings → each paragraph (blank-line-separated) = one requirement

    The heading text becomes the requirement category; all accumulated text
    under that heading (including deeper sub-headings) becomes the description.
    The mandatory flag is inferred from the parent section heading.
    """
    # Collect (level: int|None, heading: str|None, lines: list[str])
    sections: list[tuple[int | None, str | None, list[str]]] = []
    cur_level: int | None = None
    cur_heading: str | None = None
    cur_lines: list[str] = []

    for line in body.splitlines():
        stripped = line.strip()
        m = re.match(r'^(#{1,4})\s+(.+)$', stripped)
        if m:
            if cur_heading is not None or cur_lines:
                sections.append((cur_level, cur_heading, cur_lines))
            cur_level = len(m.group(1))
            cur_heading = m.group(2).strip()
            cur_lines = []
        elif stripped:
            cur_lines.append(stripped)

    if cur_heading is not None or cur_lines:
        sections.append((cur_level, cur_heading, cur_lines))

    if not sections:
        return []

    heading_levels = sorted(set(s[0] for s in sections if s[0] is not None))
    if not heading_levels:
        return _parse_paragraphs_as_requirements(body, source, target)

    min_level = heading_levels[0]
    # Use first sub-level if it exists, otherwise use the top level
    target_level = heading_levels[1] if len(heading_levels) > 1 else min_level

    reqs: list[Requirement] = []
    current_mandatory = False
    req_heading: str | None = None
    req_texts: list[str] = []

    def _flush() -> None:
        nonlocal req_heading, req_texts
        if not (req_heading or req_texts):
            return
        description = ' '.join(req_texts).strip() or req_heading or ""
        if description:
            reqs.append(Requirement(
                req_id=f"R-{uuid.uuid4().hex[:6].upper()}",
                source_system=source,
                target_system=target,
                category=req_heading or "General",
                description=description,
                mandatory=current_mandatory,
            ))
        req_heading = None
        req_texts = []

    for level, heading, lines in sections:
        if level is None:
            if req_heading is not None:
                req_texts.extend(lines)
            continue

        if level < target_level:
            # Parent section: sets mandatory flag; is NOT itself a requirement
            _flush()
            current_mandatory = _mandatory_from_heading(heading or "")
        elif level == target_level:
            _flush()
            req_heading = heading
            req_texts = lines[:]
        else:
            # Deeper sub-section: fold into current requirement
            if req_heading is not None:
                if heading:
                    req_texts.append(f"{heading}:")
                req_texts.extend(lines)
            else:
                req_heading = heading
                req_texts = lines[:]

    _flush()
    return reqs


def _parse_docx_requirements(data: bytes) -> list[Requirement]:
    """Parse a Word (.docx) document into requirements.

    Uses paragraph heading styles (Heading 1, Heading 2, …) to determine
    structure, then applies the same grouping logic as _parse_prose_requirements:
    - Heading 1 + Heading 2 → each Heading 2 section = one requirement
    - Only Heading 1 → each Heading 1 section = one requirement
    - No headings → each paragraph = one requirement

    Source/target default to "Unknown" (user fills them via the validation modal).
    """
    try:
        from docx import Document as DocxDocument
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="python-docx is required to parse .docx files.",
        ) from exc

    doc = DocxDocument(io.BytesIO(data))
    source, target = "Unknown", "Unknown"

    # Collect (level: int|None, text: str)
    items: list[tuple[int | None, str]] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style_name = (para.style.name or "").lower() if para.style else ""
        m = re.match(r'heading\s+(\d+)', style_name)
        items.append((int(m.group(1)) if m else None, text))

    if not items:
        return []

    heading_levels = sorted(set(lv for lv, _ in items if lv is not None))
    if not heading_levels:
        # No heading styles: each paragraph = one requirement
        return [
            Requirement(
                req_id=f"R-{uuid.uuid4().hex[:6].upper()}",
                source_system=source,
                target_system=target,
                category="General",
                description=text,
                mandatory=False,
            )
            for _, text in items
        ]

    min_level = heading_levels[0]
    target_level = heading_levels[1] if len(heading_levels) > 1 else min_level

    reqs: list[Requirement] = []
    current_mandatory = False
    req_heading: str | None = None
    req_texts: list[str] = []

    def _flush() -> None:
        nonlocal req_heading, req_texts
        if not (req_heading or req_texts):
            return
        description = ' '.join(req_texts).strip() or req_heading or ""
        if description:
            reqs.append(Requirement(
                req_id=f"R-{uuid.uuid4().hex[:6].upper()}",
                source_system=source,
                target_system=target,
                category=req_heading or "General",
                description=description,
                mandatory=current_mandatory,
            ))
        req_heading = None
        req_texts = []

    for level, text in items:
        if level is None:
            if req_heading is not None:
                req_texts.append(text)
            continue

        if level < target_level:
            _flush()
            current_mandatory = _mandatory_from_heading(text)
        elif level == target_level:
            _flush()
            req_heading = text
        else:
            if req_heading is not None:
                req_texts.append(f"{text}:")
            else:
                req_heading = text

    _flush()
    return reqs


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
    """Parse a Markdown (or plain-text) requirements file into Requirement objects.

    Structured mode (file contains bullet items):
        ---
        source: ERP
        target: Salsify
        ---
        ## Mandatory Requirements
        - REQ-M01 | Product Collection | Sync daily articles from ERP to PLM
        ## Non-Mandatory Requirements
        - REQ-O01 | Reporting | Generate weekly sync status report

    Unstructured mode (no bullet items — prose document):
        Paragraphs grouped at the first sub-heading level.  Each H2 (or H1 if
        no H2 exists) section becomes one requirement with the heading as
        category and the accumulated prose as description.

    Rules (both modes):
    - YAML frontmatter (---...---) provides source/target.
      Fallback: filename stem split on "-to-", "→", or "->".
    - Section heading containing "mandatory" but NOT "non" → mandatory=True.
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
        stem = re.sub(r'\.(md|txt)$', '', filename, flags=re.IGNORECASE)
        parts = re.split(r'\s*-to-\s*|\s*→\s*|\s*->\s*', stem, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2:
            source, target = parts[0].strip(), parts[1].strip()

    # ── Route to appropriate parser ───────────────────────────────────────────
    if _is_unstructured(body):
        return _parse_prose_requirements(body, source, target)

    # ── Structured: parse sections + bullet items ─────────────────────────────
    reqs = []
    current_mandatory = False

    for line in body.splitlines():
        stripped = line.strip()

        # Section heading detection
        heading = re.match(r'^#{1,4}\s+(.+)$', stripped)
        if heading:
            current_mandatory = _mandatory_from_heading(heading.group(1))
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
    """Parse a CSV, Markdown, plain-text, or Word document of integration requirements."""
    filename = file.filename or ""
    lower = filename.lower()
    is_prose = lower.endswith(".md") or lower.endswith(".txt")
    is_docx = lower.endswith(".docx")

    if not is_prose and not is_docx and file.content_type not in _ALLOWED_CSV_MIME:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported media type '{file.content_type}'. "
                "Accepted formats: CSV (.csv), Markdown (.md), "
                "plain text (.txt), Word (.docx)."
            ),
        )

    content = await file.read()

    if len(content) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the 1 MB limit ({len(content):,} bytes received).",
        )

    state.parsed_requirements.clear()

    if is_docx:
        state.parsed_requirements.extend(_parse_docx_requirements(content))
    elif is_prose:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")
        state.parsed_requirements.extend(_parse_markdown(text, filename))
    else:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")
        state.parsed_requirements.extend(_parse_csv(text))

    seen: dict[str, dict] = {}
    for r in state.parsed_requirements:
        key = f"{r.source_system}|||{r.target_system}"
        if key not in seen:
            seen[key] = {"source": r.source_system, "target": r.target_system}

    fmt = "docx" if is_docx else ("prose" if is_prose else "csv")
    logger.info(
        "[UPLOAD] Parsed %d requirements from %s, %d integration pair(s) detected.",
        len(state.parsed_requirements),
        fmt,
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
