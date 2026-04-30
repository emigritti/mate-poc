"""Retrieval metrics for the RAG eval harness.

Pure functions, no external dependencies — easy to unit test.
"""
import math
from typing import Iterable


def recall_at_k(
    retrieved: list[str],
    relevant: set[str],
    k: int,
) -> float:
    """Fraction of relevant items present in the top-k retrieved list.

    Denominator is min(len(relevant), k) — consistent with NDCG@k IDCG.
    """
    if k <= 0:
        return 0.0
    if not relevant:
        return 0.0
    top_k = set(retrieved[:k])
    return len(top_k & relevant) / min(len(relevant), k)


def mrr(queries: Iterable[tuple[list[str], set[str]]]) -> float:
    """Mean Reciprocal Rank across multiple queries.

    Each query is a tuple of (retrieved_ordered_ids, relevant_ids_set).
    """
    queries = list(queries)
    if not queries:
        return 0.0
    total = 0.0
    for retrieved, relevant in queries:
        for i, item in enumerate(retrieved, start=1):
            if item in relevant:
                total += 1.0 / i
                break
    return total / len(queries)


def ndcg_at_k(
    retrieved: list[str],
    relevant: set[str],
    k: int,
) -> float:
    """Normalized Discounted Cumulative Gain at rank k.

    Binary relevance: gain = 1 if item in relevant, else 0.
    """
    if k <= 0:
        return 0.0
    if not relevant:
        return 0.0
    dcg = sum(
        (1.0 if item in relevant else 0.0) / math.log2(i + 1)
        for i, item in enumerate(retrieved[:k], start=1)
    )
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0
