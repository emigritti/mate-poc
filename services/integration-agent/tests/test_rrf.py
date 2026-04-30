from services.retriever import HybridRetriever, ScoredChunk


def _mk(text, score, label="x"):
    return ScoredChunk(text=text, score=score, source_label=label, tags=[], doc_id=text)


def test_rrf_merges_by_rank_not_score():
    r = HybridRetriever()
    chroma = [_mk("a", 0.99), _mk("b", 0.50), _mk("c", 0.01)]
    bm25 = [_mk("c", 100.0), _mk("a", 50.0), _mk("d", 1.0)]
    out = r._rrf_merge(chroma, bm25, k=60)
    out_text = [c.text for c in out]
    # 'a' and 'c' appear in both lists → top
    assert set(out_text[:2]) == {"a", "c"}
    assert "b" in out_text
    assert "d" in out_text


def test_rrf_handles_empty_list():
    r = HybridRetriever()
    out = r._rrf_merge([], [_mk("x", 1.0)], k=60)
    assert [c.text for c in out] == ["x"]


def test_rrf_score_uses_inverse_rank_formula():
    r = HybridRetriever()
    chroma = [_mk("a", 0.9)]   # rank 1 → 1/61
    bm25 = [_mk("a", 5.0)]   # rank 1 → 1/61
    out = r._rrf_merge(chroma, bm25, k=60)
    assert len(out) == 1
    assert abs(out[0].score - (1 / 61 + 1 / 61)) < 1e-9
