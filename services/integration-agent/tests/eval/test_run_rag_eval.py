from pathlib import Path
import yaml
from tests.eval.run_rag_eval import (
    load_golden_questions, render_report, compare_runs,
)


def test_load_golden_questions(tmp_path):
    yaml_path = tmp_path / "gq.yaml"
    yaml_path.write_text(yaml.safe_dump([
        {"id": "gq-x", "query": "test", "intent": "overview",
         "expected_chunk_keywords": ["a"], "expected_doc_ids": [],
         "expected_answer_must_contain": ["x"]},
    ]))
    questions = load_golden_questions(yaml_path)
    assert len(questions) == 1
    assert questions[0]["id"] == "gq-x"


def test_render_report_includes_metrics():
    metrics = {"recall@5": 0.42, "mrr": 0.31, "latency_p50_ms": 230}
    md = render_report(label="baseline", metrics=metrics, n_queries=5)
    assert "recall@5" in md
    assert "0.42" in md
    assert "baseline" in md


def test_compare_runs_computes_delta():
    baseline = {"recall@5": 0.42, "mrr": 0.31}
    current  = {"recall@5": 0.61, "mrr": 0.49}
    md = compare_runs("baseline", baseline, "adr-x2", current)
    assert "+45" in md or "+0.19" in md  # +45% or +0.19 absolute
