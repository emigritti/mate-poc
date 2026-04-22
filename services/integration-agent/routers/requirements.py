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

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
import logging

import db
import state
from config import settings
from typing import Optional
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


def _has_subsection_headings(body: str) -> bool:
    """Return True if body contains heading level 3 or deeper (### or more).

    Documents with sub-section headings use section-based parsing regardless
    of whether they also contain bullet items (bullets are treated as content).
    """
    for line in body.splitlines():
        if re.match(r'^#{3,}\s+', line.strip()):
            return True
    return False


def _has_fr_code_structure(body: str) -> bool:
    """Return True if body has standalone **FR-code** lines or bare FR-code lines.

    FR-code lines act as requirement boundaries regardless of whether bullets
    appear in the document, so they trigger section-based parsing.
    """
    for line in body.splitlines():
        stripped = line.strip()
        # Skip actual bullet list items (- item, * item, + item) but NOT **bold** lines
        if re.match(r'^[-*+]\s+', stripped):
            continue
        bold_m = _BOLD_LINE_RE.match(stripped)
        if bold_m and _FR_CODE_RE.match(bold_m.group(1).strip()):
            return True
        if _FR_CODE_RE.match(stripped):
            return True
    return False


# Matches a line whose entire content is wrapped in **…**
_BOLD_LINE_RE = re.compile(r'^\*\*(.+?)\*\*\s*$')
# Matches FR-code identifiers (e.g. "FR-4.1", "FR‑4.O2")
_FR_CODE_RE = re.compile(r'^FR[\u2010-\u2015\u2212\-\.]\S', re.IGNORECASE)


def _normalize_doc_headings(body: str) -> str:
    """Pre-process standalone bold/FR-code lines into markdown headings.

    Two classes of lines are promoted:
    - Standalone **FR-code** lines → #### (treated as requirement-level H4)
      e.g.  **FR-4.1 – Asset Approval Event**   or   FR-4.5 – SKU Extraction
    - Other standalone **bold** lines → ### (treated as section-level H3)
      e.g.  **12. Optional Functional Requirements**

    Fenced code blocks (``` … ```) have their fence markers stripped so the
    content inside is treated as plain text rather than being parsed as headings.
    """
    result = []
    in_code_block = False
    for line in body.splitlines():
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue  # Drop the fence marker itself

        if in_code_block:
            result.append(stripped)
            continue

        bold_m = _BOLD_LINE_RE.match(stripped)
        if bold_m:
            content = bold_m.group(1).strip()
            level = "####" if _FR_CODE_RE.match(content) else "###"
            result.append(f"{level} {content}")
            continue

        # Plain (non-bold) FR-code lines that are not inside a bullet
        if _FR_CODE_RE.match(stripped) and not stripped.startswith(("-", "*", "+")):
            result.append(f"#### {stripped}")
            continue

        result.append(line)

    return "\n".join(result)


def _parse_paragraphs_as_requirements(
    body: str, source: str, target: str
) -> list[Requirement]:
    """Fallback: each blank-line-separated paragraph becomes one requirement."""
    reqs: list[Requirement] = []
    current_lines: list[str] = []

    def _flush() -> None:
        text = " ".join(current_lines).strip()
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
    """Parse a prose/section-based document into requirements.

    Pre-processing
    --------------
    Standalone **bold** lines and bare FR-code lines are promoted to markdown
    headings via _normalize_doc_headings():
      **FR-4.1 – Name**           →  #### FR-4.1 – Name   (requirement-level)
      **12. Optional Section**    →  ### 12. Optional Section  (section-level)
      FR-4.5 – Name (plain text)  →  #### FR-4.5 – Name   (requirement-level)

    Heading-level strategy
    ----------------------
    After normalisation the document may have 1, 2, or 3+ distinct heading
    levels.  The *deepest* heading level becomes the requirement boundary; the
    level immediately above it becomes the parent-section level.

    | Levels present      | Req boundary | Parent section |
    |---------------------|--------------|----------------|
    | H4 only             | H4           | —              |
    | H3 + H4             | H4           | H3             |
    | H2 + H3 + H4        | H4           | H3  (H2 = ancestor) |
    | H3 only             | H3           | —              |
    | H2 + H3             | H3           | H2             |
    | H2 only             | H2           | —              |

    Parent sections without any requirement-level children produce a single
    requirement from their aggregated content (prose + bullets).
    Empty sections (no prose, no children) are silently skipped.

    Mandatory flag is inferred from section heading text.
    """
    body = _normalize_doc_headings(body)

    # Collect (level: int|None, heading: str|None, lines: list[str])
    sections: list[tuple[int | None, str | None, list[str]]] = []
    cur_level: int | None = None
    cur_heading: str | None = None
    cur_lines: list[str] = []

    for line in body.splitlines():
        stripped = line.strip()
        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
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

    # Determine requirement boundary and parent level
    req_level = heading_levels[-1]                        # deepest = requirements
    parent_level = heading_levels[-2] if len(heading_levels) >= 2 else None
    ancestor_levels = set(heading_levels[:-2]) if len(heading_levels) >= 3 else set()

    reqs: list[Requirement] = []
    current_mandatory = False

    # Parent-section state (one level above req_level)
    cur_parent_heading: str | None = None
    cur_parent_texts: list[str] = []
    has_req_children = False          # True once a req_level section is seen under cur_parent

    # Requirement state (at req_level)
    cur_req_heading: str | None = None
    cur_req_texts: list[str] = []

    def _flush_req() -> None:
        nonlocal cur_req_heading, cur_req_texts
        if not (cur_req_heading or cur_req_texts):
            return
        description = " ".join(cur_req_texts).strip() or cur_req_heading or ""
        if description:
            reqs.append(Requirement(
                req_id=f"R-{uuid.uuid4().hex[:6].upper()}",
                source_system=source,
                target_system=target,
                category=cur_req_heading or "General",
                description=description,
                mandatory=current_mandatory,
            ))
        cur_req_heading = None
        cur_req_texts = []

    def _flush_parent_as_req() -> None:
        nonlocal cur_parent_heading, cur_parent_texts, has_req_children
        # Only emit a requirement for the parent when it had no req-level children
        if not has_req_children and (cur_parent_heading or cur_parent_texts):
            description = " ".join(cur_parent_texts).strip() or cur_parent_heading or ""
            if description:
                reqs.append(Requirement(
                    req_id=f"R-{uuid.uuid4().hex[:6].upper()}",
                    source_system=source,
                    target_system=target,
                    category=cur_parent_heading or "General",
                    description=description,
                    mandatory=current_mandatory,
                ))
        cur_parent_heading = None
        cur_parent_texts = []
        has_req_children = False

    for level, heading, lines in sections:
        if level is None:
            # Headingless prose: append to innermost active context
            if cur_req_heading is not None:
                cur_req_texts.extend(lines)
            elif cur_parent_heading is not None:
                cur_parent_texts.extend(lines)
            continue

        if level in ancestor_levels:
            # Top-most level (e.g. H2 when H2+H3+H4 exist): only sets context
            _flush_req()
            _flush_parent_as_req()
            current_mandatory = _mandatory_from_heading(heading or "")

        elif parent_level is not None and level == parent_level:
            # Section boundary: flush everything, start a new parent section
            _flush_req()
            _flush_parent_as_req()
            cur_parent_heading = heading
            cur_parent_texts = lines[:]
            has_req_children = False
            current_mandatory = _mandatory_from_heading(heading or "")

        elif level == req_level:
            # Requirement boundary
            _flush_req()
            has_req_children = True
            cur_req_heading = heading
            cur_req_texts = lines[:]

        else:
            # Deeper than req_level: fold content into current requirement
            if cur_req_heading is not None:
                if heading:
                    cur_req_texts.append(f"{heading}:")
                cur_req_texts.extend(lines)
            elif cur_parent_heading is not None:
                if heading:
                    cur_parent_texts.append(f"{heading}:")
                cur_parent_texts.extend(lines)

    _flush_req()
    _flush_parent_as_req()
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

    # Convert to pseudo-markdown and delegate to _parse_prose_requirements
    # so that the same multi-level grouping logic is reused.
    lines: list[str] = []
    for level, text in items:
        if level is None:
            lines.append(text)
        else:
            lines.append(f"{'#' * level} {text}")

    pseudo_md = "\n".join(lines)
    return _parse_prose_requirements(pseudo_md, source, target)


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
    # Section-based docs: has ### headings OR standalone **FR-code** lines
    #                     (bullets are treated as content, not requirement IDs)
    # Pure-prose docs:    no bullets at all
    # Bullet-format docs: bullets ARE the requirement identifiers
    if _has_subsection_headings(body) or _has_fr_code_structure(body) or _is_unstructured(body):
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

    # ADR-050: assign upload session ID and persist to MongoDB
    upload_id = uuid.uuid4().hex
    state.current_upload_id = upload_id
    for r in state.parsed_requirements:
        r_doc = {**r.model_dump(), "upload_id": upload_id}
        if db.requirements_col is not None:
            await db.requirements_col.replace_one(
                {"req_id": r.req_id, "upload_id": upload_id},
                r_doc,
                upsert=True,
            )

    seen: dict[str, dict] = {}
    for r in state.parsed_requirements:
        key = f"{r.source_system}|||{r.target_system}"
        if key not in seen:
            seen[key] = {"source": r.source_system, "target": r.target_system}

    fmt = "docx" if is_docx else ("prose" if is_prose else "csv")
    logger.info(
        "[UPLOAD] Parsed %d requirements from %s, %d integration pair(s) detected (upload_id=%s).",
        len(state.parsed_requirements),
        fmt,
        len(seen),
        upload_id,
    )
    return {
        "status": "parsed",
        "total_parsed": len(state.parsed_requirements),
        "preview": list(seen.values()),
        "upload_id": upload_id,
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

    # ADR-050: stamp project_id on persisted requirements and close the upload session
    if db.requirements_col is not None:
        for r in resolved:
            await db.requirements_col.update_one(
                {"req_id": r.req_id, "upload_id": state.current_upload_id},
                {"$set": {"project_id": project_id, "mandatory": r.mandatory}},
            )
    state.current_upload_id = None

    logger.info(
        "[FINALIZE] Created %d CatalogEntry(ies) under project '%s'.",
        created,
        project_id,
    )
    return {"status": "success", "integrations_created": created, "project_id": project_id}


@router.get("/requirements")
async def get_requirements(project_id: Optional[str] = Query(None)) -> dict:
    """Return requirements. With project_id queries persisted requirements for that project;
    without project_id returns the current in-memory upload session."""
    if project_id and db.requirements_col is not None:
        pid = project_id.upper().strip()
        docs = [doc async for doc in db.requirements_col.find({"project_id": pid}, {"_id": 0})]
        return {"status": "success", "data": docs}
    if project_id:
        # requirements_col unavailable (degraded mode)
        return {"status": "success", "data": []}
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
            # ADR-050: sync to MongoDB
            if db.requirements_col is not None:
                await db.requirements_col.update_one(
                    {"req_id": req_id},
                    {"$set": {"mandatory": mandatory}},
                )
            logger.info("[PATCH] Requirement '%s' mandatory set to %s.", req_id, mandatory)
            return {"status": "success", "req_id": req_id, "mandatory": mandatory}
    raise HTTPException(status_code=404, detail=f"Requirement '{req_id}' not found.")
