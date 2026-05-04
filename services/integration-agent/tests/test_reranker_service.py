from unittest.mock import MagicMock
from services.reranker_service import cross_encoder_rerank
from services.retriever import ScoredChunk


def _mk(text, score, doc_id=None):
    return ScoredChunk(
        text=text, score=score, source_label="x", tags=[], doc_id=doc_id or text,
    )


def test_cross_encoder_rerank_reorders_by_predicted_score(monkeypatch):
    fake = MagicMock()
    fake.predict.return_value = [0.1, 0.9, 0.5]
    monkeypatch.setattr("services.reranker_service._get_model", lambda: fake)

    chunks = [_mk("a", 0.5), _mk("b", 0.3), _mk("c", 0.8)]
    out = cross_encoder_rerank("query", chunks)
    assert [c.text for c in out] == ["b", "c", "a"]


def test_cross_encoder_rerank_preserves_doc_id_and_label(monkeypatch):
    fake = MagicMock()
    fake.predict.return_value = [0.5]
    monkeypatch.setattr("services.reranker_service._get_model", lambda: fake)

    src = ScoredChunk(text="x", score=0.1, source_label="kb", tags=["t"], doc_id="d-1")
    out = cross_encoder_rerank("q", [src])
    assert out[0].doc_id == "d-1"
    assert out[0].source_label == "kb"


def test_cross_encoder_rerank_handles_empty_input(monkeypatch):
    monkeypatch.setattr("services.reranker_service._get_model", lambda: None)
    assert cross_encoder_rerank("q", []) == []
