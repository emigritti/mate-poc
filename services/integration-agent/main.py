"""
Integration Agent — FastAPI Application (Refactored)

Slim app factory: lifespan, middleware, router registration.
All business logic lives in routers/ and services/ (R15).

Phase 1 changes:
  - R15: Decomposed from 2065-line monolith into modular routers and services.
  - R13: LLM calls now use retry with exponential backoff (via services.llm_service).
  - Backward compatible: all API paths and behavior are preserved.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import chromadb
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import db
import state
from config import settings
from log_helpers import prune_logs
from schemas import CatalogEntry, Approval, Document, KBDocument, Project
from services.llm_service import llm_overrides
from services.retriever import hybrid_retriever

# Import routers
from routers.requirements import router as requirements_router
from routers.projects import router as projects_router
from routers.catalog import router as catalog_router
from routers.agent import router as agent_router
from routers.approvals import router as approvals_router
from routers.documents import router as documents_router
from routers.kb import router as kb_router
from routers.admin import router as admin_router

logger = logging.getLogger(__name__)


# ── ChromaDB init with retry ──────────────────────────────────────────────────

async def _init_chromadb(retries: int = 20, delay: float = 5.0) -> None:
    for attempt in range(1, retries + 1):
        try:
            state.chroma_client = chromadb.HttpClient(
                host=settings.chroma_host, port=settings.chroma_port
            )
            state.collection = state.chroma_client.get_or_create_collection(
                name="approved_integrations"
            )
            state.kb_collection = state.chroma_client.get_or_create_collection(
                name="knowledge_base"
            )
            state.summaries_col = state.chroma_client.get_or_create_collection(
                name="kb_summaries"
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


# ── Log pruning background task ───────────────────────────────────────────────

async def _prune_logs_loop() -> None:
    """Background task: prune agent_logs every 30 minutes."""
    while True:
        await asyncio.sleep(1800)
        prune_logs()
        logger.debug("[Logs] TTL prune complete. Entries remaining: %d", len(state.agent_logs))


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: connect to dependencies with retry
    await _init_chromadb()
    await db.init_db()

    # Load persisted LLM overrides from MongoDB
    if db.llm_settings_col is not None:
        doc = await db.llm_settings_col.find_one({"_id": "current"})
        if doc:
            doc.pop("_id", None)
            llm_overrides.update(doc)
            logger.info("[LLM-SETTINGS] Loaded %d overrides from MongoDB.", len(llm_overrides))

    # Seed in-memory cache from MongoDB (survives container restarts)
    if db.catalog_col is not None:
        async for doc in db.catalog_col.find({}, {"_id": 0}):
            state.catalog[doc["id"]] = CatalogEntry(**doc)
        async for doc in db.approvals_col.find({}, {"_id": 0}):
            state.approvals[doc["id"]] = Approval(**doc)
        async for doc in db.documents_col.find({}, {"_id": 0}):
            state.documents[doc["id"]] = Document(**doc)
        logger.info(
            "[DB] Seeded %d catalog / %d approvals / %d documents from MongoDB.",
            len(state.catalog), len(state.approvals), len(state.documents),
        )

    # Seed Knowledge Base docs from MongoDB
    if db.kb_documents_col is not None:
        async for doc in db.kb_documents_col.find({}, {"_id": 0}):
            state.kb_docs[doc["id"]] = KBDocument(**doc)
        logger.info("[DB] Seeded %d KB documents from MongoDB.", len(state.kb_docs))

    # Load KB chunk texts from ChromaDB and build BM25 index (Phase 2 / ADR-027)
    if state.kb_collection is not None:
        try:
            kb_result = state.kb_collection.get(include=["documents", "metadatas"])
            docs  = kb_result.get("documents") or []
            metas = kb_result.get("metadatas") or []
            for doc_text, meta in zip(docs, metas):
                doc_id = (meta or {}).get("doc_id", "unknown")
                state.kb_chunks.setdefault(doc_id, []).append(doc_text)
            hybrid_retriever.build_bm25_index(state.kb_chunks)
            logger.info("[BM25] Index built from %d KB chunks at startup.", len(docs))
        except Exception as exc:
            logger.warning("[BM25] Failed to build index at startup: %s", exc)

    # Seed projects
    if db.projects_col is not None:
        async for doc in db.projects_col.find({}):
            doc.pop("_id", None)
            p = Project(**doc)
            state.projects[p.prefix] = p
        logger.info("[DB] Seeded %d projects from MongoDB.", len(state.projects))

    prune_task = asyncio.create_task(_prune_logs_loop(), name="log-pruner")

    yield

    prune_task.cancel()
    await db.close_db()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Integration Agent",
    description="Unified backend for Agentic RAG documentation generation",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — explicit allowlist (OWASP F-01)
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)

# Register all routers
app.include_router(requirements_router)
app.include_router(projects_router)
app.include_router(catalog_router)
app.include_router(agent_router)
app.include_router(approvals_router)
app.include_router(documents_router)
app.include_router(kb_router)
app.include_router(admin_router)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {
        "status": "healthy",
        "service": "integration-agent",
        "chromadb": "connected" if state.collection is not None else "unavailable",
        "mongodb":  "connected" if db.catalog_col is not None else "unavailable",
    }


# ── Backward-compatible re-exports for existing tests ─────────────────────────
# Tests reference main.catalog, main.collection, main._agent_lock, etc.
# These are now in state.py and services/*.py — re-export here so tests pass
# without modification. New code should import directly from state / services.

# State re-exports (tests do `import main; main.catalog.clear()`)
parsed_requirements = state.parsed_requirements
catalog    = state.catalog
documents  = state.documents
approvals  = state.approvals
agent_logs = state.agent_logs
kb_docs    = state.kb_docs
projects   = state.projects
collection = state.collection
kb_collection = state.kb_collection
_agent_lock = state.agent_lock

# Function re-exports (tests do `patch("main.generate_with_ollama", ...)`)
from services.llm_service import generate_with_ollama  # noqa: E402, F811
from routers.agent import run_agentic_rag_flow          # noqa: E402, F811
from log_helpers import log_agent, prune_logs as _prune_logs, _detect_level  # noqa: E402, F811

# LLM overrides (tests do `main._llm_overrides[...]`)
_llm_overrides = llm_overrides

# Re-export settings for tests that do `agent_main.settings`
# and httpx for tests that patch it
import httpx  # noqa: E402, F811

# Admin re-exports (tests do `from main import DOCS_MANIFEST`)
from routers.admin import DOCS_MANIFEST, DOCS_ROOT  # noqa: E402, F811

# Tag service re-exports (tests do `from main import _extract_category_tags`)
from services.tag_service import (  # noqa: E402, F811
    extract_category_tags as _extract_category_tags,
    suggest_tags_via_llm as _suggest_tags_via_llm,
)

# RAG service re-exports
from services.rag_service import (  # noqa: E402, F811
    build_rag_context as _build_rag_context,
    query_rag_with_tags as _query_rag_with_tags,
    query_kb_context as _query_kb_context,
    fetch_url_kb_context as _fetch_url_kb_context,
)
