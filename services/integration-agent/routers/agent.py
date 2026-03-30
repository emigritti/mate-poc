"""
Agent Router — trigger, cancel, logs endpoints.

Extracted from main.py (R15).
Uses generate_with_retry (R13) for LLM calls with exponential backoff.
"""

import asyncio
import logging
import uuid
import httpx
from fastapi import APIRouter, Depends, HTTPException

import db
import state
from auth import require_token
from utils import _now_iso
from config import settings
from log_helpers import log_agent
from output_guard import LLMOutputValidationError, assess_quality
from schemas import Approval, LogEntry
from services.agent_service import generate_integration_doc, generate_technical_doc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["agent"])


# ── Agentic RAG flow ──────────────────────────────────────────────────────────

async def run_agentic_rag_flow() -> None:
    """
    Core agentic loop: read TAG_CONFIRMED catalog entries → RAG → LLM → guard → HITL queue.

    Now uses generate_with_retry (R13) for resilient LLM calls.
    """
    confirmed = [e for e in state.catalog.values() if e.status == "TAG_CONFIRMED"]
    total = len(confirmed)
    log_agent(f"Processing {total} TAG_CONFIRMED integration(s)...")

    # R18: initialise progress tracking
    state.agent_progress = {}
    state.agent_progress["overall"] = {"step": "Starting", "done": 0, "total": total}

    for idx, entry in enumerate(confirmed, start=1):
        source = entry.source.get("system", "Unknown")
        target = entry.target.get("system", "Unknown")
        reqs = [r for r in state.parsed_requirements if r.req_id in entry.requirements]

        log_agent(
            f"[STEP {idx}/{total}] {entry.id} — {source} → {target} "
            f"({len(reqs)} requirement(s), tags: {entry.tags})"
        )

        # R18: update progress for this integration
        state.agent_progress["overall"] = {
            "step": f"Processing {idx}/{total}: {entry.id}",
            "done": idx - 1,
            "total": total,
        }

        # Update status to PROCESSING
        entry.status = "PROCESSING"
        if db.catalog_col is not None:
            await db.catalog_col.replace_one(
                {"id": entry.id}, entry.model_dump(), upsert=True
            )
        log_agent(f"Processing entry: {entry.id} ({entry.name}) -- {len(reqs)} reqs.")

        # 1–4. RAG retrieval + LLM generation (extracted to agent_service.py for reuse by regenerate endpoint)
        query_text = " ".join(r.description for r in reqs)
        try:
            func_content = await generate_integration_doc(
                entry=entry,
                requirements=reqs,
                reviewer_feedback="",
                log_fn=log_agent,
            )
            log_agent(
                f"[LLM] Spec generated and sanitized for {entry.id} — "
                f"{len(func_content)} chars."
            )
            # R14: non-destructive quality assessment
            quality = assess_quality(func_content)
            if not quality.passed:
                log_agent(
                    f"[QUALITY] Low quality score {quality.quality_score:.2f} for {entry.id}"
                    f" — {'; '.join(quality.issues)}"
                )
            else:
                log_agent(f"[QUALITY] Quality OK — score {quality.quality_score:.2f} for {entry.id}")
        except LLMOutputValidationError as exc:
            preview = (raw if 'raw' in dir() else "")[:120].replace("\n", " ")
            log_agent(f"[GUARD] Output rejected for {entry.id}: {exc}")
            func_content = "[LLM_OUTPUT_REJECTED: structural guard failed -- see agent logs]"
        except Exception as exc:
            exc_type = type(exc).__name__
            if isinstance(exc, httpx.TimeoutException):
                detail = (
                    f"timeout after {settings.ollama_timeout_seconds}s "
                    f"(all retries exhausted) — "
                    "increase OLLAMA_TIMEOUT_SECONDS or switch to a smaller model"
                )
            elif isinstance(exc, httpx.ConnectError):
                detail = (
                    f"cannot reach Ollama at {settings.ollama_host} "
                    f"(all retries exhausted) — "
                    "is the ollama container running?"
                )
            elif isinstance(exc, httpx.HTTPStatusError):
                detail = f"Ollama returned HTTP {exc.response.status_code}"
            else:
                detail = str(exc) if str(exc) else exc_type
            log_agent(f"[ERROR] LLM generation failed for {entry.id} — {exc_type}: {detail}")
            func_content = "[LLM_UNAVAILABLE: generation failed — see agent logs for details]"

        # 5. Create HITL Approval entry
        app_id = f"APP-{uuid.uuid4().hex[:6].upper()}"
        approval = Approval(
            id=app_id,
            integration_id=entry.id,
            doc_type="functional",
            content=func_content,
            status="PENDING",
            generated_at=_now_iso(),
        )
        state.approvals[app_id] = approval
        if db.approvals_col is not None:
            await db.approvals_col.replace_one(
                {"id": app_id}, approval.model_dump(), upsert=True
            )
        log_agent(f"Approval {app_id} queued for HITL review.")

        # Update CatalogEntry status to DONE
        entry.status = "DONE"
        if db.catalog_col is not None:
            await db.catalog_col.replace_one(
                {"id": entry.id}, entry.model_dump(), upsert=True
            )

    # R18: mark progress as complete
    state.agent_progress["overall"] = {
        "step": "Completed",
        "done": total,
        "total": total,
    }
    log_agent("Generation completed. Pending documents are waiting for HITL approval.")


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/agent/trigger")
async def trigger_agent(
    _token: str = Depends(require_token),
) -> dict:
    """
    Trigger the Agentic RAG flow asynchronously.

    Guarded by:
      - require_token (G-10)
      - asyncio.Lock — prevents concurrent runs (F-09)
    """
    if not state.parsed_requirements:
        raise HTTPException(
            status_code=400, detail="No requirements loaded. Upload a CSV first."
        )

    if state.agent_lock.locked():
        raise HTTPException(
            status_code=409, detail="Agent is already running. Wait for it to finish."
        )

    # Gate: all catalog entries must have confirmed tags before generation
    pending_tag_review = [
        e.id for e in state.catalog.values() if e.status == "PENDING_TAG_REVIEW"
    ]
    if pending_tag_review:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(pending_tag_review)} integration(s) are awaiting tag confirmation. "
                f"Confirm tags before triggering generation."
            ),
        )

    state.agent_logs.clear()
    log_agent("Started Agent Processing Task")

    task_id = uuid.uuid4().hex[:8].upper()

    async def _guarded_flow() -> None:
        async with state.agent_lock:
            await run_agentic_rag_flow()

    task = asyncio.create_task(_guarded_flow(), name=task_id)
    state.running_tasks[task_id] = task
    task.add_done_callback(
        lambda t: state.running_tasks.pop(t.get_name(), None)
    )

    return {"status": "started", "task_id": task_id}


@router.post("/agent/cancel")
async def cancel_agent(
    _token: str = Depends(require_token),
) -> dict:
    """Cancel the currently running agent task."""
    if not state.agent_lock.locked():
        raise HTTPException(status_code=409, detail="No agent is currently running.")

    cancelled = 0
    for task in list(state.running_tasks.values()):
        task.cancel()
        cancelled += 1

    log_agent("⛔ Agent execution cancelled by user request.")
    return {"status": "success", "message": f"Cancel signal sent to {cancelled} task(s)."}


@router.post("/agent/trigger-technical/{integration_id}")
async def trigger_technical(
    integration_id: str,
    _token: str = Depends(require_token),
) -> dict:
    """
    Trigger technical design generation for a single integration.

    ADR-038: Second phase — only available after functional spec is approved.
    Runs synchronously within the request (independent of the functional asyncio.Lock).

    Preconditions:
      - Integration exists in catalog
      - technical_status == "TECH_PENDING"
      - Approved functional spec exists in state.documents

    Returns:
        {"status": "success", "approval_id": "APP-XXXXXX"}
    """
    entry = state.catalog.get(integration_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Integration '{integration_id}' not found.")

    if entry.technical_status != "TECH_PENDING":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Technical generation requires technical_status='TECH_PENDING'. "
                f"Current: {entry.technical_status!r}"
            ),
        )

    func_doc = state.documents.get(f"{integration_id}-functional")
    if func_doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Approved functional spec for '{integration_id}' not found. Approve functional design first.",
        )

    entry.technical_status = "TECH_GENERATING"
    if db.catalog_col is not None:
        await db.catalog_col.replace_one({"id": entry.id}, entry.model_dump(), upsert=True)

    try:
        tech_content = await generate_technical_doc(
            entry=entry,
            functional_spec_content=func_doc.content,
            reviewer_feedback="",
            log_fn=logger.info,
        )
    except LLMOutputValidationError as exc:
        entry.technical_status = "TECH_PENDING"
        if db.catalog_col is not None:
            await db.catalog_col.replace_one({"id": entry.id}, entry.model_dump(), upsert=True)
        raise HTTPException(status_code=422, detail=f"Technical output failed structural guard: {exc}")
    except Exception as exc:
        entry.technical_status = "TECH_PENDING"
        if db.catalog_col is not None:
            await db.catalog_col.replace_one({"id": entry.id}, entry.model_dump(), upsert=True)
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {exc}")

    quality = assess_quality(tech_content)
    if not quality.passed:
        logger.warning(
            "[TECH-QUALITY] Low quality score %.2f for %s — %s",
            quality.quality_score, integration_id, "; ".join(quality.issues),
        )

    app_id = f"APP-{uuid.uuid4().hex[:6].upper()}"
    approval = Approval(
        id=app_id,
        integration_id=integration_id,
        doc_type="technical",
        content=tech_content,
        status="PENDING",
        generated_at=_now_iso(),
    )
    state.approvals[app_id] = approval
    if db.approvals_col is not None:
        await db.approvals_col.replace_one({"id": app_id}, approval.model_dump(), upsert=True)

    entry.technical_status = "TECH_REVIEW"
    if db.catalog_col is not None:
        await db.catalog_col.replace_one({"id": entry.id}, entry.model_dump(), upsert=True)

    logger.info("[TECH] Technical approval %s queued for HITL review (integration: %s)", app_id, integration_id)
    return {"status": "success", "approval_id": app_id}


@router.get("/agent/logs")
async def get_logs(offset: int = 0) -> dict:
    """Return agent logs from *offset* onwards (max 100 per call)."""
    capped = state.agent_logs[offset:][:100]
    return {
        "status": "success",
        "logs": [e.model_dump(mode="json") for e in capped],
        "next_offset": offset + len(capped),
        "finished": not state.agent_lock.locked(),
        "progress": state.agent_progress,   # R18: agent progress tracking
    }
