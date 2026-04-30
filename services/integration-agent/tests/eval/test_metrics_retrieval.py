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


def test_recall_at_k_capped_when_relevant_exceeds_k():
    """Denominator is capped at k — perfect retrieval at k=2 with 5 relevant items returns 1.0."""
    retrieved = ["a", "b", "c", "d", "e"]
    relevant = {"a", "b", "x", "y", "z"}
    # Top-2 contains 2 of the relevant items → 2/min(5,2) = 2/2 = 1.0
    assert recall_at_k(retrieved, relevant, k=2) == 1.0


def test_ndcg_at_k_imperfect_order():
    """Catches discount-formula regressions: hand-computed expected ~0.6934."""
    # retrieved = [x, a, b], relevant = {a, b}, k=3
    # DCG  = 0/log2(2) + 1/log2(3) + 1/log2(4) = 0 + 0.6309 + 0.5    = 1.1309
    # IDCG = 1/log2(2) + 1/log2(3)             = 1.0   + 0.6309      = 1.6309
    # NDCG = 1.1309 / 1.6309 ≈ 0.6934
    retrieved = ["x", "a", "b"]
    relevant = {"a", "b"}
    assert ndcg_at_k(retrieved, relevant, k=3) == pytest.approx(0.6934, abs=1e-3)


def test_mrr_mixed_match_and_miss():
    """Catches MRR averaging bugs."""
    queries = [
        (["a"], {"a"}),       # rank 1 → 1.0
        (["b"], {"x"}),       # no match → 0.0
    ]
    # mean = 0.5
    assert mrr(queries) == pytest.approx(0.5)
