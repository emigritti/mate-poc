"""
Integration Agent — FastAPI Application
Unified backend for parsing requirements, executing Agentic RAG, and managing
HITL approvals.

Phase 1 changes (Correctness Foundation):
  - G-01: generate_with_ollama() now makes a real LLM call via httpx.AsyncClient
  - G-02: MongoDB persistence via motor (write-through cache, seed on startup)
  - G-04: run_agentic_rag_flow() is async; httpx replaces requests; asyncio.sleep
           replaces time.sleep; key.split('-') bug fixed
  - G-08: LLM output sanitized via output_guard before storage
  - G-09: prompt built from reusable-meta-prompt.md via prompt_builder

Phase 3 changes (Security):
  - G-06: all config from pydantic-settings (no hardcoded hosts/model names)
  - G-07: typed Pydantic request bodies; CSV MIME + size + encoding guards
  - G-08: sanitize_human_content() applied to HITL-submitted markdown
  - G-10: _require_token dependency on mutating endpoints (trigger/approve/reject)
  - F-01: CORS allow_origins from config allowlist (not wildcard+credentials)
  - F-09: asyncio.Lock prevents concurrent agent runs (resource exhaustion guard)
  - F-15: approve/reject check current status to prevent state machine bypass
"""

import asyncio
import csv
import hmac
import io
import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import chromadb
import httpx
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import db
from config import settings
from output_guard import (
    LLMOutputValidationError,
    sanitize_human_content,
    sanitize_llm_output,
)
from prompt_builder import build_prompt
from schemas import (
    Approval,
    ApproveRequest,
    CatalogEntry,
    ConfirmTagsRequest,
    Document,
    LogEntry,
    LogLevel,
    Requirement,
    RejectRequest,
    SuggestTagsResponse,
)

logger = logging.getLogger(__name__)

# ── In-memory state (write-through to MongoDB) ────────────────────────────────
parsed_requirements: list[Requirement] = []
catalog:   dict[str, CatalogEntry] = {}
documents: dict[str, Document]     = {}
approvals: dict[str, Approval]     = {}
agent_logs: list[LogEntry]         = []

# Task registry — prevents concurrent agent runs (F-09)
_agent_lock = asyncio.Lock()
_running_tasks: dict[str, asyncio.Task] = {}

# ChromaDB — initialized with retry in lifespan
chroma_client = None
collection     = None

# ── Constants ─────────────────────────────────────────────────────────────────
_ALLOWED_CSV_MIME = frozenset({
    "text/csv", "application/csv", "text/plain", "application/vnd.ms-excel",
})
_CSV_MAX_BYTES = 1_048_576  # 1 MB
_SAFE_FILENAME_RE = re.compile(r"[^\w\-.]")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _detect_level(msg: str) -> LogLevel:
    """Infer LogLevel from message prefix/content (single responsibility)."""
    if "[LLM]"   in msg: return LogLevel.LLM
    if "[RAG]"   in msg: return LogLevel.RAG
    if "[ERROR]" in msg: return LogLevel.ERROR
    if "[GUARD]" in msg: return LogLevel.WARN
    if "⛔"      in msg or "cancelled" in msg: return LogLevel.CANCEL
    if "completed" in msg or "Approved" in msg or "✓" in msg: return LogLevel.SUCCESS
    return LogLevel.INFO


def log_agent(msg: str) -> None:
    """Append a structured LogEntry and emit as INFO log."""
    entry = LogEntry(
        ts=datetime.now(timezone.utc),
        level=_detect_level(msg),
        message=msg,
    )
    agent_logs.append(entry)
    logger.info("[%s] %s", entry.level, msg)


def _prune_logs() -> None:
    """Remove LogEntry objects older than settings.log_ttl_hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.log_ttl_hours)
    agent_logs[:] = [e for e in agent_logs if e.ts > cutoff]


async def _prune_logs_loop() -> None:
    """Background task: prune agent_logs every 30 minutes."""
    while True:
        await asyncio.sleep(1800)
        _prune_logs()
        logger.debug("[Logs] TTL prune complete. Entries remaining: %d", len(agent_logs))


# ── ChromaDB init with retry ──────────────────────────────────────────────────

async def _init_chromadb(retries: int = 20, delay: float = 5.0) -> None:
    global chroma_client, collection
    for attempt in range(1, retries + 1):
        try:
            chroma_client = chromadb.HttpClient(
                host=settings.chroma_host, port=settings.chroma_port
            )
            collection = chroma_client.get_or_create_collection(
                name="approved_integrations"
            )
            logger.info("[ChromaDB] Connected (attempt %d/%d).", attempt, retries)
            return
        except Exception as exc:
            logger.warning(
                "[ChromaDB] Attempt %d/%d failed: %s", attempt, retries, exc
            )
            if attempt < retries:
                await asyncio.sleep(delay)
    logger.warning("[ChromaDB] Unavailable after all retries — RAG features disabled.")


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: connect to dependencies with retry
    await _init_chromadb()
    await db.init_db()

    # Seed in-memory cache from MongoDB (survives container restarts)
    if db.catalog_col is not None:
        async for doc in db.catalog_col.find({}, {"_id": 0}):
            catalog[doc["id"]] = CatalogEntry(**doc)
        async for doc in db.approvals_col.find({}, {"_id": 0}):
            approvals[doc["id"]] = Approval(**doc)
        async for doc in db.documents_col.find({}, {"_id": 0}):
            documents[doc["id"]] = Document(**doc)
        logger.info(
            "[DB] Seeded %d catalog / %d approvals / %d documents from MongoDB.",
            len(catalog), len(approvals), len(documents),
        )

    prune_task = asyncio.create_task(_prune_logs_loop(), name="log-pruner")

    yield

    prune_task.cancel()
    await db.close_db()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Integration Agent",
    description="Unified backend for Agentic RAG documentation generation",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — explicit allowlist, no wildcard + credentials (OWASP F-01)
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── Auth dependency ───────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


async def _require_token(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """
    Lightweight token guard for mutating endpoints (G-10).

    Behaviour:
      - API_KEY not configured → log warning, allow through (PoC dev mode).
      - API_KEY configured + valid Bearer token → allow.
      - API_KEY configured + missing/invalid token → 401.
    """
    if settings.api_key is None:
        logger.warning(
            "[Security] API_KEY not set — endpoint unprotected (PoC mode). "
            "Set API_KEY in .env to enable auth."
        )
        return "anonymous"

    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required.")

    # F-10 / OWASP A07: constant-time comparison prevents timing attacks
    if not hmac.compare_digest(creds.credentials, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid token.")

    return creds.credentials


# ── LLM call ──────────────────────────────────────────────────────────────────

async def generate_with_ollama(prompt: str) -> str:
    """
    Call Ollama LLM and return the raw response text.

    Uses httpx.AsyncClient — fully non-blocking (G-04 / ADR-012).
    Raises httpx.HTTPStatusError or httpx.RequestError on failure.
    Logs token/timing metrics to agent_logs for dashboard visibility.
    """
    log_agent(
        f"[LLM] → model={settings.ollama_model} "
        f"prompt_chars={len(prompt)} "
        f"timeout={settings.ollama_timeout_seconds}s"
    )
    async with httpx.AsyncClient(
        timeout=settings.ollama_timeout_seconds
    ) as client:
        res = await client.post(
            f"{settings.ollama_host}/api/generate",
            json={
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": settings.ollama_num_predict,
                    "temperature": settings.ollama_temperature,
                },
            },
        )
        res.raise_for_status()
        body = res.json()

        # Log Ollama performance metrics when available
        eval_count        = body.get("eval_count", 0)
        prompt_eval_count = body.get("prompt_eval_count", 0)
        eval_duration_ns  = body.get("eval_duration", 0)
        total_duration_ns = body.get("total_duration", 0)
        load_duration_ns  = body.get("load_duration", 0)

        total_s = total_duration_ns / 1e9
        load_s  = load_duration_ns  / 1e9
        tps     = eval_count / (eval_duration_ns / 1e9) if eval_duration_ns else 0

        log_agent(
            f"[LLM] ✓ done — "
            f"prompt_tokens={prompt_eval_count} "
            f"generated_tokens={eval_count} "
            f"speed={tps:.1f} tok/s "
            f"total={total_s:.1f}s "
            f"(model_load={load_s:.1f}s)"
        )

        return body.get("response", "")


# ── Tag helpers ───────────────────────────────────────────────────────────────

def _extract_category_tags(reqs: list[Requirement]) -> list[str]:
    """Return unique, whitespace-stripped category values from requirements (max 5)."""
    seen: list[str] = []
    for r in reqs:
        tag = r.category.strip()
        if tag and tag not in seen:
            seen.append(tag)
        if len(seen) >= 5:
            break
    return seen


async def _suggest_tags_via_llm(source: str, target: str, req_text: str) -> list[str]:
    """Call LLM with a lightweight prompt to suggest up to 2 integration tags.

    Returns empty list on any failure (timeout, parse error, etc.) so the
    caller can safely ignore LLM tags and fall back to category-only tags.
    """
    short_req = req_text[:500]
    prompt = (
        f"Given this integration between {source} and {target} "
        f"with these requirements:\n{short_req}\n"
        "Suggest up to 2 short tags (1-3 words each) that best categorize "
        "this integration.\n"
        'Reply with a JSON array only. Example: ["Data Sync", "Real-time"]'
    )
    try:
        raw = await generate_with_ollama(prompt)
        # Extract JSON array from response (LLM may wrap it in prose)
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if not match:
            return []
        tags = json.loads(match.group())
        if not isinstance(tags, list):
            return []
        return [str(t).strip() for t in tags if str(t).strip()][:2]
    except Exception as exc:
        logger.warning("[Tags] LLM tag suggestion failed: %s", exc)
        return []


def _build_rag_context(docs: list[str]) -> str:
    """Join docs and truncate to prevent prompt overflow on CPU instances."""
    raw = "\n---\n".join(docs)
    max_chars = settings.ollama_rag_max_chars
    if len(raw) > max_chars:
        log_agent(f"[RAG] Context truncated to {max_chars} chars (was {len(raw)}).")
        return raw[:max_chars]
    return raw


async def _query_rag_with_tags(
    query_text: str, tags: list[str]
) -> tuple[str, str]:
    """Query ChromaDB with tag filter, falling back to similarity search.

    Returns:
        (rag_context, source_label)
        source_label: "tag_filtered" | "similarity_fallback" | "none"
    """
    if not collection:
        return "", "none"

    # Step 1: tag-filtered query using primary tag
    if tags:
        try:
            results = collection.query(
                query_texts=[query_text],
                n_results=2,
                where={"tags_csv": {"$contains": tags[0]}},
            )
            docs = (results or {}).get("documents", [[]])[0]
            if docs:
                return _build_rag_context(docs), "tag_filtered"
        except Exception as exc:
            log_agent(f"[RAG] Tag-filtered query failed: {exc}")

        log_agent(f"[RAG] No tagged examples for {tags} — fallback to similarity search.")

    # Step 2: similarity fallback (no metadata filter)
    try:
        results = collection.query(query_texts=[query_text], n_results=2)
        docs = (results or {}).get("documents", [[]])[0]
        if docs:
            return _build_rag_context(docs), "similarity_fallback"
    except Exception as exc:
        log_agent(f"[ERROR] ChromaDB similarity query failed: {exc}")

    return "", "none"


# ── Agentic RAG flow ──────────────────────────────────────────────────────────

async def run_agentic_rag_flow() -> None:
    """
    Core agentic loop: read TAG_CONFIRMED catalog entries -> RAG -> LLM -> guard -> HITL queue.

    CatalogEntries are created at upload time (PENDING_TAG_REVIEW).
    This function only processes entries with confirmed tags (TAG_CONFIRMED).
    """
    confirmed = [e for e in catalog.values() if e.status == "TAG_CONFIRMED"]
    log_agent(f"Processing {len(confirmed)} TAG_CONFIRMED integration(s)...")

    for entry in confirmed:
        source = entry.source.get("system", "Unknown")
        target = entry.target.get("system", "Unknown")
        reqs = [r for r in parsed_requirements if r.req_id in entry.requirements]

        # Update status to PROCESSING
        entry.status = "PROCESSING"
        if db.catalog_col is not None:
            await db.catalog_col.replace_one(
                {"id": entry.id}, entry.model_dump(), upsert=True
            )
        log_agent(f"Processing entry: {entry.id} ({entry.name}) -- {len(reqs)} reqs.")

        # 1. Agentic RAG: query ChromaDB filtered by confirmed tags
        query_text = " ".join(r.description for r in reqs)
        log_agent(f"[RAG] Querying for {entry.id} with tags={entry.tags}...")
        rag_context, rag_source = await _query_rag_with_tags(query_text, entry.tags)
        log_agent(f"[RAG] Source: {rag_source} | chars: {len(rag_context)}")

        # 2. Build prompt from meta-prompt template (G-09)
        log_agent(f"[LLM] Prompting for Functional Spec for {entry.id}...")
        prompt = build_prompt(
            source_system=source,
            target_system=target,
            formatted_requirements=query_text,
            rag_context=rag_context,
        )

        # 3. Call real LLM, apply output guard (G-01, G-08)
        try:
            raw = await generate_with_ollama(prompt)
            func_content = sanitize_llm_output(raw)
            log_agent(f"[LLM] Spec generated and sanitized for {entry.id}.")
        except LLMOutputValidationError as exc:
            preview = (raw or "")[:120].replace("\n", " ")
            log_agent(f"[GUARD] Output rejected for {entry.id}: {exc}")
            log_agent(f"[GUARD] Raw preview: {preview!r}")
            func_content = "[LLM_OUTPUT_REJECTED: structural guard failed -- see agent logs]"
        except Exception as exc:
            log_agent(f"[ERROR] LLM generation failed for {entry.id}: {exc}")
            func_content = "[LLM_UNAVAILABLE: generation failed -- retry after Ollama is ready]"

        # 4. Create HITL Approval entry
        app_id = f"APP-{uuid.uuid4().hex[:6].upper()}"
        approval = Approval(
            id=app_id,
            integration_id=entry.id,
            doc_type="functional",
            content=func_content,
            status="PENDING",
            generated_at=_now_iso(),
        )
        approvals[app_id] = approval
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


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {
        "status": "healthy",
        "service": "integration-agent",
        "chromadb": "connected" if collection is not None else "unavailable",
        "mongodb":  "connected" if db.catalog_col is not None else "unavailable",
    }


# ── Requirements ──────────────────────────────────────────────────────────────

@app.post("/api/v1/requirements/upload", tags=["requirements"])
async def upload_requirements(file: UploadFile = File(...)) -> dict:
    """
    Parse a CSV file of integration requirements.

    Guards (G-07 / OWASP A03):
      - MIME type must be CSV/plain-text
      - File size capped at 1 MB
      - Content must be valid UTF-8
    """
    global parsed_requirements

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
    parsed_requirements = []
    for row in reader:
        req = Requirement(
            req_id=row.get("ReqID", f"R-{uuid.uuid4().hex[:6]}"),
            source_system=row.get("Source", "Unknown"),
            target_system=row.get("Target", "Unknown"),
            category=row.get("Category", "Sync"),
            description=row.get("Description", ""),
        )
        parsed_requirements.append(req)

    # Group requirements by source→target and create CatalogEntries
    groups: dict[str, list[Requirement]] = {}
    for r in parsed_requirements:
        key = f"{r.source_system}|||{r.target_system}"
        groups.setdefault(key, []).append(r)

    for _key, reqs in groups.items():
        source = reqs[0].source_system
        target = reqs[0].target_system
        entry_id = f"INT-{uuid.uuid4().hex[:6].upper()}"
        entry = CatalogEntry(
            id=entry_id,
            name=f"{source} to {target} Integration",
            type="Auto-discovered",
            source={"system": source},
            target={"system": target},
            requirements=[r.req_id for r in reqs],
            status="PENDING_TAG_REVIEW",
            tags=[],
            created_at=_now_iso(),
        )
        catalog[entry_id] = entry
        if db.catalog_col is not None:
            await db.catalog_col.replace_one(
                {"id": entry_id}, entry.model_dump(), upsert=True
            )

    return {
        "status": "success",
        "total_parsed": len(parsed_requirements),
        "integrations_created": len(groups),
    }


@app.get("/api/v1/requirements", tags=["requirements"])
async def get_requirements() -> dict:
    return {"status": "success", "data": [r.model_dump() for r in parsed_requirements]}


# ── Agent ─────────────────────────────────────────────────────────────────────

@app.post("/api/v1/agent/cancel", tags=["agent"])
async def cancel_agent(
    _token: str = Depends(_require_token),
) -> dict:
    """
    Cancel the currently running agent task.

    Injects CancelledError into the asyncio task at its next await point
    (typically mid-LLM call). The asyncio.Lock is released automatically
    by the context manager. Partial catalog entries already written to
    MongoDB are preserved — use Reset Tools to clean them up if needed.
    """
    if not _agent_lock.locked():
        raise HTTPException(status_code=409, detail="No agent is currently running.")

    cancelled = 0
    for task in list(_running_tasks.values()):
        task.cancel()
        cancelled += 1

    log_agent("⛔ Agent execution cancelled by user request.")
    return {"status": "success", "message": f"Cancel signal sent to {cancelled} task(s)."}


@app.get("/api/v1/agent/logs", tags=["agent"])
async def get_logs() -> dict:
    return {
        "status": "success",
        "logs": [e.model_dump(mode="json") for e in agent_logs[-100:]],
    }


@app.post("/api/v1/agent/trigger", tags=["agent"])
async def trigger_agent(
    _token: str = Depends(_require_token),
) -> dict:
    """
    Trigger the Agentic RAG flow asynchronously.

    Guarded by:
      - _require_token (G-10)
      - asyncio.Lock — prevents concurrent runs (F-09)
    """
    if not parsed_requirements:
        raise HTTPException(
            status_code=400, detail="No requirements loaded. Upload a CSV first."
        )

    if _agent_lock.locked():
        raise HTTPException(
            status_code=409, detail="Agent is already running. Wait for it to finish."
        )

    # Gate: all catalog entries must have confirmed tags before generation
    pending_tag_review = [
        e.id for e in catalog.values() if e.status == "PENDING_TAG_REVIEW"
    ]
    if pending_tag_review:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(pending_tag_review)} integration(s) are awaiting tag confirmation. "
                f"Confirm tags before triggering generation."
            ),
        )

    global agent_logs
    agent_logs = []
    log_agent("Started Agent Processing Task")

    task_id = uuid.uuid4().hex[:8].upper()

    async def _guarded_flow() -> None:
        async with _agent_lock:
            await run_agentic_rag_flow()

    task = asyncio.create_task(_guarded_flow(), name=task_id)
    _running_tasks[task_id] = task
    task.add_done_callback(
        lambda t: _running_tasks.pop(t.get_name(), None)
    )

    return {"status": "started", "task_id": task_id}


# ── Catalog ───────────────────────────────────────────────────────────────────

@app.get("/api/v1/catalog/integrations", tags=["catalog"])
async def get_catalog() -> dict:
    return {"status": "success", "data": [c.model_dump() for c in catalog.values()]}


@app.get("/api/v1/catalog/integrations/{id}/functional-spec", tags=["catalog"])
async def get_func_spec(id: str) -> dict:
    doc = documents.get(f"{id}-functional")
    if not doc:
        return {"status": "error", "message": "Document not approved yet or not found."}
    return {"status": "success", "data": doc.model_dump()}


@app.get("/api/v1/catalog/integrations/{id}/technical-spec", tags=["catalog"])
async def get_tech_spec(id: str) -> dict:
    return {"status": "error", "message": "Technical specs generation is not yet implemented."}


@app.get("/api/v1/catalog/integrations/{id}/suggest-tags", tags=["catalog"])
async def suggest_tags(id: str) -> dict:
    """Propose tags for an integration from requirement categories + LLM."""
    if id not in catalog:
        raise HTTPException(status_code=404, detail="Integration not found.")

    entry = catalog[id]
    reqs = [r for r in parsed_requirements if r.req_id in entry.requirements]

    # Source 1: category extraction (deterministic)
    category_tags = _extract_category_tags(reqs)

    # Source 2: LLM suggestion (may return empty list on failure)
    req_text = " ".join(r.description for r in reqs)
    llm_tags = await _suggest_tags_via_llm(
        entry.source.get("system", ""), entry.target.get("system", ""), req_text
    )

    # Merge, deduplicate, cap at 5
    merged: list[str] = list(category_tags)
    for t in llm_tags:
        if t not in merged:
            merged.append(t)
    suggested = merged[:5]

    return SuggestTagsResponse(
        integration_id=id,
        suggested_tags=suggested,
        source={
            "from_categories": category_tags,
            "from_llm": [t for t in llm_tags if t not in category_tags],
        },
    ).model_dump()


@app.post("/api/v1/catalog/integrations/{id}/confirm-tags", tags=["catalog"])
async def confirm_tags(
    id: str,
    body: ConfirmTagsRequest,
    _token: str = Depends(_require_token),
) -> dict:
    """Confirm integration tags and transition status to TAG_CONFIRMED."""
    if id not in catalog:
        raise HTTPException(status_code=404, detail="Integration not found.")

    entry = catalog[id]
    if entry.status != "PENDING_TAG_REVIEW":
        raise HTTPException(
            status_code=409,
            detail=f"Tags already confirmed or entry is in status '{entry.status}'.",
        )

    # Strip whitespace, discard blank tags, enforce max 50 chars each
    clean_tags = [t.strip()[:50] for t in body.tags if t.strip()]
    if not clean_tags:
        raise HTTPException(status_code=422, detail="No valid tags after stripping whitespace.")

    entry.tags = clean_tags
    entry.status = "TAG_CONFIRMED"
    if db.catalog_col is not None:
        await db.catalog_col.replace_one(
            {"id": id}, entry.model_dump(), upsert=True
        )

    return {
        "status": "success",
        "integration_id": id,
        "confirmed_tags": clean_tags,
    }


# ── Approvals (HITL) ──────────────────────────────────────────────────────────

@app.get("/api/v1/approvals/pending", tags=["approvals"])
async def get_pending_approvals() -> dict:
    pending = [a.model_dump() for a in approvals.values() if a.status == "PENDING"]
    return {"status": "success", "data": pending}


@app.post("/api/v1/approvals/{id}/approve", tags=["approvals"])
async def approve_doc(
    id: str,
    body: ApproveRequest,
    _token: str = Depends(_require_token),
) -> dict:
    """
    Approve a pending document.

    Guards:
      - Typed body (G-07 / OWASP A03)
      - Status machine check — prevents double-approval (F-15)
      - sanitize_human_content — strips HTML from clipboard paste (G-08 / F-05)
      - ChromaDB upsert uses doc_id as stable key; duplicate raises caught (F-14)
    """
    if id not in approvals:
        raise HTTPException(status_code=404, detail="Approval not found.")

    app_entry = approvals[id]
    if app_entry.status == "APPROVED":
        raise HTTPException(status_code=409, detail="Document already approved.")

    # Sanitize human-edited content before storage (G-08)
    safe_md = sanitize_human_content(body.final_markdown)

    app_entry.status  = "APPROVED"
    app_entry.content = safe_md
    if db.approvals_col is not None:
        await db.approvals_col.replace_one(
            {"id": id}, app_entry.model_dump(), upsert=True
        )

    # Save final Document
    doc_id = f"{app_entry.integration_id}-{app_entry.doc_type}"
    doc = Document(
        id=doc_id,
        integration_id=app_entry.integration_id,
        doc_type=app_entry.doc_type,
        content=safe_md,
        generated_at=_now_iso(),
    )
    documents[doc_id] = doc
    if db.documents_col is not None:
        await db.documents_col.replace_one(
            {"id": doc_id}, doc.model_dump(), upsert=True
        )

    # Persist to ChromaDB RAG store (learning loop)
    if collection is not None:
        try:
            # Include confirmed tags as searchable metadata
            cat_entry = catalog.get(app_entry.integration_id)
            tags_csv = ",".join(cat_entry.tags) if cat_entry else ""
            collection.upsert(
                documents=[safe_md],
                metadatas=[{
                    "integration_id": app_entry.integration_id,
                    "type": app_entry.doc_type,
                    "tags_csv": tags_csv,
                }],
                ids=[doc_id],
            )
            logger.info("[RAG] Saved %s to ChromaDB (tags: %s).", doc_id, tags_csv)
        except Exception as exc:
            logger.warning("[RAG] ChromaDB save failed for %s: %s", doc_id, exc)

    return {"status": "success", "message": "Approved and saved to RAG."}


# ── Admin / Reset ─────────────────────────────────────────────────────────────

@app.delete("/api/v1/admin/reset/requirements", tags=["admin"])
async def reset_requirements(
    _token: str = Depends(_require_token),
) -> dict:
    """
    Clear in-memory parsed requirements and agent logs.
    Safe to call even while the agent is not running.
    """
    global parsed_requirements, agent_logs
    if _agent_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Agent is running — wait for it to finish before resetting.",
        )
    parsed_requirements = []
    agent_logs = []
    logger.info("[ADMIN] Requirements and agent logs cleared.")
    return {"status": "success", "message": "Requirements and agent logs cleared."}


@app.delete("/api/v1/admin/reset/mongodb", tags=["admin"])
async def reset_mongodb(
    _token: str = Depends(_require_token),
) -> dict:
    """
    Drop all documents from MongoDB catalog / approvals / documents collections
    and clear the corresponding in-memory caches atomically.
    """
    if db.catalog_col is not None:
        await db.catalog_col.delete_many({})
    if db.approvals_col is not None:
        await db.approvals_col.delete_many({})
    if db.documents_col is not None:
        await db.documents_col.delete_many({})
    catalog.clear()
    approvals.clear()
    documents.clear()
    logger.info("[ADMIN] MongoDB collections and in-memory caches cleared.")
    return {"status": "success", "message": "MongoDB collections cleared."}


@app.delete("/api/v1/admin/reset/chromadb", tags=["admin"])
async def reset_chromadb(
    _token: str = Depends(_require_token),
) -> dict:
    """
    Delete and recreate the ChromaDB 'approved_integrations' collection,
    effectively wiping the RAG vector store.
    """
    global collection
    if chroma_client is None:
        raise HTTPException(status_code=503, detail="ChromaDB is unavailable.")
    try:
        chroma_client.delete_collection("approved_integrations")
        collection = chroma_client.get_or_create_collection("approved_integrations")
        logger.info("[ADMIN] ChromaDB collection cleared and recreated.")
        return {"status": "success", "message": "ChromaDB collection cleared."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ChromaDB reset failed: {exc}")


@app.delete("/api/v1/admin/reset/all", tags=["admin"])
async def reset_all(
    _token: str = Depends(_require_token),
) -> dict:
    """
    Full system reset: requirements, agent logs, MongoDB collections,
    ChromaDB vector store. Rejected if the agent is currently running.
    """
    global parsed_requirements, agent_logs, collection
    if _agent_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Agent is running — wait for it to finish before resetting.",
        )

    # 1. Requirements + logs
    parsed_requirements = []
    agent_logs = []

    # 2. MongoDB + in-memory caches
    if db.catalog_col is not None:
        await db.catalog_col.delete_many({})
    if db.approvals_col is not None:
        await db.approvals_col.delete_many({})
    if db.documents_col is not None:
        await db.documents_col.delete_many({})
    catalog.clear()
    approvals.clear()
    documents.clear()

    # 3. ChromaDB (non-fatal if unavailable)
    chroma_warning = ""
    if chroma_client is not None:
        try:
            chroma_client.delete_collection("approved_integrations")
            collection = chroma_client.get_or_create_collection("approved_integrations")
        except Exception as exc:
            chroma_warning = f" ChromaDB warning: {exc}"

    msg = f"Full reset completed.{chroma_warning}"
    logger.info("[ADMIN] %s", msg)
    return {"status": "success", "message": msg}


@app.post("/api/v1/approvals/{id}/reject", tags=["approvals"])
async def reject_doc(
    id: str,
    body: RejectRequest,
    _token: str = Depends(_require_token),
) -> dict:
    """
    Reject a pending document.

    Guards:
      - Typed body (G-07)
      - Status machine: only PENDING documents can be rejected (F-15)
    """
    if id not in approvals:
        raise HTTPException(status_code=404, detail="Approval not found.")

    if approvals[id].status != "PENDING":
        raise HTTPException(
            status_code=409,
            detail=f"Only PENDING approvals can be rejected (current: {approvals[id].status}).",
        )

    approvals[id].status   = "REJECTED"
    approvals[id].feedback = body.feedback
    if db.approvals_col is not None:
        await db.approvals_col.replace_one(
            {"id": id}, approvals[id].model_dump(), upsert=True
        )

    return {"status": "success", "message": "Rejected. Feedback stored for agent retry context."}
