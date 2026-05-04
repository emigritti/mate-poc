"""Glues golden questions → retriever → metrics."""
from __future__ import annotations
import asyncio
import time
from typing import Any

from tests.eval.metrics.retrieval import recall_at_k, mrr, ndcg_at_k
from tests.eval.metrics.faithfulness import substring_faithfulness


async def _retrieve_for_query(query: str, intent: str) -> list:
    """Real implementation — overridden in tests."""
    from services.retriever import hybrid_retriever
    from state import kb_collection
    return await hybrid_retriever.retrieve(
        query_text=query, tags=[], collection=kb_collection, intent=intent,
    )


async def _run_async(questions: list[dict]) -> dict[str, Any]:
    """Run all golden questions through the retriever and aggregate metrics.

    Note: faithfulness_substring measures whether the top-3 retrieved chunks
    contain the expected_answer_must_contain tokens — it is a retrieval-coverage
    proxy, NOT end-to-end LLM-answer faithfulness.  The latter requires an LLM
    in the loop (see llm_judge_faithfulness, opt-in via ANTHROPIC_API_KEY).
    """
    mrr_inputs: list[tuple[list[str], set[str]]] = []
    recall5_scores: list[float] = []
    ndcg5_scores: list[float] = []
    faithfulness_scores: list[float] = []
    latencies_ms: list[float] = []

    for q in questions:
        t0 = time.perf_counter()
        chunks = await _retrieve_for_query(q["query"], q.get("intent", ""))
        latencies_ms.append((time.perf_counter() - t0) * 1000)

        retrieved_ids = [c.doc_id for c in chunks if getattr(c, "doc_id", "")]
        relevant = set(q.get("expected_doc_ids") or [])
        if relevant:
            recall5_scores.append(recall_at_k(retrieved_ids, relevant, k=5))
            ndcg5_scores.append(ndcg_at_k(retrieved_ids, relevant, k=5))
            mrr_inputs.append((retrieved_ids, relevant))
        # Keyword-based recall fallback when expected_doc_ids is empty
        else:
            keywords = q.get("expected_chunk_keywords") or []
            hits = sum(
                1 for kw in keywords
                if any(kw.lower() in c.text.lower() for c in chunks)
            )
            recall5_scores.append(hits / len(keywords) if keywords else 0.0)

        # End-to-end faithfulness: stitch chunk text as proxy answer
        answer = " ".join(c.text for c in chunks[:3])
        must = q.get("expected_answer_must_contain") or []
        if must:
            faithfulness_scores.append(substring_faithfulness(answer, must))

    return {
        "recall@5": sum(recall5_scores) / len(recall5_scores) if recall5_scores else 0.0,
        "mrr": mrr(mrr_inputs) if mrr_inputs else 0.0,
        "ndcg@5": sum(ndcg5_scores) / len(ndcg5_scores) if ndcg5_scores else 0.0,
        "faithfulness_substring": (
            sum(faithfulness_scores) / len(faithfulness_scores)
            if faithfulness_scores else 0.0
        ),
        "latency_p50_ms": sorted(latencies_ms)[len(latencies_ms) // 2] if latencies_ms else 0.0,
        "latency_p95_ms": sorted(latencies_ms)[int(len(latencies_ms) * 0.95)] if latencies_ms else 0.0,
        "n_queries": len(questions),
    }


def execute_pipeline(questions: list[dict]) -> dict[str, Any]:
    return asyncio.run(_run_async(questions))
