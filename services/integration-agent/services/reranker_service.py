"""Cross-encoder reranker for the RAG pipeline (ADR-X3).

Lazy-loaded — sentence-transformers is heavy (~600 MB).  No global state until
first call.  When disabled (settings.reranker_enabled=False), callers should
short-circuit before invoking this module.
"""
from __future__ import annotations
import logging

from config import settings
from services.retriever import ScoredChunk

logger = logging.getLogger(__name__)

_model_singleton = None


def _get_model():
    global _model_singleton
    if _model_singleton is None:
        from sentence_transformers import CrossEncoder
        logger.info("[Reranker] Loading %s (lazy, first call).",
                    settings.reranker_model_name)
        _model_singleton = CrossEncoder(settings.reranker_model_name)
    return _model_singleton


def cross_encoder_rerank(
    query: str,
    chunks: list[ScoredChunk],
) -> list[ScoredChunk]:
    if not chunks:
        return chunks
    model = _get_model()
    pairs = [[query, c.text] for c in chunks]
    scores = model.predict(pairs).tolist() if hasattr(model.predict(pairs), "tolist") else list(model.predict(pairs))
    rescored = [
        ScoredChunk(
            text=c.text, score=float(s),
            source_label=c.source_label, tags=c.tags,
            doc_id=c.doc_id, semantic_type=c.semantic_type,
        )
        for c, s in zip(chunks, scores)
    ]
    return sorted(rescored, key=lambda c: c.score, reverse=True)
