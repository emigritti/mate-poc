"""
Admin Router — reset, LLM settings, project docs endpoints.

Extracted from main.py (R15).
"""

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import db
import state
from auth import require_token
from config import settings
from services.llm_service import llm_overrides

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["admin"])


# ── LLM Settings Patch schema ─────────────────────────────────────────────────

class _DocLLMPatch(BaseModel):
    model: str | None = None
    num_predict: int | None = None
    timeout_seconds: int | None = None
    temperature: float | None = None
    rag_max_chars: int | None = None


class _TagLLMPatch(BaseModel):
    num_predict: int | None = None
    timeout_seconds: int | None = None
    temperature: float | None = None


class LLMSettingsPatchRequest(BaseModel):
    doc_llm: _DocLLMPatch | None = None
    tag_llm: _TagLLMPatch | None = None

# ── Project Docs ──────────────────────────────────────────────────────────────
DOCS_ROOT = Path(os.getenv("DOCS_ROOT", Path(__file__).parent.parent.parent.parent / "docs"))
if not DOCS_ROOT.is_dir():
    logger.warning("DOCS_ROOT %s does not exist or is not a directory.", DOCS_ROOT)

DOCS_MANIFEST: list[dict] = [
    {"path": "README.md", "name": "README", "category": "Guide", "description": "Overview of the project."},
    {"path": "AWS-DEPLOYMENT-GUIDE.md", "name": "AWS Deployment Guide", "category": "Guide", "description": "Step-by-step AWS deployment instructions."},
    {"path": "architecture_specification.md", "name": "Architecture Specification", "category": "Guide", "description": "Full technical architecture."},
    {"path": "functional-guide.md", "name": "Functional Guide", "category": "Guide", "description": "End-to-end functional walkthrough."},
    {"path": "adr/ADR-001-011-decisions.md", "name": "ADR-001…011", "category": "ADR", "description": "Foundational decisions."},
    {"path": "adr/ADR-012-async-llm-client.md", "name": "ADR-012 Async LLM Client", "category": "ADR", "description": "Decision to use httpx.AsyncClient."},
    {"path": "adr/ADR-013-mongodb-persistence.md", "name": "ADR-013 MongoDB Persistence", "category": "ADR", "description": "MongoDB write-through cache."},
    {"path": "adr/ADR-014-prompt-builder.md", "name": "ADR-014 Prompt Builder", "category": "ADR", "description": "Prompt assembly module."},
    {"path": "adr/ADR-015-llm-output-guard.md", "name": "ADR-015 LLM Output Guard", "category": "ADR", "description": "Output sanitization layer."},
    {"path": "adr/ADR-016-secret-management.md", "name": "ADR-016 Secret Management", "category": "ADR", "description": "Pydantic-settings config."},
    {"path": "adr/ADR-017-frontend-xss-mitigation.md", "name": "ADR-017 Frontend XSS", "category": "ADR", "description": "Frontend XSS mitigation."},
    {"path": "adr/ADR-018-cors-standardization.md", "name": "ADR-018 CORS Standardization", "category": "ADR", "description": "CORS allowlist strategy."},
    {"path": "adr/ADR-019-rag-tag-filtering.md", "name": "ADR-019 RAG Tag Filtering", "category": "ADR", "description": "ChromaDB tag-based queries."},
    {"path": "adr/ADR-020-tag-llm-tuning.md", "name": "ADR-020 Tag LLM Tuning", "category": "ADR", "description": "Lightweight tag LLM settings."},
    {"path": "adr/ADR-021-best-practice-flow.md", "name": "ADR-021 Best Practice Flow", "category": "ADR", "description": "KB import flow and RAG integration."},
    {"path": "adr/ADR-022-nginx-gateway.md", "name": "ADR-022 Nginx Gateway", "category": "ADR", "description": "Nginx reverse-proxy gateway."},
    {"path": "adr/ADR-023-document-lifecycle-staged-promotion.md", "name": "ADR-023 Document Lifecycle", "category": "ADR", "description": "Staged document promotion."},
    {"path": "adr/ADR-024-kb-url-links.md", "name": "ADR-024 KB URL Links", "category": "ADR", "description": "Live URL fetch at generation time."},
    {"path": "adr/ADR-025-project-metadata-upload-modal.md", "name": "ADR-025 Project Metadata", "category": "ADR", "description": "Client-scoped projects."},
    {"path": "adr/ADR-026-backend-decomposition-r15.md", "name": "ADR-026 Backend Decomposition (R15)", "category": "ADR", "description": "Modular routers, services, shared state."},
    {"path": "adr/ADR-027-bm25-hybrid-retrieval.md", "name": "ADR-027 BM25 Hybrid Retrieval", "category": "ADR", "description": "BM25 + ChromaDB dense ensemble retrieval."},
    {"path": "adr/ADR-028-multi-query-expansion.md", "name": "ADR-028 Multi-Query Expansion", "category": "ADR", "description": "2 template + 2 LLM query variants."},
    {"path": "adr/ADR-029-context-assembler.md", "name": "ADR-029 ContextAssembler", "category": "ADR", "description": "Unified context fusion with token budget."},
    {"path": "adr/ADR-030-semantic-chunking-langchain.md", "name": "ADR-030 Semantic Chunking", "category": "ADR", "description": "LangChain RecursiveCharacterTextSplitter."},
    {"path": "code-review/CODE-REVIEW-CHECKLIST.md", "name": "Code Review Checklist", "category": "Checklist", "description": "Architecture/correctness/security gates."},
    {"path": "security-review/SECURITY-REVIEW-CHECKLIST.md", "name": "Security Review Checklist", "category": "Checklist", "description": "OWASP-aligned security checklist."},
    {"path": "unit-test-review/UNIT-TEST-REVIEW-CHECKLIST.md", "name": "Unit Test Review Checklist", "category": "Checklist", "description": "Test quality gates."},
    {"path": "test-plan/TEST-PLAN-001-remediation.md", "name": "TEST-PLAN-001 Remediation", "category": "Test Plan", "description": "Unit test plan with 195 tests."},
    {"path": "mappings/UNIT-SECURITY-OWASP-MAPPING.md", "name": "OWASP Unit-Test Mapping", "category": "Mapping", "description": "Test-to-OWASP traceability."},
]


# ── Reset endpoints ───────────────────────────────────────────────────────────

@router.delete("/admin/reset/requirements")
async def reset_requirements(
    _token: str = Depends(require_token),
) -> dict:
    if state.agent_lock.locked():
        raise HTTPException(status_code=409, detail="Agent is running — wait for it to finish before resetting.")
    state.parsed_requirements.clear()
    state.agent_logs.clear()
    logger.info("[ADMIN] Requirements and agent logs cleared.")
    return {"status": "success", "message": "Requirements and agent logs cleared."}


@router.delete("/admin/reset/mongodb")
async def reset_mongodb(
    _token: str = Depends(require_token),
) -> dict:
    if db.catalog_col is not None:
        await db.catalog_col.delete_many({})
    if db.approvals_col is not None:
        await db.approvals_col.delete_many({})
    if db.documents_col is not None:
        await db.documents_col.delete_many({})
    state.catalog.clear()
    state.approvals.clear()
    state.documents.clear()
    logger.info("[ADMIN] MongoDB collections and in-memory caches cleared.")
    return {"status": "success", "message": "MongoDB collections cleared."}


@router.delete("/admin/reset/chromadb")
async def reset_chromadb(
    _token: str = Depends(require_token),
) -> dict:
    if state.chroma_client is None:
        raise HTTPException(status_code=503, detail="ChromaDB is unavailable.")
    try:
        state.chroma_client.delete_collection("approved_integrations")
        state.collection = state.chroma_client.get_or_create_collection("approved_integrations")
        logger.info("[ADMIN] ChromaDB collection cleared and recreated.")
        return {"status": "success", "message": "ChromaDB collection cleared."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ChromaDB reset failed: {exc}")


@router.delete("/admin/reset/all")
async def reset_all(
    _token: str = Depends(require_token),
) -> dict:
    if state.agent_lock.locked():
        raise HTTPException(status_code=409, detail="Agent is running — wait for it to finish before resetting.")

    state.parsed_requirements.clear()
    state.agent_logs.clear()

    if db.catalog_col is not None:
        await db.catalog_col.delete_many({})
    if db.approvals_col is not None:
        await db.approvals_col.delete_many({})
    if db.documents_col is not None:
        await db.documents_col.delete_many({})
    if db.kb_documents_col is not None:
        await db.kb_documents_col.delete_many({})
    state.catalog.clear()
    state.approvals.clear()
    state.documents.clear()
    state.kb_docs.clear()

    llm_overrides.clear()
    if db.llm_settings_col is not None:
        await db.llm_settings_col.delete_one({"_id": "current"})

    chroma_warning = ""
    if state.chroma_client is not None:
        try:
            state.chroma_client.delete_collection("approved_integrations")
            state.collection = state.chroma_client.get_or_create_collection("approved_integrations")
            state.chroma_client.delete_collection("knowledge_base")
            state.kb_collection = state.chroma_client.get_or_create_collection("knowledge_base")
        except Exception as exc:
            chroma_warning = f" ChromaDB warning: {exc}"

    msg = f"Full reset completed.{chroma_warning}"
    logger.info("[ADMIN] %s", msg)
    return {"status": "success", "message": msg}


# ── LLM Settings ──────────────────────────────────────────────────────────────

def _llm_settings_response() -> dict:
    defaults = {
        "doc_llm": {
            "model":           settings.ollama_model,
            "num_predict":     settings.ollama_num_predict,
            "timeout_seconds": settings.ollama_timeout_seconds,
            "temperature":     settings.ollama_temperature,
            "rag_max_chars":   settings.ollama_rag_max_chars,
        },
        "tag_llm": {
            "num_predict":     settings.tag_num_predict,
            "timeout_seconds": settings.tag_timeout_seconds,
            "temperature":     settings.tag_temperature,
        },
    }
    effective = {
        "doc_llm": {
            "model":           llm_overrides.get("model",           settings.ollama_model),
            "num_predict":     llm_overrides.get("num_predict",      settings.ollama_num_predict),
            "timeout_seconds": llm_overrides.get("timeout_seconds",  settings.ollama_timeout_seconds),
            "temperature":     llm_overrides.get("temperature",      settings.ollama_temperature),
            "rag_max_chars":   llm_overrides.get("rag_max_chars",    settings.ollama_rag_max_chars),
        },
        "tag_llm": {
            "num_predict":     llm_overrides.get("tag_num_predict",    settings.tag_num_predict),
            "timeout_seconds": llm_overrides.get("tag_timeout_seconds", settings.tag_timeout_seconds),
            "temperature":     llm_overrides.get("tag_temperature",    settings.tag_temperature),
        },
    }
    return {
        "status": "success",
        "data": {
            "effective": effective,
            "defaults":  defaults,
            "overrides_active": bool(llm_overrides),
        },
    }


@router.get("/admin/llm-settings")
async def get_llm_settings(_token: str = Depends(require_token)) -> dict:
    return _llm_settings_response()


@router.patch("/admin/llm-settings")
async def patch_llm_settings(
    body: LLMSettingsPatchRequest,
    _token: str = Depends(require_token),
) -> dict:
    if body.doc_llm is not None:
        for k, v in body.doc_llm.model_dump(exclude_none=True).items():
            llm_overrides[k] = v

    if body.tag_llm is not None:
        for k, v in body.tag_llm.model_dump(exclude_none=True).items():
            llm_overrides[f"tag_{k}"] = v

    if db.llm_settings_col is not None:
        await db.llm_settings_col.replace_one(
            {"_id": "current"},
            {"_id": "current", **llm_overrides},
            upsert=True,
        )

    logger.info("[LLM-SETTINGS] Overrides updated: %s", llm_overrides)
    return _llm_settings_response()


@router.post("/admin/llm-settings/reset")
async def reset_llm_settings(_token: str = Depends(require_token)) -> dict:
    llm_overrides.clear()
    if db.llm_settings_col is not None:
        await db.llm_settings_col.delete_one({"_id": "current"})
    logger.info("[LLM-SETTINGS] Reset to design defaults.")
    return _llm_settings_response()


# ── Project Docs (read-only) ──────────────────────────────────────────────────

@router.get("/admin/docs")
async def list_project_docs(_token: str = Depends(require_token)) -> dict:
    return {"status": "success", "data": DOCS_MANIFEST}


@router.get("/admin/docs/{path:path}")
async def get_project_doc(path: str, _token: str = Depends(require_token)) -> dict:
    if "\x00" in path:
        raise HTTPException(status_code=400, detail="Invalid document path.")
    if not path.endswith(".md"):
        raise HTTPException(status_code=400, detail="Only .md files are served.")

    _manifest_paths = {d["path"] for d in DOCS_MANIFEST}
    if path not in _manifest_paths:
        raise HTTPException(status_code=404, detail="Document not found.")

    resolved = (DOCS_ROOT / path).resolve()
    docs_root_resolved = DOCS_ROOT.resolve()

    try:
        resolved.relative_to(docs_root_resolved)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document path.")

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Document not found.")

    content = resolved.read_text(encoding="utf-8")
    name = next((d["name"] for d in DOCS_MANIFEST if d["path"] == path), path)
    return {"status": "success", "data": {"path": path, "name": name, "content": content}}
