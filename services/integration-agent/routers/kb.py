"""
Knowledge Base Router — upload, list, delete, tags, search, stats, add-url.

Extracted from main.py (R15).
"""

import logging
import secrets
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from typing import List, Optional

import db
import state
from auth import require_token
from config import settings
from document_parser import (
    DocumentParseError,
    detect_file_type,
    enrich_chunk_metadata,
    parse_document,
    parse_with_docling,
    semantic_chunk,
)
from log_helpers import log_agent
from services.retriever import hybrid_retriever
from schemas import (
    KBAddUrlRequest,
    KBDocument,
    KBExportBundle,
    KBExportChunk,
    KBImportResult,
    KBSearchResponse,
    KBSearchResult,
    KBStatsResponse,
    KBUpdateTagsRequest,
    KBUploadResponse,
)
from services.summarizer_service import summarize_section
from services.tag_service import suggest_kb_tags_via_llm
from services.wiki_graph_builder import WikiGraphBuilder
from utils import _now_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["knowledge-base"])


async def _run_raptor_summarization(
    doc_id: str,
    filename: str,
    docling_chunks: list,
    auto_tags: list[str],
    tags_csv: str,
) -> None:
    """
    RAPTOR-lite section summarization (ADR-032).

    Groups docling_chunks by section_header and generates LLM summaries for
    sections with >= 3 chunks. Capped at settings.kb_max_summarize_sections
    to prevent runaway LLM calls on large documents.

    Designed for use as a FastAPI BackgroundTask (fire-and-forget): all
    exceptions are caught and logged so a background failure never crashes
    the worker process.
    """
    if state.summaries_col is None:
        return

    from itertools import groupby

    sorted_chunks = sorted(docling_chunks, key=lambda c: c.section_header)
    sections_done = 0

    for section_header, group_iter in groupby(sorted_chunks, key=lambda c: c.section_header):
        if sections_done >= settings.kb_max_summarize_sections:
            logger.info(
                "[RAPTOR] Section cap (%d) reached for doc=%s — skipping remaining sections.",
                settings.kb_max_summarize_sections,
                doc_id,
            )
            break

        section_chunks = list(group_iter)
        try:
            summary = await summarize_section(section_chunks, doc_id=doc_id, tags=auto_tags)
        except Exception as exc:
            logger.warning("[RAPTOR] summarize_section failed for %s: %s", doc_id, exc)
            sections_done += 1
            continue

        sections_done += 1

        if summary is not None:
            summary_id = f"{doc_id}-summary-{abs(hash(section_header)) % 100000}"
            try:
                state.summaries_col.upsert(
                    documents=[summary.text],
                    metadatas=[{
                        "document_id": doc_id,
                        "filename": filename,
                        "section_header": summary.section_header,
                        "tags_csv": tags_csv,
                    }],
                    ids=[summary_id],
                )
                logger.info("[RAPTOR] Summary stored for doc=%s section='%s'.", doc_id, section_header)
            except Exception as exc:
                logger.warning("[RAPTOR] summaries_col upsert failed for %s: %s", doc_id, exc)


async def _run_wiki_graph_build(doc_id: str, force: bool = False) -> None:
    """Background task: build/update wiki graph for a KB document."""
    if db.wiki_entities_col is None or db.wiki_relationships_col is None:
        return
    if state.kb_collection is None:
        return
    try:
        builder = WikiGraphBuilder(
            entities_col=db.wiki_entities_col,
            relationships_col=db.wiki_relationships_col,
            kb_collection=state.kb_collection,
            ollama_host=settings.ollama_host,
            llm_model=settings.tag_model,
            llm_assist=settings.wiki_llm_relation_extraction,
            typed_edges_only=settings.wiki_graph_typed_edges_only,
        )
        stats = await builder.build_for_document(doc_id, force=force)
        logger.info("[Wiki] Auto-build for %s (force=%s): %s", doc_id, force, stats)
    except Exception as exc:
        logger.warning("[Wiki] Auto-build failed for %s: %s", doc_id, exc)


async def _process_kb_file(
    content: bytes,
    filename: str,
    file_type: str,
) -> tuple[str, list, list[str], str]:
    """Parse, auto-tag, enrich semantics, and upsert one KB file into ChromaDB.

    Shared by the single-upload and batch-upload endpoints to avoid pipeline
    duplication (ADR-044). Updates state.kb_docs and state.kb_chunks in-place.

    Args:
        content:   raw file bytes
        filename:  original filename (for tagging and metadata)
        file_type: detected format ("pdf", "docx", "md", etc.)

    Returns:
        (doc_id, docling_chunks, auto_tags, tags_csv)

    Raises:
        RuntimeError:  on parse failure, empty document, or ChromaDB write failure.
        HTTPException: 503 when ChromaDB is unavailable (propagated to caller).
    """
    try:
        docling_chunks = await parse_with_docling(content, file_type)
    except Exception as exc:
        raise RuntimeError(f"Document parsing failed: {exc}") from exc

    if not docling_chunks:
        raise RuntimeError("No text could be extracted from the file.")

    # ADR-X4: prepend situating annotations before embedding (Anthropic Contextual Retrieval).
    # Disabled by default in unit tests via CONTEXTUAL_RETRIEVAL_ENABLED env (see conftest.py).
    if settings.contextual_retrieval_enabled and len(docling_chunks) > 1:
        try:
            from services.contextual_retrieval_service import add_context_to_chunks
            full_doc = "\n\n".join(c.text for c in docling_chunks)
            docling_chunks = await add_context_to_chunks(full_doc, docling_chunks)
        except Exception as exc:
            log_agent(f"[KB] Contextual retrieval failed (graceful): {exc}")

    preview_text = " ".join(c.text for c in docling_chunks if c.chunk_type == "text")[:1000]
    auto_tags = await suggest_kb_tags_via_llm(
        preview_text or docling_chunks[0].text[:1000], filename, log_fn=log_agent,
    )
    log_agent(f"[KB] Auto-tags for '{filename}': {auto_tags}")

    doc_id = f"KB-{uuid.uuid4().hex[:8].upper()}"
    if state.kb_collection is None:
        raise HTTPException(status_code=503, detail="ChromaDB is unavailable.")

    tags_csv = ",".join(auto_tags)
    try:
        state.kb_collection.upsert(
            documents=[c.text for c in docling_chunks],
            metadatas=[
                {
                    **enrich_chunk_metadata(c, file_type),   # ADR-044 semantic fields
                    # These three must come AFTER the spread: enrich_chunk_metadata
                    # calls classify_chunk with document_id="" and filename="", so
                    # flatten_to_chroma would overwrite the real values if placed first.
                    "document_id":    doc_id,
                    "filename":       filename,
                    "tags_csv":       tags_csv,
                }
                for c in docling_chunks
            ],
            ids=[f"{doc_id}-chunk-{c.index}" for c in docling_chunks],
        )
        logger.info("[KB] Stored %d chunks in ChromaDB for %s.", len(docling_chunks), doc_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[KB] ChromaDB upsert failed for %s: %s", doc_id, exc)
        raise RuntimeError(f"Vector store failed: {exc}") from exc

    kb_doc = KBDocument(
        id=doc_id,
        filename=filename,
        file_type=file_type,
        file_size_bytes=len(content),
        tags=auto_tags,
        chunk_count=len(docling_chunks),
        content_preview=preview_text[:500] or "",
        uploaded_at=_now_iso(),
    )
    state.kb_docs[doc_id] = kb_doc
    state.kb_chunks[doc_id] = [c.text for c in docling_chunks]
    return doc_id, docling_chunks, auto_tags, tags_csv


@router.post("/kb/upload")
async def kb_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    _token: str = Depends(require_token),
) -> dict:
    """Upload a best-practice document to the Knowledge Base."""
    filename = file.filename or "unnamed"

    try:
        file_type = detect_file_type(filename, file.content_type)
    except DocumentParseError as exc:
        raise HTTPException(status_code=415, detail=str(exc))

    content = await file.read()
    if len(content) > settings.kb_max_file_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File exceeds the {settings.kb_max_file_bytes // 1_048_576} MB limit "
                f"({len(content):,} bytes received)."
            ),
        )

    try:
        doc_id, docling_chunks, auto_tags, tags_csv = await _process_kb_file(
            content, filename, file_type,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # RAPTOR-lite: run summarization in the background so the response is sent
    # immediately after ChromaDB/BM25/MongoDB (< 5s). This eliminates 504 errors
    # on large PDFs where sequential LLM calls would exceed nginx proxy_read_timeout.
    background_tasks.add_task(
        _run_raptor_summarization,
        doc_id=doc_id,
        filename=filename,
        docling_chunks=docling_chunks,
        auto_tags=auto_tags,
        tags_csv=tags_csv,
    )
    logger.info("[RAPTOR] Summarization enqueued as background task for doc=%s.", doc_id)

    # ADR-052: wiki graph build (auto, gated by config flag)
    if settings.wiki_auto_build_on_upload:
        background_tasks.add_task(_run_wiki_graph_build, doc_id)
        logger.info("[Wiki] Graph build enqueued as background task for doc=%s.", doc_id)

    # Update BM25 corpus — all chunk types (text, table, figure) are included (ADR-031).
    state.kb_chunks[doc_id] = [c.text for c in docling_chunks]
    hybrid_retriever.build_bm25_index(state.kb_chunks)
    if db.kb_documents_col is not None:
        await db.kb_documents_col.replace_one(
            {"id": doc_id}, state.kb_docs[doc_id].model_dump(), upsert=True
        )

    log_agent(f"[KB] Document '{filename}' imported as {doc_id} ({len(docling_chunks)} chunks).")
    return KBUploadResponse(
        id=doc_id,
        filename=filename,
        file_type=file_type,
        chunks_created=len(docling_chunks),
        auto_tags=auto_tags,
        raptor_status="pending",
    ).model_dump()


@router.post("/kb/batch-upload")
async def kb_batch_upload(
    files: List[UploadFile] = File(...),
    _token: str = Depends(require_token),
) -> dict:
    """Upload up to 10 documents at once to the Knowledge Base.

    Returns per-file results with partial success: a failure on one file
    does not abort processing of the remaining files.
    """
    if len(files) > 10:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files: at most 10 allowed, got {len(files)}.",
        )

    results: list[dict] = []
    for upload_file in files:
        filename = upload_file.filename or "unnamed"
        try:
            file_type = detect_file_type(filename, upload_file.content_type)
        except DocumentParseError as exc:
            results.append({"filename": filename, "status": "error", "chunks_created": 0, "error": str(exc)})
            continue

        content = await upload_file.read()
        if len(content) > settings.kb_max_file_bytes:
            results.append({
                "filename": filename,
                "status": "error",
                "chunks_created": 0,
                "error": (
                    f"File exceeds the {settings.kb_max_file_bytes // 1_048_576} MB limit "
                    f"({len(content):,} bytes received)."
                ),
            })
            continue

        try:
            doc_id, docling_chunks, auto_tags, tags_csv = await _process_kb_file(
                content, filename, file_type,
            )
        except (RuntimeError, HTTPException) as exc:
            error_msg = exc.detail if isinstance(exc, HTTPException) else str(exc)
            results.append({"filename": filename, "status": "error", "chunks_created": 0, "error": error_msg})
            continue

        # RAPTOR-lite summarization — runs inline (batch stays synchronous) but
        # the section cap (kb_max_summarize_sections) prevents runaway LLM calls.
        await _run_raptor_summarization(
            doc_id=doc_id,
            filename=filename,
            docling_chunks=docling_chunks,
            auto_tags=auto_tags,
            tags_csv=tags_csv,
        )

        state.kb_chunks[doc_id] = [c.text for c in docling_chunks]
        hybrid_retriever.build_bm25_index(state.kb_chunks)
        if db.kb_documents_col is not None:
            await db.kb_documents_col.replace_one(
                {"id": doc_id}, state.kb_docs[doc_id].model_dump(), upsert=True
            )

        log_agent(f"[KB] Batch-upload: '{filename}' imported as {doc_id} ({len(docling_chunks)} chunks).")
        results.append({"filename": filename, "status": "success", "chunks_created": len(docling_chunks), "error": None})

    return {"results": results}


@router.get("/kb/documents")
async def kb_list_documents() -> dict:
    return {
        "status": "success",
        "data": [d.model_dump() for d in state.kb_docs.values()],
    }


@router.post("/kb/add-url")
async def kb_add_url(
    body: KBAddUrlRequest,
    _token: str = Depends(require_token),
) -> dict:
    """Register an HTTP/HTTPS URL as a Knowledge Base reference entry."""
    url_str = str(body.url).strip()
    if not url_str.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must use http:// or https:// scheme.")

    parsed = urlparse(url_str)
    hostname = (parsed.hostname or "").lower()

    _BLOCKED_PREFIXES = ("127.", "10.", "192.168.", "0.0.0.0")
    _BLOCKED_NAMES = {"localhost", "::1", "0.0.0.0"}
    is_blocked = hostname in _BLOCKED_NAMES or any(hostname.startswith(p) for p in _BLOCKED_PREFIXES)
    if hostname.startswith("172."):
        try:
            second_octet = int(hostname.split(".")[1])
            if 16 <= second_octet <= 31:
                is_blocked = True
        except (IndexError, ValueError):
            pass
    if is_blocked:
        raise HTTPException(status_code=400, detail="Private or loopback URLs are not allowed.")

    clean_tags = [t.strip()[:50] for t in body.tags if t.strip()]
    if not clean_tags:
        raise HTTPException(status_code=422, detail="At least one non-empty tag is required.")

    display_title = (body.title or "").strip() or hostname or url_str

    doc_id = "KB-" + secrets.token_hex(4)
    kb_doc = KBDocument(
        id=doc_id,
        filename=display_title,
        file_type="url",
        file_size_bytes=0,
        tags=clean_tags,
        chunk_count=0,
        content_preview="",
        uploaded_at=_now_iso(),
        source_type="url",
        url=url_str,
    )

    if db.kb_documents_col is not None:
        await db.kb_documents_col.replace_one({"id": doc_id}, kb_doc.model_dump(), upsert=True)
    state.kb_docs[doc_id] = kb_doc

    log_agent(f"[KB] URL registered as {doc_id}: {url_str} (tags: {clean_tags})")
    return {"status": "success", "data": kb_doc.model_dump()}


@router.get("/kb/documents/{id}")
async def kb_get_document(id: str) -> dict:
    if id not in state.kb_docs:
        raise HTTPException(status_code=404, detail="KB document not found.")
    return {"status": "success", "data": state.kb_docs[id].model_dump()}


@router.delete("/kb/documents/{id}")
async def kb_delete_document(
    id: str,
    _token: str = Depends(require_token),
) -> dict:
    """Delete a Knowledge Base document and its chunks from ChromaDB and MongoDB."""
    if id not in state.kb_docs:
        raise HTTPException(status_code=404, detail="KB document not found.")

    kb_doc = state.kb_docs[id]

    if state.kb_collection is not None and kb_doc.source_type == "file" and kb_doc.chunk_count > 0:
        try:
            chunk_ids = [f"{id}-chunk-{i}" for i in range(kb_doc.chunk_count)]
            state.kb_collection.delete(ids=chunk_ids)
            logger.info("[KB] Deleted %d chunks from ChromaDB for %s.", kb_doc.chunk_count, id)
        except Exception as exc:
            logger.warning("[KB] ChromaDB delete failed for %s: %s", id, exc)

    if db.kb_documents_col is not None:
        await db.kb_documents_col.delete_one({"id": id})

    del state.kb_docs[id]
    # Remove from BM25 corpus and rebuild index
    state.kb_chunks.pop(id, None)
    hybrid_retriever.build_bm25_index(state.kb_chunks)

    # ADR-052: remove wiki graph nodes for this document
    if db.wiki_entities_col is not None and db.wiki_relationships_col is not None:
        try:
            builder = WikiGraphBuilder(
                entities_col=db.wiki_entities_col,
                relationships_col=db.wiki_relationships_col,
                kb_collection=state.kb_collection,
            )
            await builder.delete_for_document(id)
        except Exception as exc:
            logger.warning("[Wiki] Graph cleanup failed for %s: %s", id, exc)

    return {"status": "success", "message": f"KB document {id} deleted."}


@router.put("/kb/documents/{id}/tags")
async def kb_update_tags(
    id: str,
    body: KBUpdateTagsRequest,
    background_tasks: BackgroundTasks,
    _token: str = Depends(require_token),
) -> dict:
    """Update tags for a Knowledge Base document."""
    if id not in state.kb_docs:
        raise HTTPException(status_code=404, detail="KB document not found.")

    clean_tags = [t.strip()[:50] for t in body.tags if t.strip()]
    if not clean_tags:
        raise HTTPException(status_code=422, detail="No valid tags after stripping whitespace.")

    kb_doc = state.kb_docs[id]
    kb_doc.tags = clean_tags

    if db.kb_documents_col is not None:
        await db.kb_documents_col.replace_one(
            {"id": id}, kb_doc.model_dump(), upsert=True
        )

    if state.kb_collection is not None:
        tags_csv = ",".join(clean_tags)
        try:
            chunk_ids = [f"{id}-chunk-{i}" for i in range(kb_doc.chunk_count)]
            state.kb_collection.update(
                ids=chunk_ids,
                metadatas=[{"tags_csv": tags_csv, "document_id": id, "filename": kb_doc.filename, "chunk_index": i} for i in range(kb_doc.chunk_count)],
            )
        except Exception as exc:
            logger.warning("[KB] ChromaDB tag update failed for %s: %s", id, exc)

    if settings.wiki_auto_build_on_upload:
        background_tasks.add_task(_run_wiki_graph_build, id, True)
        logger.info("[Wiki] Graph rebuild enqueued as background task for doc=%s.", id)

    return {
        "status": "success",
        "integration_id": id,
        "updated_tags": clean_tags,
    }


@router.get("/kb/search")
async def kb_search(
    q: str = Query(..., min_length=1, max_length=500),
    n: int = Query(5, ge=1, le=20),
) -> dict:
    """Semantic search across Knowledge Base chunks."""
    if not state.kb_collection:
        raise HTTPException(status_code=503, detail="ChromaDB is unavailable.")

    try:
        results = state.kb_collection.query(
            query_texts=[q],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}")

    docs = (results or {}).get("documents", [[]])[0]
    metas = (results or {}).get("metadatas", [[]])[0]
    distances = (results or {}).get("distances", [[]])[0]

    items: list[dict] = []
    for text, meta, dist in zip(docs, metas, distances):
        items.append(KBSearchResult(
            chunk_text=text,
            document_id=meta.get("document_id", ""),
            filename=meta.get("filename", ""),
            score=round(1.0 - dist, 4) if dist is not None else None,
        ).model_dump())

    return KBSearchResponse(
        results=items,
        query=q,
        total_results=len(items),
    ).model_dump()


@router.post("/kb/rebuild-bm25")
async def kb_rebuild_bm25(
    _token: str = Depends(require_token),
) -> dict:
    """
    Rebuild the BM25 sparse index from all current ChromaDB chunks.

    Called by the ingestion-platform after a successful ingest run so that
    newly indexed API/HTML chunks are included in hybrid retrieval immediately
    (without waiting for an integration-agent container restart).
    """
    if state.kb_collection is None:
        raise HTTPException(status_code=503, detail="ChromaDB unavailable.")
    try:
        result = state.kb_collection.get(include=["documents", "metadatas"])
        docs  = result.get("documents") or []
        metas = result.get("metadatas") or []
        new_chunks: dict[str, list[str]] = {}
        for doc_text, meta in zip(docs, metas):
            doc_id = (meta or {}).get("document_id", "unknown")
            new_chunks.setdefault(doc_id, []).append(doc_text)
        state.kb_chunks.clear()
        state.kb_chunks.update(new_chunks)
        hybrid_retriever.build_bm25_index(state.kb_chunks)
        logger.info("[BM25] Rebuilt from %d chunks (%d sources).", len(docs), len(new_chunks))
        return {"status": "ok", "chunks": len(docs), "sources": len(new_chunks)}
    except Exception as exc:
        logger.error("[BM25] Rebuild failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"BM25 rebuild failed: {exc}")


@router.get("/kb/stats")
async def kb_stats() -> dict:
    """Return Knowledge Base statistics."""
    file_types: dict[str, int] = {}
    all_tags: set[str] = set()
    total_chunks = 0

    for doc in state.kb_docs.values():
        file_types[doc.file_type] = file_types.get(doc.file_type, 0) + 1
        all_tags.update(doc.tags)
        total_chunks += doc.chunk_count

    return KBStatsResponse(
        total_documents=len(state.kb_docs),
        total_chunks=total_chunks,
        file_types=file_types,
        all_tags=sorted(all_tags),
    ).model_dump()


# ── KB Metadata v2 Enrichment (ADR-048) ──────────────────────────────────────

@router.post("/kb/enrich")
async def kb_enrich_all(
    force: bool = False,
    _token: str = Depends(require_token),
) -> dict:
    """Enrich all existing KB chunks with v2 semantic metadata.

    Reads every chunk from ChromaDB, re-classifies its metadata using the
    ADR-048 semantic_classifier, and upserts updated metadata in place.
    Embeddings are NOT recomputed.

    Query params:
        force: if true, re-enrich chunks already tagged as kb_schema_version=v2.
    """
    if state.kb_collection is None:
        raise HTTPException(status_code=503, detail="ChromaDB unavailable.")
    try:
        from services.kb_enrichment_service import enrich_all_documents
        summary = enrich_all_documents(state.kb_collection, force=force)
        return {
            "status": "ok",
            "documents_processed": summary.documents_processed,
            "documents_skipped_already_v2": summary.documents_skipped,
            "total_chunks_enriched": summary.total_chunks_enriched,
            "total_errors": summary.total_errors,
        }
    except Exception as exc:
        logger.error("[KB-Enrich] Batch enrichment failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Enrichment failed: {exc}")


@router.post("/kb/enrich/{document_id}")
async def kb_enrich_document(
    document_id: str,
    force: bool = False,
    _token: str = Depends(require_token),
) -> dict:
    """Enrich all chunks for a single KB document with v2 semantic metadata."""
    if state.kb_collection is None:
        raise HTTPException(status_code=503, detail="ChromaDB unavailable.")
    try:
        from services.kb_enrichment_service import enrich_document
        result = enrich_document(document_id, state.kb_collection, force=force)
        if not result.success:
            raise HTTPException(
                status_code=500,
                detail=f"Enrichment errors: {'; '.join(result.errors)}",
            )
        return {
            "status": "ok",
            "doc_id": result.doc_id,
            "chunks_enriched": result.chunks_processed,
            "chunks_skipped_already_v2": result.chunks_skipped_already_v2,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[KB-Enrich] Single-doc enrichment failed for %s: %s", document_id, exc)
        raise HTTPException(status_code=500, detail=f"Enrichment failed: {exc}")


# ── KB Export / Import (ADR-051) ──────────────────────────────────────────────

_ALL_SOURCE_TYPES = {"file", "url", "openapi", "html", "mcp"}


def _parse_source_types(raw: Optional[str]) -> set[str]:
    """Parse a comma-separated source_types query param into a validated set."""
    if not raw:
        return set(_ALL_SOURCE_TYPES)
    requested = {s.strip().lower() for s in raw.split(",") if s.strip()}
    unknown = requested - _ALL_SOURCE_TYPES
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source_types: {sorted(unknown)}. Allowed: {sorted(_ALL_SOURCE_TYPES)}.",
        )
    return requested


@router.get("/kb/export")
async def kb_export(
    source_types: Optional[str] = Query(
        default=None,
        description="Comma-separated list of source types to export. Defaults to all: file,url,openapi,html,mcp.",
    ),
    _token: str = Depends(require_token),
) -> StreamingResponse:
    """
    Export the Knowledge Base as a portable JSON bundle (ADR-051).

    Includes KBDocument metadata records for file/url source types and raw
    chunk text + metadata for all requested source types.  Embeddings are
    NOT exported — ChromaDB re-embeds on import.

    Query params:
        source_types: comma-separated subset of file,url,openapi,html,mcp
    """
    types = _parse_source_types(source_types)

    # ── 1. Collect KBDocument records for file + url types ─────────────────
    kb_docs_export: list[KBDocument] = [
        doc for doc in state.kb_docs.values()
        if doc.source_type in types
    ]

    # ── 2. Collect ChromaDB chunks ─────────────────────────────────────────
    chunks_export: list[KBExportChunk] = []
    if state.kb_collection is not None:
        try:
            result = state.kb_collection.get(include=["documents", "metadatas", "ids"])
            ids   = result.get("ids") or []
            texts = result.get("documents") or []
            metas = result.get("metadatas") or []
            for chunk_id, text, meta in zip(ids, texts, metas):
                chunk_source_type = (meta or {}).get("source_type", "file")
                if chunk_source_type in types:
                    chunks_export.append(KBExportChunk(
                        id=chunk_id,
                        text=text or "",
                        metadata=dict(meta or {}),
                    ))
        except Exception as exc:
            logger.warning("[KB-Export] ChromaDB read failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"ChromaDB read failed: {exc}")

    bundle = KBExportBundle(
        exported_at=_now_iso(),
        source_types_included=sorted(types),
        kb_documents=kb_docs_export,
        chunks=chunks_export,
    )

    payload = bundle.model_dump_json(indent=2).encode("utf-8")
    logger.info(
        "[KB-Export] Exported %d documents and %d chunks (types: %s).",
        len(kb_docs_export), len(chunks_export), sorted(types),
    )
    return StreamingResponse(
        iter([payload]),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="kb_export.json"'},
    )


@router.post("/kb/import")
async def kb_import(
    bundle_file: UploadFile = File(..., description="JSON bundle produced by GET /api/v1/kb/export"),
    source_types: Optional[str] = Query(
        default=None,
        description="Comma-separated source types to import. Defaults to all types present in the bundle.",
    ),
    overwrite: bool = Query(
        default=False,
        description="If true, existing documents/chunks with the same ID are replaced.",
    ),
    _token: str = Depends(require_token),
) -> dict:
    """
    Import a KB bundle produced by GET /api/v1/kb/export (ADR-051).

    Documents and chunks are upserted by ID.  By default, existing records
    are skipped; set overwrite=true to replace them.  The BM25 index is
    rebuilt after a successful import.

    Query params:
        source_types: comma-separated subset to import (default: all in bundle)
        overwrite:    replace existing records (default: false)
    """
    raw = await bundle_file.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON bundle: {exc}")

    if data.get("export_version") != "1.0":
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported bundle version: {data.get('export_version')!r}. Expected '1.0'.",
        )

    try:
        bundle = KBExportBundle.model_validate(data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Bundle validation failed: {exc}")

    types = _parse_source_types(source_types)

    docs_imported = 0
    docs_skipped = 0
    chunks_imported = 0
    chunks_skipped = 0
    errors: list[str] = []

    # ── 1. Import KBDocument records (file + url) ──────────────────────────
    for doc in bundle.kb_documents:
        if doc.source_type not in types:
            docs_skipped += 1
            continue
        if not overwrite and doc.id in state.kb_docs:
            docs_skipped += 1
            continue
        state.kb_docs[doc.id] = doc
        if db.kb_documents_col is not None:
            try:
                await db.kb_documents_col.replace_one(
                    {"id": doc.id}, doc.model_dump(), upsert=True
                )
            except Exception as exc:
                errors.append(f"MongoDB upsert failed for {doc.id}: {exc}")
        docs_imported += 1

    # ── 2. Import ChromaDB chunks ──────────────────────────────────────────
    if state.kb_collection is not None and bundle.chunks:
        ids_to_upsert: list[str] = []
        texts_to_upsert: list[str] = []
        metas_to_upsert: list[dict] = []

        if not overwrite:
            try:
                existing = state.kb_collection.get(ids=[c.id for c in bundle.chunks])
                existing_ids = set(existing.get("ids") or [])
            except Exception:
                existing_ids = set()
        else:
            existing_ids = set()

        for chunk in bundle.chunks:
            chunk_source = chunk.metadata.get("source_type", "file")
            if chunk_source not in types:
                chunks_skipped += 1
                continue
            if not overwrite and chunk.id in existing_ids:
                chunks_skipped += 1
                continue
            ids_to_upsert.append(chunk.id)
            texts_to_upsert.append(chunk.text)
            metas_to_upsert.append(chunk.metadata)

        if ids_to_upsert:
            _BATCH = 500
            for i in range(0, len(ids_to_upsert), _BATCH):
                try:
                    state.kb_collection.upsert(
                        ids=ids_to_upsert[i:i + _BATCH],
                        documents=texts_to_upsert[i:i + _BATCH],
                        metadatas=metas_to_upsert[i:i + _BATCH],
                    )
                    chunks_imported += len(ids_to_upsert[i:i + _BATCH])
                except Exception as exc:
                    errors.append(f"ChromaDB batch upsert failed (offset {i}): {exc}")

    # ── 3. Rebuild BM25 index from full ChromaDB state ─────────────────────
    if state.kb_collection is not None and (chunks_imported > 0 or docs_imported > 0):
        try:
            result = state.kb_collection.get(include=["documents", "metadatas"])
            new_chunks: dict[str, list[str]] = {}
            for doc_text, meta in zip(result.get("documents") or [], result.get("metadatas") or []):
                doc_id = (meta or {}).get("document_id", "unknown")
                new_chunks.setdefault(doc_id, []).append(doc_text)
            state.kb_chunks.clear()
            state.kb_chunks.update(new_chunks)
            hybrid_retriever.build_bm25_index(state.kb_chunks)
        except Exception as exc:
            errors.append(f"BM25 rebuild failed: {exc}")

    logger.info(
        "[KB-Import] docs_imported=%d docs_skipped=%d chunks_imported=%d chunks_skipped=%d errors=%d",
        docs_imported, docs_skipped, chunks_imported, chunks_skipped, len(errors),
    )
    return KBImportResult(
        documents_imported=docs_imported,
        documents_skipped=docs_skipped,
        chunks_imported=chunks_imported,
        chunks_skipped=chunks_skipped,
        errors=errors,
    ).model_dump()
