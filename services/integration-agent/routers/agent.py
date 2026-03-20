"""
Agent Router — trigger, cancel, logs endpoints.

Extracted from main.py (R15).
Uses generate_with_retry (R13) for LLM calls with exponential backoff.
"""

import asyncio
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException

import db
import state
from auth import require_token
from config import settings
from log_helpers import log_agent
from output_guard import LLMOutputValidationError, sanitize_llm_output
from prompt_builder import build_prompt
from schemas import Approval, LogEntry
from services.llm_service import generate_with_retry
from services.rag_service import ContextAssembler, fetch_url_kb_context
from services.retriever import ScoredChunk as _SC, hybrid_retriever

router = APIRouter(prefix="/api/v1", tags=["agent"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Agentic RAG flow ──────────────────────────────────────────────────────────

async def run_agentic_rag_flow() -> None:
    """
    Core agentic loop: read TAG_CONFIRMED catalog entries → RAG → LLM → guard → HITL queue.

    Now uses generate_with_retry (R13) for resilient LLM calls.
    """
    confirmed = [e for e in state.catalog.values() if e.status == "TAG_CONFIRMED"]
    total = len(confirmed)
    log_agent(f"Processing {total} TAG_CONFIRMED integration(s)...")

    for idx, entry in enumerate(confirmed, start=1):
        source = entry.source.get("system", "Unknown")
        target = entry.target.get("system", "Unknown")
        reqs = [r for r in state.parsed_requirements if r.req_id in entry.requirements]

        log_agent(
            f"[STEP {idx}/{total}] {entry.id} — {source} → {target} "
            f"({len(reqs)} requirement(s), tags: {entry.tags})"
        )

        # Update status to PROCESSING
        entry.status = "PROCESSING"
        if db.catalog_col is not None:
            await db.catalog_col.replace_one(
                {"id": entry.id}, entry.model_dump(), upsert=True
            )
        log_agent(f"Processing entry: {entry.id} ({entry.name}) -- {len(reqs)} reqs.")

        # 1. Multi-query hybrid retrieval (R8 + R9 + R12 + BM25 / Phase 2)
        query_text = " ".join(r.description for r in reqs)
        category   = entry.tags[0] if entry.tags else ""

        log_agent(f"[RAG] Hybrid retrieval for {entry.id} (tags={entry.tags})...")
        approved_chunks = await hybrid_retriever.retrieve(
            query_text,
            entry.tags,
            state.collection,
            source=source,
            target=target,
            category=category,
            log_fn=log_agent,
        )

        kb_scored_chunks = await hybrid_retriever.retrieve(
            query_text,
            entry.tags,
            state.kb_collection,
            source=source,
            target=target,
            category=category,
            log_fn=log_agent,
        )

        # 2. Fetch live URL KB entries (tag-filtered)
        url_raw = await fetch_url_kb_context(
            entry.tags, state.kb_docs, log_fn=log_agent
        )
        url_chunks = ([_SC(text=url_raw, score=0.5, source_label="kb_url")]
                      if url_raw else [])

        # 3. ContextAssembler: unified context with structured sections (R10)
        assembler   = ContextAssembler()
        rag_context = assembler.assemble(
            approved_chunks,
            kb_scored_chunks,
            url_chunks,
            max_chars=settings.ollama_rag_max_chars,
        )
        log_agent(f"[RAG] Assembled context: {len(rag_context)} chars")

        # 4. Build prompt from meta-prompt template (G-09)
        prompt = build_prompt(
            source_system=source,
            target_system=target,
            formatted_requirements=query_text,
            rag_context=rag_context,
            kb_context="",  # now included in rag_context via ContextAssembler
        )
        log_agent(f"[LLM] Prompt ready for {entry.id} — {len(prompt)} chars. Calling {settings.ollama_model}...")

        # 4. Call LLM with retry (R13), apply output guard (G-08)
        try:
            raw = await generate_with_retry(prompt, log_fn=log_agent)
            func_content = sanitize_llm_output(raw)
            log_agent(
                f"[LLM] Spec generated and sanitized for {entry.id} — "
                f"{len(func_content)} chars."
            )
        except LLMOutputValidationError as exc:
            preview = (raw or "")[:120].replace("\n", " ")
            log_agent(f"[GUARD] Output rejected for {entry.id}: {exc}")
            log_agent(f"[GUARD] Raw preview: {preview!r}")
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


@router.get("/agent/logs")
async def get_logs(offset: int = 0) -> dict:
    """Return agent logs from *offset* onwards (max 100 per call)."""
    capped = state.agent_logs[offset:][:100]
    return {
        "status": "success",
        "logs": [e.model_dump(mode="json") for e in capped],
        "next_offset": offset + len(capped),
        "finished": not state.agent_lock.locked(),
    }
