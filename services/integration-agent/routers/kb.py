"""
Knowledge Base Router — upload, list, delete, tags, search, stats, add-url.

Extracted from main.py (R15).
"""

import logging
import secrets
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

import db
import state
from auth import require_token
from config import settings
from document_parser import (
    DocumentParseError,
    detect_file_type,
    parse_document,
    semantic_chunk,
)
from log_helpers import log_agent
from services.retriever import hybrid_retriever
from schemas import (
    KBAddUrlRequest,
    KBDocument,
    KBSearchResponse,
    KBSearchResult,
    KBStatsResponse,
    KBUpdateTagsRequest,
    KBUploadResponse,
)
from services.tag_service import suggest_kb_tags_via_llm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["knowledge-base"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/kb/upload")
async def kb_upload(
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
        result = parse_document(content, filename, file.content_type)
    except DocumentParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    chunks = semantic_chunk(
        result.text,
        chunk_size=settings.kb_chunk_size,
        chunk_overlap=settings.kb_chunk_overlap,
    )
    if not chunks:
        raise HTTPException(status_code=422, detail="No text could be extracted from the file.")

    auto_tags = await suggest_kb_tags_via_llm(result.text[:1000], filename, log_fn=log_agent)
    log_agent(f"[KB] Auto-tags for '{filename}': {auto_tags}")

    doc_id = f"KB-{uuid.uuid4().hex[:8].upper()}"
    if state.kb_collection is not None:
        tags_csv = ",".join(auto_tags)
        try:
            state.kb_collection.upsert(
                documents=[c.text for c in chunks],
                metadatas=[
                    {
                        "document_id": doc_id,
                        "filename": filename,
                        "chunk_index": c.index,
                        "tags_csv": tags_csv,
                    }
                    for c in chunks
                ],
                ids=[f"{doc_id}-chunk-{c.index}" for c in chunks],
            )
            logger.info("[KB] Stored %d chunks in ChromaDB for %s.", len(chunks), doc_id)
        except Exception as exc:
            logger.warning("[KB] ChromaDB upsert failed for %s: %s", doc_id, exc)
            raise HTTPException(status_code=500, detail=f"Vector store failed: {exc}")
    else:
        raise HTTPException(status_code=503, detail="ChromaDB is unavailable.")

    kb_doc = KBDocument(
        id=doc_id,
        filename=filename,
        file_type=result.file_type,
        file_size_bytes=len(content),
        tags=auto_tags,
        chunk_count=len(chunks),
        content_preview=result.text[:500],
        uploaded_at=_now_iso(),
    )
    state.kb_docs[doc_id] = kb_doc
    # Update BM25 corpus and rebuild index (Phase 2 / ADR-027)
    state.kb_chunks[doc_id] = [c.text for c in chunks]
    hybrid_retriever.build_bm25_index(state.kb_chunks)
    if db.kb_documents_col is not None:
        await db.kb_documents_col.replace_one(
            {"id": doc_id}, kb_doc.model_dump(), upsert=True
        )

    log_agent(f"[KB] Document '{filename}' imported as {doc_id} ({len(chunks)} chunks).")
    return KBUploadResponse(
        id=doc_id,
        filename=filename,
        file_type=result.file_type,
        chunks_created=len(chunks),
        auto_tags=auto_tags,
    ).model_dump()


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
    return {"status": "success", "message": f"KB document {id} deleted."}


@router.put("/kb/documents/{id}/tags")
async def kb_update_tags(
    id: str,
    body: KBUpdateTagsRequest,
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
