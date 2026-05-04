from unittest.mock import AsyncMock, MagicMock
from tests.eval.runner import execute_pipeline


def test_execute_pipeline_computes_recall_and_mrr(monkeypatch):
    fake_questions = [
        {"id": "gq-1", "query": "q1", "intent": "overview",
         "expected_chunk_keywords": ["alpha"],
         "expected_doc_ids": ["doc-1"],
         "expected_answer_must_contain": ["alpha"]},
    ]

    async def fake_retrieve(*args, **kwargs):
        return [
            MagicMock(text="alpha beta", doc_id="doc-1", score=0.9),
            MagicMock(text="other",     doc_id="doc-2", score=0.5),
        ]

    monkeypatch.setattr("tests.eval.runner._retrieve_for_query", fake_retrieve)

    metrics = execute_pipeline(fake_questions)

    assert metrics["recall@5"] == 1.0
    assert metrics["mrr"] >= 0.99
    assert "latency_p50_ms" in metrics
