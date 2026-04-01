"""
Hybrid Retriever — BM25 + ChromaDB dense retrieval with multi-query expansion.

Phase 2 — R8 (multi-query expansion), R9 (threshold + TF-IDF re-rank + BM25),
           R12 (tag-based result preference via Python post-filter).

ADR-027: BM25 Hybrid Retrieval (rank_bm25 + ensemble scoring).
ADR-028: Multi-Query Expansion 2+2 (2 template + 2 LLM variants).
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Callable

from rank_bm25 import BM25Plus
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config import settings
from services.llm_service import generate_with_ollama, llm_overrides

logger = logging.getLogger(__name__)

# Metadata field used to store comma-separated tags on every ChromaDB document.
# Defined as a constant to prevent typo-based silent misses in tag filtering.
TAGS_CSV_FIELD = "tags_csv"


@dataclass
class ScoredChunk:
    """A retrieved text chunk with its relevance score and source metadata."""
    text: str
    score: float
    source_label: str   # "approved" | "kb_document" | "ingestion_openapi" | "ingestion_html" | "kb_url"
    tags: list[str] = field(default_factory=list)
    doc_id: str = ""    # document_id from ChromaDB metadata (for attribution)


class HybridRetriever:
    """
    Combines ChromaDB dense retrieval with BM25 sparse retrieval.

    Pipeline (per call to retrieve()):
      1. Query expansion: 2 template + 2 LLM variants (R8 / ADR-028)
      2. ChromaDB query: parallel, $or tag filter, include distances (R12)
      3. BM25 query: in-memory index of KB file chunks (ADR-027)
      4. Ensemble merge: weighted score combination (0.6 dense / 0.4 sparse)
      5. Distance threshold filter (R9)
      6. TF-IDF cosine re-rank (R9)
      7. Top-K selection
    """

    def __init__(self) -> None:
        self._bm25: BM25Plus | None = None
        self._bm25_docs: list[str] = []
        self._bm25_ids: list[str] = []

    # ── BM25 Index ────────────────────────────────────────────────────────────

    def build_bm25_index(self, kb_chunks: dict[str, list[str]]) -> None:
        """Build BM25 in-memory index from KB chunk corpus.

        Args:
            kb_chunks: dict mapping doc_id → list of chunk texts.
                       Populated from state.kb_chunks (loaded from ChromaDB at startup).

        Called at startup by main.py lifespan and after every KB upload/delete.
        """
        all_texts: list[str] = []
        all_ids: list[str] = []

        for doc_id, chunks in kb_chunks.items():
            for chunk in chunks:
                all_texts.append(chunk)
                all_ids.append(doc_id)

        if not all_texts:
            self._bm25 = None
            self._bm25_docs = []
            self._bm25_ids = []
            logger.info("[BM25] No KB chunks — index cleared.")
            return

        tokenized = [t.lower().split() for t in all_texts]
        self._bm25 = BM25Plus(tokenized)
        self._bm25_docs = all_texts
        self._bm25_ids = all_ids
        logger.info("[BM25] Index built: %d chunks across %d documents.", len(all_texts), len(kb_chunks))

    # ── Query Expansion (R8 / ADR-028) ───────────────────────────────────────

    async def _expand_queries(
        self,
        query_text: str,
        tags: list[str],
        source: str,
        target: str,
        category: str,
        *,
        log_fn: Callable[[str], None] | None = None,
    ) -> list[str]:
        """Generate 2 template + up to 2 LLM query variants.

        Template variants are always generated (deterministic, zero latency).
        LLM variants are attempted using tag_llm settings (lightweight call).
        If LLM call fails for any reason, only template variants are used.
        """
        _log = log_fn or (lambda msg: logger.info(msg))

        variants: list[str] = [
            query_text,
            f"{source} to {target} {category} integration pattern",
        ]

        prompt = (
            f'Given this integration query: "{query_text[:500]}"\n'
            "Generate 2 alternative phrasings:\n"
            "1. A technical systems integration perspective\n"
            "2. A business process perspective\n"
            'Reply with a JSON array only: ["technical variant", "business variant"]'
        )
        try:
            raw = await generate_with_ollama(
                prompt,
                num_predict=llm_overrides.get("tag_num_predict", settings.tag_num_predict),
                timeout=llm_overrides.get("tag_timeout_seconds", settings.tag_timeout_seconds),
                temperature=0.3,
                log_fn=log_fn,
            )
            match = re.search(r"\[.*?\]", raw, re.DOTALL)
            if match:
                llm_variants = json.loads(match.group())
                if isinstance(llm_variants, list):
                    valid = [str(v).strip() for v in llm_variants[:2] if str(v).strip()]
                    variants.extend(valid)
                    _log(f"[RAG] Query expansion: {len(variants)} variants (2 template + {len(valid)} LLM)")
        except Exception as exc:
            _log(f"[RAG] Query expansion LLM unavailable — using 2 template variants: {exc}")

        return variants

    # ── Tag Filter (R12) ──────────────────────────────────────────────────────

    @staticmethod
    def _tags_match_meta(meta: dict | None, tags: list[str]) -> bool:
        """Return True if any tag appears as a substring in meta[TAGS_CSV_FIELD].

        Used as a Python post-filter replacing the unsupported ChromaDB
        $contains metadata operator (R12 / ADR-019).
        """
        if not tags:
            return True
        tags_str = (meta or {}).get(TAGS_CSV_FIELD, "")
        return any(t in tags_str for t in tags)

    # ── ChromaDB Query ────────────────────────────────────────────────────────

    def _query_chroma(
        self,
        queries: list[str],
        collection,
        tags: list[str],
    ) -> list[ScoredChunk]:
        """Query ChromaDB with all query variants; deduplicate by doc_id.

        Tag filtering is applied as a Python post-filter via _tags_match_meta()
        (ChromaDB 0.5.x metadata 'where' does not support $contains on string
        fields).  When tags are provided, tag-matched chunks are returned;
        falls back to all results if no chunk matches the requested tags.
        """
        if not collection:
            return []

        seen: dict[str, ScoredChunk] = {}   # all results, deduplicated by doc_id
        matched_ids: set[str] = set()        # doc_ids whose tags_csv matched (R12)
        n = settings.rag_n_results_per_query

        for query in queries:
            try:
                results = collection.query(
                    query_texts=[query],
                    n_results=n,
                    include=["documents", "distances", "metadatas"],
                )
                docs  = (results.get("documents") or [[]])[0]
                dists = (results.get("distances")  or [[]])[0]
                metas = (results.get("metadatas")  or [[]])[0]

                for doc, dist, meta in zip(docs, dists, metas):
                    score = 1.0 / (1.0 + dist)   # metric-agnostic distance → similarity score
                    m = meta or {}
                    doc_id = m.get("document_id", doc[:50])
                    # Derive source label from ingestion-platform metadata when present.
                    source_type = m.get("source_type", "")
                    if source_type:
                        label = f"ingestion_{source_type}"    # e.g. "ingestion_openapi"
                    else:
                        label = "kb_document"
                    if doc_id not in seen or seen[doc_id].score < score:
                        seen[doc_id] = ScoredChunk(
                            text=doc, score=score, source_label=label,
                            tags=tags, doc_id=doc_id,
                        )
                    if tags and self._tags_match_meta(meta, tags):
                        matched_ids.add(doc_id)

            except Exception as exc:
                logger.warning("[RAG] ChromaDB query failed for variant: %s", exc)

        # Prefer tag-matched chunks (membership tracked separately from scores);
        # fall back to all results when no chunk matches the requested tags.
        if tags and matched_ids:
            return [seen[doc_id] for doc_id in matched_ids if doc_id in seen]
        return list(seen.values())

    # ── BM25 Query ────────────────────────────────────────────────────────────

    def _query_bm25(self, queries: list[str]) -> list[ScoredChunk]:
        """Query BM25 index with all query variants; return deduplicated chunks."""
        if not self._bm25 or not self._bm25_docs:
            return []

        seen: dict[int, ScoredChunk] = {}

        for query in queries:
            tokens = query.lower().split()
            scores = self._bm25.get_scores(tokens)
            for idx, score in enumerate(scores):
                if score <= 0.0:
                    continue
                if idx not in seen or seen[idx].score < score:
                    seen[idx] = ScoredChunk(
                        text=self._bm25_docs[idx],
                        score=float(score),
                        source_label="kb_file",
                        tags=[],
                    )

        return list(seen.values())

    # ── Ensemble Merge (ADR-027) ──────────────────────────────────────────────

    def _ensemble_merge(
        self,
        chroma_chunks: list[ScoredChunk],
        bm25_chunks: list[ScoredChunk],
    ) -> list[ScoredChunk]:
        """Weighted merge of ChromaDB (dense) and BM25 (sparse) results.

        Weights: Chroma = (1 - rag_bm25_weight), BM25 = rag_bm25_weight.
        Scores are normalised within each set before weighting.
        Chunks appearing in both sets have their scores summed.
        """
        chroma_w = 1.0 - settings.rag_bm25_weight
        bm25_w   = settings.rag_bm25_weight

        def _normalize(chunks: list[ScoredChunk], weight: float) -> list[ScoredChunk]:
            if not chunks:
                return []
            max_s = max(c.score for c in chunks) or 1.0
            return [
                ScoredChunk(
                    text=c.text,
                    score=(c.score / max_s) * weight,
                    source_label=c.source_label,
                    tags=c.tags,
                    doc_id=c.doc_id,
                )
                for c in chunks
            ]

        merged: dict[str, ScoredChunk] = {}

        for chunk in _normalize(chroma_chunks, chroma_w):
            key = chunk.text[:100]
            if key not in merged or merged[key].score < chunk.score:
                merged[key] = chunk

        for chunk in _normalize(bm25_chunks, bm25_w):
            key = chunk.text[:100]
            if key not in merged:
                merged[key] = chunk
            else:
                existing = merged[key]
                merged[key] = ScoredChunk(
                    text=existing.text,
                    score=existing.score + chunk.score,
                    source_label=existing.source_label,
                    tags=existing.tags,
                    doc_id=existing.doc_id,
                )

        return list(merged.values())

    # ── Threshold Filter (R9) ─────────────────────────────────────────────────

    def _apply_threshold(self, chunks: list[ScoredChunk]) -> list[ScoredChunk]:
        """Discard chunks below the relevance threshold.

        settings.rag_distance_threshold is a ChromaDB distance (0 = perfect, 2 = worst).
        After ensemble normalisation, scores are in [0, 1].
        We keep chunks where score >= 1/(1 + threshold).
        """
        min_score = 1.0 / (1.0 + settings.rag_distance_threshold)
        filtered = [c for c in chunks if c.score >= min_score]
        if len(filtered) < len(chunks):
            logger.info("[RAG] Threshold (%.2f): %d → %d chunks.", min_score, len(chunks), len(filtered))
        return filtered

    # ── TF-IDF Re-rank (R9) ──────────────────────────────────────────────────

    def _tfidf_rerank(
        self,
        chunks: list[ScoredChunk],
        query: str,
    ) -> list[ScoredChunk]:
        """Re-rank chunks by TF-IDF cosine similarity to the original query.

        Final score = 0.5 × ensemble_score + 0.5 × tfidf_cosine_similarity.
        Falls back to score-only ordering if TF-IDF fails.
        """
        if len(chunks) <= 1:
            return chunks

        try:
            texts = [query] + [c.text for c in chunks]
            vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
            matrix = vectorizer.fit_transform(texts)
            sims = cosine_similarity(matrix[0], matrix[1:])[0]

            reranked = [
                ScoredChunk(
                    text=c.text,
                    score=(c.score * 0.5) + (float(sim) * 0.5),
                    source_label=c.source_label,
                    tags=c.tags,
                )
                for c, sim in zip(chunks, sims)
            ]
            return sorted(reranked, key=lambda c: c.score, reverse=True)

        except Exception as exc:
            logger.warning("[RAG] TF-IDF re-rank failed, using score order: %s", exc)
            return sorted(chunks, key=lambda c: c.score, reverse=True)

    # ── Public API ────────────────────────────────────────────────────────────

    async def retrieve(
        self,
        query_text: str,
        tags: list[str],
        collection,
        source: str = "",
        target: str = "",
        category: str = "",
        *,
        log_fn: Callable[[str], None] | None = None,
    ) -> list[ScoredChunk]:
        """Full retrieval pipeline for a single integration.

        Returns top-K ScoredChunks ordered by final relevance score.
        """
        _log = log_fn or (lambda msg: logger.info(msg))

        queries = await self._expand_queries(
            query_text, tags, source, target, category, log_fn=log_fn
        )

        chroma_chunks = self._query_chroma(queries, collection, tags)
        bm25_chunks   = self._query_bm25(queries)
        _log(f"[RAG] Retrieved: {len(chroma_chunks)} Chroma + {len(bm25_chunks)} BM25 chunks")

        merged   = self._ensemble_merge(chroma_chunks, bm25_chunks)
        filtered = self._apply_threshold(merged)
        reranked = self._tfidf_rerank(filtered, query_text)
        top_k    = reranked[:settings.rag_top_k_chunks]

        _log(f"[RAG] Final: {len(top_k)} chunks after ensemble+threshold+rerank")
        return top_k

    # ── RAPTOR-lite Summary Retrieval (ADR-032) ───────────────────────────────

    async def retrieve_summaries(
        self,
        query_text: str,
        tags: list[str] | None,
        summaries_col,
        *,
        top_k: int = 3,
    ) -> list[ScoredChunk]:
        """Retrieve document-level summaries from the RAPTOR-lite summaries collection.

        Dense-only retrieval (no BM25) — summaries are longer, descriptive text
        that benefits more from semantic embedding than keyword matching.

        Returns at most `top_k` ScoredChunks with source_label='summary'.
        Returns [] gracefully when summaries_col is None (collection unavailable).
        Tag filtering reuses _tags_match_meta (same logic as _query_chroma).
        """
        if summaries_col is None:
            return []

        try:
            raw = summaries_col.query(
                query_texts=[query_text],
                n_results=top_k * 2,  # over-fetch to allow for tag filtering
                include=["documents", "distances", "metadatas"],
            )
        except Exception as exc:
            logger.warning("[RAG] retrieve_summaries query failed: %s", exc)
            return []

        docs      = (raw.get("documents") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]
        metadatas = (raw.get("metadatas") or [[]])[0]

        results: list[ScoredChunk] = []
        for text, dist, meta in zip(docs, distances, metadatas):
            if tags and not self._tags_match_meta(meta, tags):
                continue
            score = 1.0 / (1.0 + dist) if dist is not None else 0.0
            results.append(ScoredChunk(
                text=text,
                score=score,
                source_label="summary",
                tags=[t.strip() for t in (meta or {}).get(TAGS_CSV_FIELD, "").split(",") if t.strip()],
            ))

        results.sort(key=lambda c: c.score, reverse=True)
        return results[:top_k]


# ── Module-level singleton ────────────────────────────────────────────────────
# Initialized at startup in main.py lifespan. Routers import this instance.
hybrid_retriever = HybridRetriever()
