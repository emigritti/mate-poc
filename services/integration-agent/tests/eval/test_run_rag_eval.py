from pathlib import Path
import yaml
import pytest
from tests.eval.run_rag_eval import (
    load_golden_questions, render_report, compare_runs,
    list_domains, load_domain, _merge_domains,
)


# ── load_golden_questions — legacy path ───────────────────────────────────────

def test_load_golden_questions_from_explicit_path(tmp_path):
    yaml_path = tmp_path / "gq.yaml"
    yaml_path.write_text(yaml.safe_dump([
        {"id": "gq-x", "query": "test", "intent": "overview",
         "expected_chunk_keywords": ["a"], "expected_doc_ids": [],
         "expected_answer_must_contain": ["x"]},
    ]))
    questions = load_golden_questions(path=yaml_path)
    assert len(questions) == 1
    assert questions[0]["id"] == "gq-x"


# ── load_domain ───────────────────────────────────────────────────────────────

def test_load_domain_returns_questions(tmp_path, monkeypatch):
    domains_dir = tmp_path / "domains"
    domains_dir.mkdir()
    (domains_dir / "mydom.yaml").write_text(yaml.safe_dump([
        {"id": "d-001", "query": "q1", "intent": "overview",
         "expected_chunk_keywords": [], "expected_doc_ids": [],
         "expected_answer_must_contain": []},
    ]))
    monkeypatch.setattr("tests.eval.run_rag_eval.DOMAINS_DIR", domains_dir)
    questions = load_domain("mydom")
    assert len(questions) == 1
    assert questions[0]["id"] == "d-001"


def test_load_domain_raises_for_missing_domain(tmp_path, monkeypatch):
    monkeypatch.setattr("tests.eval.run_rag_eval.DOMAINS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="nonexistent"):
        load_domain("nonexistent")


# ── list_domains ──────────────────────────────────────────────────────────────

def test_list_domains_returns_sorted_stems(tmp_path, monkeypatch):
    monkeypatch.setattr("tests.eval.run_rag_eval.DOMAINS_DIR", tmp_path)
    (tmp_path / "commerce.yaml").touch()
    (tmp_path / "plm_pim_dam.yaml").touch()
    (tmp_path / "mulesoft.yaml").touch()
    result = list_domains()
    assert result == ["commerce", "mulesoft", "plm_pim_dam"]


def test_list_domains_returns_empty_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tests.eval.run_rag_eval.DOMAINS_DIR", tmp_path / "nonexistent"
    )
    assert list_domains() == []


# ── load_golden_questions — domain selection ──────────────────────────────────

def _make_domains_dir(tmp_path: Path) -> Path:
    d = tmp_path / "domains"
    d.mkdir()
    (d / "alpha.yaml").write_text(yaml.safe_dump([
        {"id": "a-001", "query": "qa1", "intent": "overview",
         "expected_chunk_keywords": [], "expected_doc_ids": [],
         "expected_answer_must_contain": []},
        {"id": "a-002", "query": "qa2", "intent": "errors",
         "expected_chunk_keywords": [], "expected_doc_ids": [],
         "expected_answer_must_contain": []},
    ]))
    (d / "beta.yaml").write_text(yaml.safe_dump([
        {"id": "b-001", "query": "qb1", "intent": "architecture",
         "expected_chunk_keywords": [], "expected_doc_ids": [],
         "expected_answer_must_contain": []},
    ]))
    return d


def test_load_golden_questions_single_domain(tmp_path, monkeypatch):
    domains_dir = _make_domains_dir(tmp_path)
    monkeypatch.setattr("tests.eval.run_rag_eval.DOMAINS_DIR", domains_dir)
    questions = load_golden_questions(domain="alpha")
    assert len(questions) == 2
    assert questions[0]["id"] == "a-001"


def test_load_golden_questions_multiple_domains(tmp_path, monkeypatch):
    domains_dir = _make_domains_dir(tmp_path)
    monkeypatch.setattr("tests.eval.run_rag_eval.DOMAINS_DIR", domains_dir)
    questions = load_golden_questions(domains=["alpha", "beta"])
    assert len(questions) == 3
    ids = {q["id"] for q in questions}
    assert ids == {"a-001", "a-002", "b-001"}


def test_load_golden_questions_all_domains(tmp_path, monkeypatch):
    domains_dir = _make_domains_dir(tmp_path)
    monkeypatch.setattr("tests.eval.run_rag_eval.DOMAINS_DIR", domains_dir)
    questions = load_golden_questions(domain="all")
    assert len(questions) == 3


def test_merge_domains_deduplicates_by_id(tmp_path, monkeypatch):
    domains_dir = _make_domains_dir(tmp_path)
    # Add a duplicate id to beta
    (domains_dir / "beta.yaml").write_text(yaml.safe_dump([
        {"id": "a-001", "query": "duplicate", "intent": "overview",
         "expected_chunk_keywords": [], "expected_doc_ids": [],
         "expected_answer_must_contain": []},
        {"id": "b-001", "query": "qb1", "intent": "architecture",
         "expected_chunk_keywords": [], "expected_doc_ids": [],
         "expected_answer_must_contain": []},
    ]))
    monkeypatch.setattr("tests.eval.run_rag_eval.DOMAINS_DIR", domains_dir)
    questions = load_golden_questions(domains=["alpha", "beta"])
    ids = [q["id"] for q in questions]
    assert ids.count("a-001") == 1  # deduped
    assert len(questions) == 3


# ── CLI — --list-domains ──────────────────────────────────────────────────────

def test_cli_list_domains(tmp_path, monkeypatch, capsys):
    domains_dir = _make_domains_dir(tmp_path)
    monkeypatch.setattr("tests.eval.run_rag_eval.DOMAINS_DIR", domains_dir)
    from tests.eval.run_rag_eval import main
    rc = main(["--list-domains"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "alpha" in out
    assert "beta" in out


def test_cli_requires_label_without_list_domains():
    from tests.eval.run_rag_eval import main
    with pytest.raises(SystemExit):
        main([])


def test_cli_domain_and_domains_mutually_exclusive():
    from tests.eval.run_rag_eval import main
    with pytest.raises(SystemExit):
        main(["--label", "x", "--domain", "alpha", "--domains", "alpha,beta"])


# ── render_report / compare_runs (unchanged) ──────────────────────────────────

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
    assert "+45" in md or "+0.19" in md
