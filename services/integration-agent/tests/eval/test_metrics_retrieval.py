import pytest
from tests.eval.metrics.retrieval import recall_at_k, mrr, ndcg_at_k


def test_recall_at_k_full_match():
    retrieved = ["a", "b", "c", "d", "e"]
    relevant = {"a", "c"}
    assert recall_at_k(retrieved, relevant, k=5) == 1.0


def test_recall_at_k_partial_at_cutoff():
    retrieved = ["a", "b", "c", "d", "e"]
    relevant = {"a", "x"}
    assert recall_at_k(retrieved, relevant, k=2) == 0.5


def test_recall_at_k_empty_relevant_returns_zero():
    assert recall_at_k(["a", "b"], set(), k=2) == 0.0


def test_mrr_first_position():
    queries = [
        (["a", "b", "c"], {"a"}),
        (["x", "y", "z"], {"y"}),
    ]
    # 1/1 + 1/2 = 1.5; mean = 0.75
    assert mrr(queries) == pytest.approx(0.75)


def test_mrr_no_match_returns_zero_for_query():
    queries = [
        (["a", "b"], {"x"}),
    ]
    assert mrr(queries) == 0.0


def test_ndcg_at_k_perfect_order():
    retrieved = ["a", "b", "c"]
    relevant = {"a", "b", "c"}
    assert ndcg_at_k(retrieved, relevant, k=3) == pytest.approx(1.0)


def test_ndcg_at_k_zero_relevant():
    assert ndcg_at_k(["a", "b"], set(), k=2) == 0.0
