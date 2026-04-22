"""
Agent Router — trigger, cancel, logs endpoints.

Extracted from main.py (R15).
Uses generate_with_retry (R13) for LLM calls with exponential backoff.
"""

import asyncio
import logging
import uuid
import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from typing import Optional
from pydantic import BaseModel

import db
import state
from auth import require_token
from utils import _now_iso
from config import settings
from log_helpers import log_agent
from output_guard import LLMOutputValidationError, QualityGateError, assess_quality, enforce_quality_gate
from schemas import Approval, LogEntry
from services.agent_service import generate_integration_doc
from services.retriever import ScoredChunk

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["agent"])


class TriggerRequest(BaseModel):
    """Optional request body for POST /agent/trigger."""
    pinned_doc_ids: list[str] = []
    llm_profile: str = "default"   # "default" | "high_quality" (ADR-046)
    project_id: Optional[str] = None  # ADR-050: None = process all TAG_CONFIRMED (backward-compat)


# ── Agentic RAG flow ──────────────────────────────────────────────────────────

async def run_agentic_rag_flow(
    pinned_chunks: list[ScoredChunk] | None = None,
    llm_profile: str = "default",
    project_id: Optional[str] = None,
) -> None:
    """
    Core agentic loop: read TAG_CONFIRMED catalog entries → RAG → LLM → guard → HITL queue.

    Generates a single unified Integration Spec per entry using the
    integration_base_template.md. Optionally enriches n/a sections via Claude API.

    Args:
        pinned_chunks: KB chunks explicitly selected by the user to be injected
                       in the PINNED REFERENCES section of every generated document.
        llm_profile:   "default" or "high_quality" — selects the Ollama model and sampling
                       parameters for document generation (ADR-046). "premium" accepted as alias.
        project_id:    ADR-050 — restrict processing to entries for this project.
                       None = process all TAG_CONFIRMED entries (backward-compatible).
    """
    confirmed = [
        e for e in state.catalog.values()
        if e.status == "TAG_CONFIRMED"
        and (project_id is None or e.project_id == project_id)
    ]
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

        # RAG retrieval + LLM generation + optional Claude enrichment
        gen_report = None
        quality = None
        try:
            spec_content, gen_report = await generate_integration_doc(
                entry=entry,
                requirements=reqs,
                reviewer_feedback="",
                log_fn=log_agent,
                pinned_chunks=pinned_chunks or [],
                llm_profile=llm_profile,
            )
            log_agent(
                f"[LLM] Integration Spec generated for {entry.id} — "
                f"{len(spec_content)} chars."
            )
            # Quality gate: assess then enforce before queueing for HITL review.
            quality = assess_quality(spec_content)
            if not quality.passed:
                log_agent(
                    f"[QUALITY] Issues for {entry.id} (score={quality.quality_score:.2f})"
                    f" — {'; '.join(quality.issues)}"
                )
            else:
                log_agent(f"[QUALITY] OK — score {quality.quality_score:.2f} for {entry.id}")
            enforce_quality_gate(
                quality,
                min_score=settings.quality_gate_min_score,
                mode=settings.quality_gate_mode,
            )
        except QualityGateError as exc:
            log_agent(f"[QUALITY GATE] Document BLOCKED for {entry.id}: {exc}")
            score_str = f"{quality.quality_score:.2f}" if quality else "n/a"
            issues_str = "; ".join(quality.issues) if quality else str(exc)
            spec_content = (
                f"[QUALITY_GATE_BLOCKED: score={score_str} — {issues_str}]"
            )
        except LLMOutputValidationError as exc:
            log_agent(f"[GUARD] Output rejected for {entry.id}: {exc}")
            spec_content = "[LLM_OUTPUT_REJECTED: structural guard failed — see agent logs]"
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
            spec_content = "[LLM_UNAVAILABLE: generation failed — see agent logs for details]"

        # Create HITL Approval entry
        app_id = f"APP-{uuid.uuid4().hex[:6].upper()}"
        approval = Approval(
            id=app_id,
            integration_id=entry.id,
            doc_type="integration",
            content=spec_content,
            status="PENDING",
            generated_at=_now_iso(),
            generation_report=gen_report,
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
    request: TriggerRequest = Body(default_factory=TriggerRequest),
    _token: str = Depends(require_token),
) -> dict:
    """
    Trigger the Agentic RAG flow asynchronously.

    Accepts an optional JSON body with ``pinned_doc_ids`` — a list of KB document
    IDs whose chunks will be injected as a mandatory PINNED REFERENCES section in
    every generated document, regardless of RAG retrieval score.

    Guarded by:
      - require_token (G-10)
      - asyncio.Lock — prevents concurrent runs (F-09)
    """
    if not state.parsed_requirements:
        raise HTTPException(
            status_code=400, detail="No requirements loaded. Upload a CSV or Markdown file first."
        )

    if state.agent_lock.locked():
        raise HTTPException(
            status_code=409, detail="Agent is already running. Wait for it to finish."
        )

    # Gate: catalog entries awaiting tag confirmation (scoped to project if provided, ADR-050)
    pid = request.project_id.upper().strip() if request.project_id else None
    pending_tag_review = [
        e.id for e in state.catalog.values()
        if e.status == "PENDING_TAG_REVIEW"
        and (pid is None or e.project_id == pid)
    ]
    if pending_tag_review:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(pending_tag_review)} integration(s) are awaiting tag confirmation. "
                f"Confirm tags before triggering generation."
            ),
        )

    # Resolve pinned chunks from the in-memory BM25 corpus (state.kb_chunks).
    # URL-type KB docs are not chunked (fetched live); they are silently skipped.
    pinned_chunks: list[ScoredChunk] = []
    for doc_id in request.pinned_doc_ids:
        texts = state.kb_chunks.get(doc_id, [])
        if not texts:
            logger.warning("[PINNED] doc_id %s not found in kb_chunks — skipped", doc_id)
            continue
        pinned_chunks.extend(
            ScoredChunk(text=t, score=1.0, source_label="pinned", doc_id=doc_id)
            for t in texts
        )
    if pinned_chunks:
        log_agent(
            f"[PINNED] {len(pinned_chunks)} chunk(s) pinned from "
            f"{len(request.pinned_doc_ids)} doc(s): {request.pinned_doc_ids}"
        )

    state.agent_logs.clear()
    log_agent("Started Agent Processing Task")

    task_id = uuid.uuid4().hex[:8].upper()

    llm_profile = request.llm_profile

    async def _guarded_flow() -> None:
        async with state.agent_lock:
            await run_agentic_rag_flow(
                pinned_chunks=pinned_chunks,
                llm_profile=llm_profile,
                project_id=pid,
            )

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
