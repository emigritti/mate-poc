"""KB enrichment service — ADR-048.

Reads existing chunks from ChromaDB and re-writes their metadata using the v2
schema (semantic_classifier).  Embeddings are NOT recomputed — ChromaDB upsert
with the same ID and same document text leaves the vector untouched while
updating metadata in place.

Usage:
    result = enrich_document("KB-ABCD1234", kb_collection)
    summary = enrich_all_documents(kb_collection)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from services.metadata_schema import flatten_to_chroma
from services.semantic_classifier import classify_chunk

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentResult:
    doc_id: str
    chunks_processed: int = 0
    chunks_skipped_already_v2: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


@dataclass
class BatchEnrichmentResult:
    documents_processed: int = 0
    documents_skipped: int = 0
    total_chunks_enriched: int = 0
    total_errors: int = 0
    per_doc: list[EnrichmentResult] = field(default_factory=list)


def enrich_document(
    doc_id: str,
    kb_collection: Any,
    *,
    force: bool = False,
) -> EnrichmentResult:
    """Enrich all chunks for a single document in ChromaDB.

    Args:
        doc_id:        The document_id value stored in chunk metadata.
        kb_collection: A chromadb Collection instance.
        force:         If True, re-enrich chunks that already have kb_schema_version=v2.
    """
    result = EnrichmentResult(doc_id=doc_id)

    try:
        response = kb_collection.get(
            where={"document_id": doc_id},
            include=["documents", "metadatas"],
        )
    except Exception as exc:
        result.errors.append(f"ChromaDB get failed: {exc}")
        return result

    ids       = response.get("ids") or []
    documents = response.get("documents") or []
    metadatas = response.get("metadatas") or []

    if not ids:
        logger.info("[KB-Enrich] No chunks found for doc_id=%s", doc_id)
        return result

    new_metadatas: list[dict] = []

    for chunk_id, text, meta in zip(ids, documents, metadatas):
        meta = meta or {}

        if not force and meta.get("kb_schema_version") == "v2":
            result.chunks_skipped_already_v2 += 1
            new_metadatas.append(meta)   # keep existing
            continue

        # Infer source_modality from existing metadata (ADR-044 field if present)
        source_modality = (
            meta.get("source_modality")
            or _infer_modality_from_filename(meta.get("filename", ""))
        )

        v2_meta = classify_chunk(
            text=text or "",
            chunk_type=meta.get("chunk_type", "text"),
            chunk_id=chunk_id,
            document_id=doc_id,
            source_modality=source_modality,
            chunk_index=meta.get("chunk_index", 0),
            section_header=meta.get("section_header", ""),
            page_num=meta.get("page_num", 0),
            filename=meta.get("filename", ""),
            tags=_csv_to_list(meta.get("tags_csv", "")),
        )

        flat = flatten_to_chroma(v2_meta)
        # Preserve any extra fields from old metadata that v2 doesn't cover
        # (e.g. source_type / source_code from ingestion-platform)
        for k, v in meta.items():
            if k not in flat:
                flat[k] = v

        new_metadatas.append(flat)
        result.chunks_processed += 1

    if result.chunks_processed == 0:
        logger.info("[KB-Enrich] All chunks already v2 for doc_id=%s", doc_id)
        return result

    try:
        kb_collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=new_metadatas,
        )
        logger.info(
            "[KB-Enrich] Enriched %d chunks for doc_id=%s (skipped %d already-v2)",
            result.chunks_processed,
            doc_id,
            result.chunks_skipped_already_v2,
        )
    except Exception as exc:
        result.errors.append(f"ChromaDB upsert failed: {exc}")
        result.chunks_processed = 0

    return result


def enrich_all_documents(
    kb_collection: Any,
    *,
    max_docs: Optional[int] = None,
    force: bool = False,
) -> BatchEnrichmentResult:
    """Enrich chunks for all documents in the KB collection.

    Args:
        kb_collection: A chromadb Collection instance.
        max_docs:      Optional cap on number of documents to process.
        force:         If True, re-enrich chunks already at v2.
    """
    summary = BatchEnrichmentResult()

    try:
        response = kb_collection.get(include=["metadatas"])
    except Exception as exc:
        logger.error("[KB-Enrich] Could not list KB collection: %s", exc)
        return summary

    metadatas = response.get("metadatas") or []

    # Collect unique document IDs
    doc_ids: list[str] = []
    seen: set[str] = set()
    for meta in metadatas:
        doc_id = (meta or {}).get("document_id", "")
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            doc_ids.append(doc_id)

    if max_docs is not None:
        doc_ids = doc_ids[:max_docs]

    logger.info("[KB-Enrich] Starting batch enrichment for %d documents", len(doc_ids))

    for doc_id in doc_ids:
        result = enrich_document(doc_id, kb_collection, force=force)
        summary.per_doc.append(result)
        summary.documents_processed += 1
        summary.total_chunks_enriched += result.chunks_processed
        summary.total_errors += len(result.errors)

        if result.chunks_skipped_already_v2 > 0 and result.chunks_processed == 0:
            summary.documents_skipped += 1

    logger.info(
        "[KB-Enrich] Batch complete: %d docs, %d chunks enriched, %d errors",
        summary.documents_processed,
        summary.total_chunks_enriched,
        summary.total_errors,
    )
    return summary


# ── Helpers ───────────────────────────────────────────────────────────────────

def _csv_to_list(csv: str) -> list[str]:
    if not csv:
        return []
    return [t.strip() for t in csv.split(",") if t.strip()]


def _infer_modality_from_filename(filename: str) -> str:
    if not filename:
        return "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    mapping = {
        "pdf": "pdf", "docx": "docx", "doc": "docx",
        "xlsx": "xlsx", "xls": "xlsx",
        "pptx": "pptx", "ppt": "pptx",
        "md": "md", "txt": "txt",
        "png": "image", "jpg": "image", "jpeg": "image",
        "svg": "svg", "html": "html",
    }
    return mapping.get(ext, "unknown")
