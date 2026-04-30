# RAG Pipeline Modernization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Modernize the integration-agent RAG pipeline (parsing + retrieval) via four sequential ADRs (X1 parser / X2 embedder / X3 reranker+RRF / X4 contextual retrieval) gated by a lightweight eval harness, with full test coverage and Accenture-CLAUDE.md compliance.

**Architecture:** Phased rollout — every step is independently reversible behind a feature flag. The eval harness is merged FIRST so every ADR reports recall@k / MRR / NDCG / faithfulness deltas. New components plug into existing module boundaries (`services/`, `routers/kb.py`, `db.py`); ADR-027 (BM25), ADR-028 (multi-query), ADR-043/048 (semantic), ADR-052 (graph) are preserved unchanged.

**Tech Stack:** FastAPI + Pydantic-Settings + ChromaDB 0.5 + BM25Plus + Docling 2.5 + Ollama (Granite-Vision-3.2-2B / nomic-embed-text-v1.5 / llama3.1:8b) + sentence-transformers (bge-reranker-base) + Anthropic Claude Haiku 4.5 (opt-in).

**Reference design:** `docs/plans/2026-04-30-rag-pipeline-modernization-design.md` — read before starting any task.

**Conventions used in this plan:**
- Every task follows TDD: test first → run-fail → implement → run-pass → commit.
- File paths are absolute relative to repo root (`services/integration-agent/...`).
- Tests live next to the existing suite under `services/integration-agent/tests/` (or `services/ingestion-platform/tests/` when applicable).
- Each commit message follows the existing style (`feat(adr-xN): ...`, `test(adr-xN): ...`).
- Run unit tests with `cd services/integration-agent && python -m pytest tests/<file>.py -v`.

---

## Phase 0 — Eval Harness (prerequisite)

**Goal:** Deliver baseline measurement infrastructure BEFORE touching any pipeline code.

### Task 0.1: Create eval harness directory layout

**Files:**
- Create: `services/integration-agent/tests/eval/__init__.py` (empty)
- Create: `services/integration-agent/tests/eval/golden_questions.yaml`
- Create: `services/integration-agent/tests/eval/fixtures/.gitkeep`
- Create: `services/integration-agent/tests/eval/reports/.gitkeep`

**Step 1: Create directory layout**

```bash
mkdir -p services/integration-agent/tests/eval/{metrics,fixtures/sample_kb_corpus,reports}
touch services/integration-agent/tests/eval/__init__.py
touch services/integration-agent/tests/eval/metrics/__init__.py
touch services/integration-agent/tests/eval/fixtures/.gitkeep
touch services/integration-agent/tests/eval/reports/.gitkeep
```

**Step 2: Seed `golden_questions.yaml` with 5 example queries**

```yaml
# tests/eval/golden_questions.yaml
# 5 seed queries — extend to 30-50 before treating numbers as authoritative
- id: gq-001
  query: "What are the status mapping rules from PIM to PLM?"
  intent: data_mapping
  expected_chunk_keywords:
    - "product_status"
    - "lifecycle_state"
  expected_doc_ids: []  # filled after baseline run inspection
  expected_answer_must_contain:
    - "status"

- id: gq-002
  query: "How is authentication handled between PLM and DAM?"
  intent: architecture
  expected_chunk_keywords:
    - "OAuth"
    - "token"
  expected_doc_ids: []
  expected_answer_must_contain:
    - "authentication"

- id: gq-003
  query: "What error handling pattern is used for failed PIM uploads?"
  intent: errors
  expected_chunk_keywords:
    - "retry"
    - "dead-letter"
  expected_doc_ids: []
  expected_answer_must_contain:
    - "retry"

- id: gq-004
  query: "Describe the end-to-end product data flow."
  intent: overview
  expected_chunk_keywords:
    - "product"
    - "flow"
  expected_doc_ids: []
  expected_answer_must_contain:
    - "PIM"

- id: gq-005
  query: "What validation rules apply to product_status?"
  intent: business_rules
  expected_chunk_keywords:
    - "validation"
    - "mandatory"
  expected_doc_ids: []
  expected_answer_must_contain:
    - "validation"
```

**Step 3: Commit**

```bash
git add services/integration-agent/tests/eval/
git commit -m "test(eval): scaffold eval harness layout with 5 seed golden questions"
```

---

### Task 0.2: Implement retrieval metrics module (TDD)

**Files:**
- Create: `services/integration-agent/tests/eval/metrics/retrieval.py`
- Create: `services/integration-agent/tests/eval/test_metrics_retrieval.py`

**Step 1: Write failing tests for `recall_at_k`, `mrr`, `ndcg_at_k`**

```python
# tests/eval/test_metrics_retrieval.py
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
```

**Step 2: Run to confirm fail**

```bash
cd services/integration-agent && python -m pytest tests/eval/test_metrics_retrieval.py -v
# Expected: FAIL — module not found
```

**Step 3: Implement `retrieval.py`**

```python
# tests/eval/metrics/retrieval.py
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
    """Fraction of relevant items present in the top-k retrieved list."""
    if not relevant:
        return 0.0
    top_k = set(retrieved[:k])
    return len(top_k & relevant) / len(relevant)


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
    if not relevant:
        return 0.0
    dcg = sum(
        (1.0 if item in relevant else 0.0) / math.log2(i + 1)
        for i, item in enumerate(retrieved[:k], start=1)
    )
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0
```

**Step 4: Run, verify pass**

```bash
cd services/integration-agent && python -m pytest tests/eval/test_metrics_retrieval.py -v
# Expected: 7 passed
```

**Step 5: Commit**

```bash
git add services/integration-agent/tests/eval/metrics/retrieval.py services/integration-agent/tests/eval/test_metrics_retrieval.py
git commit -m "test(eval): retrieval metrics — recall@k, MRR, NDCG@k with TDD coverage"
```

---

### Task 0.3: Implement faithfulness module (TDD, optional Claude judge)

**Files:**
- Create: `services/integration-agent/tests/eval/metrics/faithfulness.py`
- Create: `services/integration-agent/tests/eval/test_metrics_faithfulness.py`

**Step 1: Write failing tests**

```python
# tests/eval/test_metrics_faithfulness.py
from tests.eval.metrics.faithfulness import substring_faithfulness, llm_judge_faithfulness


def test_substring_faithfulness_all_present():
    answer = "The status mapping uses uppercase transformation."
    must_contain = ["status", "uppercase"]
    assert substring_faithfulness(answer, must_contain) == 1.0


def test_substring_faithfulness_partial():
    answer = "The status uses transformation."
    must_contain = ["status", "uppercase", "lifecycle"]
    # 1/3
    assert abs(substring_faithfulness(answer, must_contain) - 1/3) < 1e-9


def test_substring_faithfulness_case_insensitive():
    answer = "STATUS uses UPPERCASE."
    assert substring_faithfulness(answer, ["status", "uppercase"]) == 1.0


def test_llm_judge_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    score = llm_judge_faithfulness(
        query="anything", answer="anything", contexts=["c1"],
    )
    assert score is None
```

**Step 2: Run, verify fail**

```bash
cd services/integration-agent && python -m pytest tests/eval/test_metrics_faithfulness.py -v
# Expected: FAIL — module not found
```

**Step 3: Implement `faithfulness.py`**

```python
# tests/eval/metrics/faithfulness.py
"""Faithfulness metrics — substring (cheap, deterministic) + LLM-judge (opt-in).

LLM-judge requires ANTHROPIC_API_KEY in the environment; without it returns None
and the harness reports 'n/a' for the metric.
"""
import os


def substring_faithfulness(answer: str, must_contain: list[str]) -> float:
    """Fraction of `must_contain` tokens present (case-insensitive) in answer."""
    if not must_contain:
        return 0.0
    answer_lower = answer.lower()
    hits = sum(1 for token in must_contain if token.lower() in answer_lower)
    return hits / len(must_contain)


def llm_judge_faithfulness(
    query: str,
    answer: str,
    contexts: list[str],
    *,
    model: str = "claude-haiku-4-5",
) -> float | None:
    """Score answer faithfulness 0-5 via Claude judge.

    Returns None when ANTHROPIC_API_KEY is absent (graceful skip).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic()
    prompt = (
        "Score how well the ANSWER is supported by the CONTEXTS for the QUERY.\n"
        "Return only a single number 0-5 (5 = fully grounded, 0 = hallucinated).\n\n"
        f"QUERY: {query}\n\n"
        f"CONTEXTS:\n{chr(10).join('- ' + c[:500] for c in contexts)}\n\n"
        f"ANSWER: {answer}\n\nSCORE:"
    )
    try:
        msg = client.messages.create(
            model=model, max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Extract first digit
        for ch in raw:
            if ch.isdigit():
                return float(ch)
        return None
    except Exception:
        return None
```

**Step 4: Run, verify pass**

```bash
cd services/integration-agent && python -m pytest tests/eval/test_metrics_faithfulness.py -v
# Expected: 4 passed
```

**Step 5: Commit**

```bash
git add services/integration-agent/tests/eval/metrics/faithfulness.py services/integration-agent/tests/eval/test_metrics_faithfulness.py
git commit -m "test(eval): faithfulness metric — substring + Claude judge with key-absent fallback"
```

---

### Task 0.4: Implement `run_rag_eval.py` CLI runner

**Files:**
- Create: `services/integration-agent/tests/eval/run_rag_eval.py`
- Create: `services/integration-agent/tests/eval/test_run_rag_eval.py`

**Step 1: Write failing tests for label / compare / report rendering**

```python
# tests/eval/test_run_rag_eval.py
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
```

**Step 2: Run, verify fail**

```bash
cd services/integration-agent && python -m pytest tests/eval/test_run_rag_eval.py -v
```

**Step 3: Implement `run_rag_eval.py`** (skeleton — actual retrieval invocation deferred to Task 0.5)

```python
# tests/eval/run_rag_eval.py
"""CLI runner for RAG eval harness.

Usage:
  python tests/eval/run_rag_eval.py --label baseline --output reports/2026-04-30_baseline.md
  python tests/eval/run_rag_eval.py --label adr-x2 --compare baseline
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


REPORTS_DIR = Path(__file__).parent / "reports"
GOLDEN_PATH = Path(__file__).parent / "golden_questions.yaml"


def load_golden_questions(path: Path = GOLDEN_PATH) -> list[dict]:
    with open(path) as f:
        return yaml.safe_load(f) or []


def render_report(label: str, metrics: dict[str, Any], n_queries: int) -> str:
    lines = [
        f"# RAG Eval Report — {label}",
        "",
        f"- queries: {n_queries}",
        "",
        "| metric | value |",
        "|--------|-------|",
    ]
    for k, v in metrics.items():
        if isinstance(v, float):
            lines.append(f"| {k} | {v:.3f} |")
        else:
            lines.append(f"| {k} | {v} |")
    return "\n".join(lines) + "\n"


def compare_runs(
    label_a: str, metrics_a: dict[str, Any],
    label_b: str, metrics_b: dict[str, Any],
) -> str:
    lines = [f"# RAG Eval Comparison — {label_a} vs {label_b}", "", "| metric | A | B | Δ abs | Δ % |", "|--------|---|---|-------|-----|"]
    for k in metrics_a.keys() & metrics_b.keys():
        a, b = metrics_a[k], metrics_b[k]
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            d_abs = b - a
            d_pct = (d_abs / a * 100.0) if a != 0 else float("nan")
            lines.append(f"| {k} | {a:.3f} | {b:.3f} | {d_abs:+.3f} | {d_pct:+.0f}% |")
    return "\n".join(lines) + "\n"


def _save_run(label: str, metrics: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{label}.json"
    path.write_text(json.dumps(metrics, indent=2))
    return path


def _load_run(label: str) -> dict:
    return json.loads((REPORTS_DIR / f"{label}.json").read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compare", default=None,
                        help="Label of a previous run to diff against")
    args = parser.parse_args(argv)

    # Actual retrieval execution → Task 0.5
    from tests.eval.runner import execute_pipeline
    metrics = execute_pipeline(load_golden_questions())

    _save_run(args.label, metrics)

    if args.compare:
        baseline = _load_run(args.compare)
        report_md = compare_runs(args.compare, baseline, args.label, metrics)
    else:
        report_md = render_report(args.label, metrics, n_queries=len(load_golden_questions()))

    out = args.output or (REPORTS_DIR / f"{args.label}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_md)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Run, verify pass**

```bash
cd services/integration-agent && python -m pytest tests/eval/test_run_rag_eval.py -v
```

**Step 5: Commit**

```bash
git add services/integration-agent/tests/eval/run_rag_eval.py services/integration-agent/tests/eval/test_run_rag_eval.py
git commit -m "test(eval): CLI runner with report rendering and run-comparison"
```

---

### Task 0.5: Implement pipeline-execution `runner.py` (mockable for tests)

**Files:**
- Create: `services/integration-agent/tests/eval/runner.py`
- Create: `services/integration-agent/tests/eval/test_runner.py`

**Step 1: Write failing test using mocked retriever**

```python
# tests/eval/test_runner.py
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
```

**Step 2: Run, verify fail**

```bash
cd services/integration-agent && python -m pytest tests/eval/test_runner.py -v
```

**Step 3: Implement `runner.py`**

```python
# tests/eval/runner.py
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
```

**Step 4: Run, verify pass**

```bash
cd services/integration-agent && python -m pytest tests/eval/test_runner.py -v
```

**Step 5: Run full eval suite — produce baseline report**

```bash
cd services/integration-agent && python -m pytest tests/eval/ -v
# All tests should pass
```

**Step 6: Commit**

```bash
git add services/integration-agent/tests/eval/runner.py services/integration-agent/tests/eval/test_runner.py
git commit -m "test(eval): pipeline runner stitching retriever output to metrics"
```

---

### Task 0.6: Document the eval harness

**Files:**
- Create: `HOW-TO/how-to-rag-eval.md`

**Step 1: Write a brief HOW-TO guide**

```markdown
# How To — Run RAG Eval Harness

The eval harness produces empirical recall@k / MRR / NDCG / faithfulness metrics
to gate every ADR in the RAG pipeline modernization (`docs/plans/2026-04-30-rag-pipeline-modernization-design.md`).

## Quick start

```bash
cd services/integration-agent

# 1. Make sure Ollama / ChromaDB / MongoDB are reachable (`docker compose up`)
# 2. Make sure the KB has at least the synthetic fixtures ingested

# Baseline pre-ADR
python -m tests.eval.run_rag_eval --label baseline

# After merging ADR-X2
python -m tests.eval.run_rag_eval --label adr-x2 --compare baseline
```

Reports are written to `tests/eval/reports/{label}.md` and `{label}.json`.

## Adding a golden question

Edit `tests/eval/golden_questions.yaml`. Each entry needs:

- `id`: unique slug (e.g. `gq-042`)
- `query`: the user question
- `intent`: one of `overview`, `business_rules`, `data_mapping`, `errors`, `architecture`
- `expected_chunk_keywords`: keyword fallback when `expected_doc_ids` is empty
- `expected_doc_ids`: best-effort ground truth chunk IDs (may be filled from a baseline run)
- `expected_answer_must_contain`: tokens required in the assembled answer

## Compliance note (CLAUDE.md §1)

Use only synthetic / public / Accenture-Internal-classified data in `tests/eval/fixtures/sample_kb_corpus/`.
Never commit real client data.

## Faithfulness (LLM-judge)

When `ANTHROPIC_API_KEY` is exported, the harness can additionally call
Claude Haiku to score answer-context faithfulness 0-5. Without the key the
metric is reported as `n/a` and the run continues.
```

**Step 2: Commit**

```bash
git add HOW-TO/how-to-rag-eval.md
git commit -m "docs(eval): how-to guide for running and extending the RAG eval harness"
```

---

### Task 0.7: Capture baseline (manual step)

**Action (no code change):**

```bash
cd services/integration-agent
python -m tests.eval.run_rag_eval --label baseline --output tests/eval/reports/2026-04-30_baseline.md
git add tests/eval/reports/2026-04-30_baseline.md tests/eval/reports/baseline.json
git commit -m "test(eval): capture baseline report (pre-ADR-X1)"
```

**Verify:** `cat tests/eval/reports/2026-04-30_baseline.md` shows recall@5, MRR, NDCG@5, latency.
This baseline is the comparison point for all subsequent ADR runs.

---

## Phase 1 — ADR-X1 Parser (Docling 2.5 + Granite-Vision)

**Goal:** Replace LLaVA-7b with Granite-Vision-3.2-2B as default VLM, keep LLaVA as configurable fallback.

### Task X1.1: Add config flags + spike Granite-Vision availability

**Files:**
- Modify: `services/integration-agent/config.py`

**Step 1 (manual spike, 30 min):** Verify Granite-Vision is pullable on EC2.

```bash
# On EC2 18.197.235.56
ollama pull granite3.2-vision:2b
ollama list  # confirm presence
```

If unavailable → fall back to `granite3.2-vision:latest` or document as risk and stop here.

**Step 2: Add config vars**

Edit `services/integration-agent/config.py` — replace the line `vision_model_name: str = "llava:7b"` block with:

```python
    # ── Vision / VLM (ADR-X1) ─────────────────────────────────────────────────
    # Primary VLM — IBM Granite-Vision tuned for enterprise documents.
    vlm_model_name: str = "granite3.2-vision:2b"
    # Fallback VLM — used when the primary fails or VLM_FORCE_FALLBACK=true.
    vlm_fallback_model_name: str = "llava:7b"
    # When True, the fallback model is used directly (skips primary attempt).
    vlm_force_fallback: bool = False
    # DEPRECATED — kept for backward compat in tests.  Reads from vlm_model_name.
    vision_model_name: str = "granite3.2-vision:2b"
    # Existing flag preserved.
    vision_captioning_enabled: bool = True
```

**Step 3: Run existing tests to confirm nothing breaks**

```bash
cd services/integration-agent && python -m pytest tests/test_config.py -v
# Expected: pass (the 2 pre-existing failures unrelated to llama3.1:8b stay)
```

**Step 4: Commit**

```bash
git add services/integration-agent/config.py
git commit -m "feat(adr-x1): add VLM config — Granite-Vision primary + LLaVA fallback"
```

---

### Task X1.2: Update vision_service with fallback chain (TDD)

**Files:**
- Modify: `services/integration-agent/services/vision_service.py`
- Modify (or create): `services/integration-agent/tests/test_vision_service.py`

**Step 1: Write failing tests**

```python
# tests/test_vision_service.py
import pytest
from unittest.mock import AsyncMock, patch
from services.vision_service import caption_figure


@pytest.mark.asyncio
async def test_caption_uses_primary_vlm_first(monkeypatch):
    monkeypatch.setattr("config.settings.vlm_model_name", "granite3.2-vision:2b")
    monkeypatch.setattr("config.settings.vlm_fallback_model_name", "llava:7b")
    monkeypatch.setattr("config.settings.vlm_force_fallback", False)
    monkeypatch.setattr("config.settings.vision_captioning_enabled", True)

    captured_models = []
    async def fake_post(self, url, json, **kw):
        captured_models.append(json["model"])
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"message": {"content": "primary caption"}}
        return R()

    with patch("httpx.AsyncClient.post", new=fake_post):
        out = await caption_figure(b"\x00\x01")
    assert out == "primary caption"
    assert captured_models == ["granite3.2-vision:2b"]


@pytest.mark.asyncio
async def test_caption_falls_back_to_llava_on_primary_error(monkeypatch):
    monkeypatch.setattr("config.settings.vlm_model_name", "granite3.2-vision:2b")
    monkeypatch.setattr("config.settings.vlm_fallback_model_name", "llava:7b")
    monkeypatch.setattr("config.settings.vlm_force_fallback", False)
    monkeypatch.setattr("config.settings.vision_captioning_enabled", True)

    calls = []
    async def fake_post(self, url, json, **kw):
        calls.append(json["model"])
        class R:
            status_code = 500
            def raise_for_status(self):
                if json["model"] == "granite3.2-vision:2b":
                    import httpx
                    raise httpx.HTTPStatusError("boom", request=None, response=None)
            def json(self):
                return {"message": {"content": "fallback caption"}}
        return R()

    with patch("httpx.AsyncClient.post", new=fake_post):
        out = await caption_figure(b"\x00\x01")
    assert out == "fallback caption"
    assert calls == ["granite3.2-vision:2b", "llava:7b"]


@pytest.mark.asyncio
async def test_caption_skips_primary_when_force_fallback_set(monkeypatch):
    monkeypatch.setattr("config.settings.vlm_model_name", "granite3.2-vision:2b")
    monkeypatch.setattr("config.settings.vlm_fallback_model_name", "llava:7b")
    monkeypatch.setattr("config.settings.vlm_force_fallback", True)
    monkeypatch.setattr("config.settings.vision_captioning_enabled", True)

    calls = []
    async def fake_post(self, url, json, **kw):
        calls.append(json["model"])
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"message": {"content": "ok"}}
        return R()

    with patch("httpx.AsyncClient.post", new=fake_post):
        await caption_figure(b"\x00")
    assert calls == ["llava:7b"]


@pytest.mark.asyncio
async def test_caption_returns_placeholder_when_disabled(monkeypatch):
    monkeypatch.setattr("config.settings.vision_captioning_enabled", False)
    out = await caption_figure(b"\x00")
    assert out == "[FIGURE: no caption available]"
```

**Step 2: Run, verify fail**

```bash
cd services/integration-agent && python -m pytest tests/test_vision_service.py -v
```

**Step 3: Refactor `vision_service.py` to use the fallback chain**

```python
# services/vision_service.py
"""Vision Service — VLM figure captioning via Ollama (ADR-X1).

Primary: Granite-Vision-3.2-2B (IBM, tuned for enterprise documents).
Fallback: LLaVA-7b (legacy, kept for env-var-driven override).

Fallback-first design: any failure (timeout, server error, disabled flag) returns
the "[FIGURE: no caption available]" placeholder so KB ingestion never crashes.
"""

import base64
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

_PLACEHOLDER = "[FIGURE: no caption available]"

_CAPTION_PROMPT = (
    "Describe this image concisely for a technical integration document. "
    "Focus on data flows, field mappings, system names, and chart values if present. "
    "One short paragraph, no bullet points."
)


async def _call_vlm(model: str, image_bytes: bytes) -> str:
    image_b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": _CAPTION_PROMPT,
            "images": [image_b64],
        }],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=settings.tag_timeout_seconds) as client:
        resp = await client.post(f"{settings.ollama_host}/api/chat", json=payload)
        resp.raise_for_status()
        body = resp.json()
        return (body.get("message", {}).get("content") or "").strip()


async def caption_figure(image_bytes: bytes) -> str:
    """Generate a text caption for an image using the configured VLM with fallback.

    Order:
      1. settings.vlm_model_name (Granite-Vision by default)
      2. settings.vlm_fallback_model_name (LLaVA by default) — used on error
         or when settings.vlm_force_fallback is True.
      3. _PLACEHOLDER on both failures.
    """
    if not settings.vision_captioning_enabled:
        return _PLACEHOLDER

    primary = settings.vlm_model_name
    fallback = settings.vlm_fallback_model_name
    models = [fallback] if settings.vlm_force_fallback else [primary, fallback]

    for model in models:
        try:
            caption = await _call_vlm(model, image_bytes)
            if caption:
                logger.info("[Vision] Caption ok (%s, %d chars).", model, len(caption))
                return caption
            logger.warning("[Vision] %s returned empty caption.", model)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
            logger.warning("[Vision] %s failed (%s) — trying next.", model, type(exc).__name__)

    return _PLACEHOLDER
```

**Step 4: Run, verify pass**

```bash
cd services/integration-agent && python -m pytest tests/test_vision_service.py -v
# Expected: 4 passed
```

**Step 5: Run regression**

```bash
cd services/integration-agent && python -m pytest tests/ -v -k "vision or docling"
# Expected: all green
```

**Step 6: Commit**

```bash
git add services/integration-agent/services/vision_service.py services/integration-agent/tests/test_vision_service.py
git commit -m "feat(adr-x1): VLM fallback chain — Granite-Vision primary, LLaVA fallback"
```

---

### Task X1.3: Update Docling integration to use new VLM model name

**Files:**
- Modify: `services/integration-agent/document_parser.py:614,674`
- Modify: `services/integration-agent/tests/test_document_parser_docling.py`

**Step 1: Add a regression test asserting the VLM name flows through**

Edit `tests/test_document_parser_docling.py` and add:

```python
@pytest.mark.asyncio
async def test_picture_item_invokes_vlm_via_fallback_chain(monkeypatch):
    """ADR-X1: Docling → caption_figure() must use settings.vlm_model_name."""
    monkeypatch.setattr("config.settings.vlm_model_name", "granite3.2-vision:2b")
    monkeypatch.setattr("config.settings.vision_captioning_enabled", True)

    captured = {}
    async def fake_caption(img_bytes):
        captured["called"] = True
        return "caption from VLM"

    monkeypatch.setattr("services.vision_service.caption_figure", fake_caption)
    # ... full Docling mock omitted for brevity — copy from existing test
    # Assert captured["called"] is True after parse_with_docling()
```

(In practice extend the existing `test_picture_item_produces_figure_chunk` test to also assert the model name at the httpx level.)

**Step 2: Modify `document_parser.py:580+` so the lazy import comment mentions the new model**

Replace any comment referencing `llava:7b` with `Granite-Vision (settings.vlm_model_name)` — the actual code already calls `caption_figure()` which now handles the fallback chain internally.

**Step 3: Run all docling tests**

```bash
cd services/integration-agent && python -m pytest tests/test_document_parser_docling.py -v
# Expected: all green
```

**Step 4: Commit**

```bash
git add services/integration-agent/document_parser.py services/integration-agent/tests/test_document_parser_docling.py
git commit -m "feat(adr-x1): document_parser routes figure captions through VLM fallback chain"
```

---

### Task X1.4: Pin Docling version in requirements + Dockerfile pre-pull

**Files:**
- Modify: `services/integration-agent/requirements.txt`
- Modify: `services/integration-agent/Dockerfile` (if present)
- Modify: `docker-compose.yml` (Ollama init)

**Step 1: Bump Docling**

`requirements.txt`:
```diff
-docling>=2.0
+docling>=2.5,<3.0
```

**Step 2: Add Granite-Vision to ollama-init**

In `docker-compose.yml`, find the Ollama init service and ensure pull list includes `granite3.2-vision:2b`. Example:

```yaml
  ollama-init:
    image: curlimages/curl:8.7.1
    depends_on: [ollama]
    entrypoint: |
      sh -c "
      curl -X POST http://ollama:11434/api/pull -d '{\"name\":\"qwen2.5:14b\"}' &&
      curl -X POST http://ollama:11434/api/pull -d '{\"name\":\"qwen3:8b\"}' &&
      curl -X POST http://ollama:11434/api/pull -d '{\"name\":\"granite3.2-vision:2b\"}' &&
      curl -X POST http://ollama:11434/api/pull -d '{\"name\":\"llava:7b\"}'
      "
```

**Step 3: Rebuild image locally to confirm**

```bash
docker compose build integration-agent
docker compose up -d ollama
docker compose run --rm ollama-init  # verify all 4 pulls succeed
```

**Step 4: Commit**

```bash
git add services/integration-agent/requirements.txt docker-compose.yml
git commit -m "chore(adr-x1): bump Docling to 2.5 and pre-pull granite3.2-vision:2b"
```

---

### Task X1.5: Re-ingest KB and run eval

**Action (manual):**

```bash
# Re-ingest sample fixtures
cd services/integration-agent
# (use UI or scripted upload of tests/eval/fixtures/sample_kb_corpus/*)

# Run eval
python -m tests.eval.run_rag_eval --label adr-x1-parser --compare baseline
```

**Step 1: Commit eval report**

```bash
git add services/integration-agent/tests/eval/reports/adr-x1-parser.md services/integration-agent/tests/eval/reports/adr-x1-parser.json
git commit -m "test(eval): ADR-X1 parser — eval report vs baseline"
```

**Step 2: Write ADR-X1 in `docs/adr/`** (use `docs/adr/ADR-000-template.md`).
Include:
- Decision: Granite-Vision primary, LLaVA fallback
- Validation plan: eval harness recall delta + caption-quality
- Rollback: `VLM_MODEL_NAME=llava:7b`

```bash
git add docs/adr/ADR-X1-vlm-granite-vision.md
git commit -m "docs(adr-x1): VLM upgrade — Granite-Vision primary, LLaVA fallback"
```

**Step 3: Tag pre-merge state**

```bash
git tag pre-adr-x1
```

---

## Phase 2 — ADR-X2 Embedder (`nomic-embed-text-v1.5`)

**Goal:** Replace ChromaDB default embedder with nomic-embed-text-v1.5 via Ollama.

### Task X2.1: Add config + dual-mode embedding function (TDD)

**Files:**
- Modify: `services/integration-agent/config.py`
- Create: `services/integration-agent/embedding_function.py`
- Create: `services/integration-agent/tests/test_embedding_function.py`

**Step 1: Add config vars** to `config.py`:

```python
    # ── Embedder (ADR-X2) ─────────────────────────────────────────────────────
    # Provider: "ollama" (default) or "default" (ChromaDB native MiniLM).
    embedder_provider: str = "ollama"
    embedder_model_name: str = "nomic-embed-text:v1.5"
    # nomic-embed-text task prefixes — ingestion vs retrieval.
    embedder_doc_prefix: str = "search_document: "
    embedder_query_prefix: str = "search_query: "
```

**Step 2: Write failing tests**

```python
# tests/test_embedding_function.py
from unittest.mock import patch
from embedding_function import OllamaEmbeddingFunction


def test_ollama_embedding_function_uses_doc_prefix_for_documents(monkeypatch):
    monkeypatch.setattr("config.settings.embedder_doc_prefix", "search_document: ")
    monkeypatch.setattr("config.settings.embedder_query_prefix", "search_query: ")
    captured = []
    def fake_post(self, url, json, **kw):
        captured.append(json)
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"embedding": [0.1, 0.2, 0.3]}
        return R()
    fn = OllamaEmbeddingFunction(model="nomic-embed-text:v1.5",
                                 ollama_host="http://o:11434", mode="document")
    with patch("httpx.Client.post", new=fake_post):
        out = fn(["chunk text"])
    assert captured[0]["prompt"].startswith("search_document: ")
    assert out == [[0.1, 0.2, 0.3]]


def test_ollama_embedding_function_uses_query_prefix_in_query_mode(monkeypatch):
    monkeypatch.setattr("config.settings.embedder_doc_prefix", "search_document: ")
    monkeypatch.setattr("config.settings.embedder_query_prefix", "search_query: ")
    captured = []
    def fake_post(self, url, json, **kw):
        captured.append(json)
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"embedding": [0.0]}
        return R()
    fn = OllamaEmbeddingFunction(model="nomic-embed-text:v1.5",
                                 ollama_host="http://o:11434", mode="query")
    with patch("httpx.Client.post", new=fake_post):
        fn(["my question"])
    assert captured[0]["prompt"].startswith("search_query: ")


def test_ollama_embedding_function_iterates_each_input(monkeypatch):
    posts = []
    def fake_post(self, url, json, **kw):
        posts.append(json["prompt"])
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"embedding": [0.0] * 768}
        return R()
    fn = OllamaEmbeddingFunction(model="nomic-embed-text:v1.5",
                                 ollama_host="http://o:11434", mode="document")
    with patch("httpx.Client.post", new=fake_post):
        out = fn(["a", "b", "c"])
    assert len(posts) == 3
    assert all(p.endswith("a") or p.endswith("b") or p.endswith("c") for p in posts)
    assert len(out) == 3
    assert all(len(v) == 768 for v in out)
```

**Step 3: Run, verify fail**

```bash
cd services/integration-agent && python -m pytest tests/test_embedding_function.py -v
```

**Step 4: Implement `embedding_function.py`**

```python
# embedding_function.py
"""Ollama-backed ChromaDB embedding function with task-aware prefixing (ADR-X2).

nomic-embed-text-v1.5 uses task prefixes ("search_document: " / "search_query: ")
to disambiguate ingestion vs retrieval calls.  This wrapper enforces them per
mode at the function-call site.
"""
from __future__ import annotations
import logging
from typing import Literal

import httpx
from chromadb import Documents, EmbeddingFunction, Embeddings

from config import settings

logger = logging.getLogger(__name__)

_MODE = Literal["document", "query"]


class OllamaEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model: str, ollama_host: str, mode: _MODE):
        self._model = model
        self._url = f"{ollama_host.rstrip('/')}/api/embeddings"
        self._mode = mode

    def __call__(self, input: Documents) -> Embeddings:
        prefix = (settings.embedder_doc_prefix
                  if self._mode == "document"
                  else settings.embedder_query_prefix)
        out: Embeddings = []
        with httpx.Client(timeout=60.0) as client:
            for text in input:
                resp = client.post(self._url, json={
                    "model": self._model,
                    "prompt": f"{prefix}{text}",
                })
                resp.raise_for_status()
                out.append(resp.json()["embedding"])
        return out
```

**Step 5: Run, verify pass**

```bash
cd services/integration-agent && python -m pytest tests/test_embedding_function.py -v
# Expected: 3 passed
```

**Step 6: Commit**

```bash
git add services/integration-agent/config.py services/integration-agent/embedding_function.py services/integration-agent/tests/test_embedding_function.py
git commit -m "feat(adr-x2): OllamaEmbeddingFunction — task-prefix-aware document/query modes"
```

---

### Task X2.2: Wire EmbeddingFunction into ChromaDB collection init

**Files:**
- Modify: `services/integration-agent/main.py:46-69` (ChromaDB init)

**Step 1: Modify `_init_chromadb()` to attach the embedder**

Replace the `get_or_create_collection` calls so each collection has `embedding_function=OllamaEmbeddingFunction(..., mode="document")`. Add a sibling `_kb_query_embedder` (mode="query") used at query time.

```python
# main.py — schematic diff
from embedding_function import OllamaEmbeddingFunction

def _make_embedder(mode):
    if settings.embedder_provider != "ollama":
        return None  # ChromaDB falls back to default MiniLM
    return OllamaEmbeddingFunction(
        model=settings.embedder_model_name,
        ollama_host=settings.ollama_host,
        mode=mode,
    )

state.kb_doc_embedder = _make_embedder("document")
state.kb_query_embedder = _make_embedder("query")

state.collection = state.chroma_client.get_or_create_collection(
    name="approved_integrations",
    embedding_function=state.kb_doc_embedder,
)
state.kb_collection = state.chroma_client.get_or_create_collection(
    name="knowledge_base",
    embedding_function=state.kb_doc_embedder,
)
state.summaries_col = state.chroma_client.get_or_create_collection(
    name="kb_summaries",
    embedding_function=state.kb_doc_embedder,
)
```

**Step 2: Update `state.py`** — add `kb_doc_embedder` and `kb_query_embedder` module-level placeholders.

**Step 3: Audit `kb_collection.query(query_texts=...)` callers** — they implicitly use the collection's `embedding_function`, which is the doc embedder. Switch query-time embedding by passing `query_embeddings=state.kb_query_embedder([query_text])` instead of `query_texts=[...]` in:
- `services/retriever.py:_query_chroma` (line ~263)
- `services/rag_service.py:124`
- `services/retriever.py:retrieve_summaries` (line ~671)

**Step 4: Add a smoke integration test**

```python
# tests/test_embedder_wiring.py
def test_kb_collection_has_ollama_embedder_in_document_mode(monkeypatch):
    monkeypatch.setenv("EMBEDDER_PROVIDER", "ollama")
    # … construct via importlib.reload(main) and assert state.kb_doc_embedder._mode == "document"
```

**Step 5: Run regression**

```bash
cd services/integration-agent && python -m pytest tests/ -v -k "embedder or chroma or kb"
# Expected: all green; existing tests unchanged
```

**Step 6: Commit**

```bash
git add services/integration-agent/main.py services/integration-agent/state.py services/integration-agent/services/retriever.py services/integration-agent/services/rag_service.py services/integration-agent/tests/test_embedder_wiring.py
git commit -m "feat(adr-x2): wire OllamaEmbeddingFunction into ChromaDB collections"
```

---

### Task X2.3: Mirror change in ingestion-platform

**Files:**
- Modify: `services/ingestion-platform/...` (apply same pattern as X2.1+X2.2 to the ingestion-platform's ChromaDB init)
- Tests in `services/ingestion-platform/tests/`

**Step 1:** Locate the ChromaDB collection init in ingestion-platform (search `chromadb.HttpClient` / `get_or_create_collection`).

**Step 2:** Apply the same `OllamaEmbeddingFunction(mode="document")` wiring.

**Step 3:** Add unit test mirroring `test_embedding_function.py`.

**Step 4: Commit**

```bash
git add services/ingestion-platform/
git commit -m "feat(adr-x2): apply OllamaEmbeddingFunction to ingestion-platform"
```

---

### Task X2.4: Re-ingest KB + run eval

**Action (manual, requires running stack):**

```bash
# Pre-X2 snapshot
docker compose exec mate-chromadb sh -c "cp -r /chroma/chroma /tmp/pre-x2"

# Drop & recreate kb_collection / kb_summaries / approved_integrations
# (via UI button or admin script)

# Re-upload KB fixtures
# (UI batch-upload or scripted)

# Run eval
cd services/integration-agent
python -m tests.eval.run_rag_eval --label adr-x2-embedder --compare baseline
```

**Step 1: Commit eval + ADR**

```bash
git add services/integration-agent/tests/eval/reports/adr-x2-embedder.{md,json} docs/adr/ADR-X2-embedder-nomic.md
git commit -m "docs(adr-x2): embedder swap to nomic-embed-text-v1.5 — eval delta vs baseline"
git tag pre-adr-x2-merge
```

---

## Phase 3 — ADR-X3 Reranker + RRF

**Goal:** Replace `_ensemble_merge` with RRF; replace `_tfidf_rerank` with `bge-reranker-base` cross-encoder; add opt-in Claude Haiku LLM-judge.

### Task X3.1: Add config flags

**Files:**
- Modify: `services/integration-agent/config.py`

```python
    # ── Reranker / Fusion (ADR-X3) ────────────────────────────────────────────
    reranker_enabled: bool = True
    reranker_model_name: str = "BAAI/bge-reranker-base"
    reranker_top_n: int = 30
    rag_use_rrf: bool = True
    rag_rrf_k: int = 60
    llm_judge_enabled: bool = False
    llm_judge_top_k: int = 10
    llm_judge_model: str = "claude-haiku-4-5"
```

**Step 1: Commit**

```bash
git add services/integration-agent/config.py
git commit -m "feat(adr-x3): config flags for reranker + RRF + LLM-judge"
```

---

### Task X3.2: Implement RRF (TDD)

**Files:**
- Modify: `services/integration-agent/services/retriever.py`
- Modify: `services/integration-agent/tests/test_retriever.py` (or create dedicated `test_rrf.py`)

**Step 1: Write failing tests**

```python
# tests/test_rrf.py
from services.retriever import HybridRetriever, ScoredChunk


def _mk(text, score, label="x"):
    return ScoredChunk(text=text, score=score, source_label=label, tags=[], doc_id=text)


def test_rrf_merges_by_rank_not_score():
    r = HybridRetriever()
    chroma = [_mk("a", 0.99), _mk("b", 0.50), _mk("c", 0.01)]
    bm25   = [_mk("c", 100.0), _mk("a", 50.0), _mk("d", 1.0)]
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
    bm25   = [_mk("a", 5.0)]   # rank 1 → 1/61
    out = r._rrf_merge(chroma, bm25, k=60)
    assert len(out) == 1
    assert abs(out[0].score - (1/61 + 1/61)) < 1e-9
```

**Step 2: Run, verify fail**

```bash
cd services/integration-agent && python -m pytest tests/test_rrf.py -v
```

**Step 3: Implement `_rrf_merge` in `retriever.py`** (alongside the existing `_ensemble_merge`, gated by `settings.rag_use_rrf`):

```python
    def _rrf_merge(
        self,
        chroma_chunks: list[ScoredChunk],
        bm25_chunks: list[ScoredChunk],
        k: int = 60,
    ) -> list[ScoredChunk]:
        """Reciprocal Rank Fusion — robust to heterogeneous score scales."""
        rrf_scores: dict[str, float] = {}
        chunk_map: dict[str, ScoredChunk] = {}

        for source in (chroma_chunks, bm25_chunks):
            sorted_src = sorted(source, key=lambda c: c.score, reverse=True)
            for rank, chunk in enumerate(sorted_src, start=1):
                key = chunk.text[:100]
                rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (k + rank)
                if key not in chunk_map:
                    chunk_map[key] = chunk

        out = []
        for key, score in sorted(rrf_scores.items(), key=lambda kv: kv[1], reverse=True):
            existing = chunk_map[key]
            out.append(ScoredChunk(
                text=existing.text, score=score,
                source_label=existing.source_label, tags=existing.tags,
                doc_id=existing.doc_id, semantic_type=existing.semantic_type,
            ))
        return out
```

**Step 4: Wire into `retrieve()` based on flag**

```python
        if settings.rag_use_rrf:
            merged = self._rrf_merge(chroma_chunks, bm25_chunks, k=settings.rag_rrf_k)
        else:
            merged = self._ensemble_merge(chroma_chunks, bm25_chunks)
```

**Step 5: Run, verify pass + regression**

```bash
cd services/integration-agent && python -m pytest tests/test_rrf.py tests/test_retriever.py -v
```

**Step 6: Commit**

```bash
git add services/integration-agent/services/retriever.py services/integration-agent/tests/test_rrf.py
git commit -m "feat(adr-x3): RRF fusion alongside weighted-merge (gated by RAG_USE_RRF)"
```

---

### Task X3.3: Implement cross-encoder reranker service (TDD)

**Files:**
- Create: `services/integration-agent/services/reranker_service.py`
- Create: `services/integration-agent/tests/test_reranker_service.py`

**Step 1: Add `sentence-transformers` to requirements.txt**

```diff
+sentence-transformers>=3.0,<4.0
```

**Step 2: Write failing tests**

```python
# tests/test_reranker_service.py
from unittest.mock import MagicMock, patch
from services.reranker_service import cross_encoder_rerank
from services.retriever import ScoredChunk


def _mk(text, score, doc_id=None):
    return ScoredChunk(text=text, score=score, source_label="x", tags=[], doc_id=doc_id or text)


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
```

**Step 3: Run, verify fail**

```bash
cd services/integration-agent && python -m pytest tests/test_reranker_service.py -v
```

**Step 4: Implement `reranker_service.py`**

```python
# services/reranker_service.py
"""Cross-encoder reranker for the RAG pipeline (ADR-X3).

Lazy-loaded — sentence-transformers is heavy (~600 MB).  No global state until
first call.  When disabled (settings.reranker_enabled=False), callers should
short-circuit before invoking this module.
"""
from __future__ import annotations
import logging
from typing import Optional

from config import settings
from services.retriever import ScoredChunk

logger = logging.getLogger(__name__)

_model_singleton = None


def _get_model():
    global _model_singleton
    if _model_singleton is None:
        from sentence_transformers import CrossEncoder
        logger.info("[Reranker] Loading %s (lazy, first call).",
                    settings.reranker_model_name)
        _model_singleton = CrossEncoder(settings.reranker_model_name)
    return _model_singleton


def cross_encoder_rerank(
    query: str,
    chunks: list[ScoredChunk],
) -> list[ScoredChunk]:
    if not chunks:
        return chunks
    model = _get_model()
    pairs = [[query, c.text] for c in chunks]
    scores = model.predict(pairs).tolist()  # type: ignore[union-attr]
    rescored = [
        ScoredChunk(
            text=c.text, score=float(s),
            source_label=c.source_label, tags=c.tags,
            doc_id=c.doc_id, semantic_type=c.semantic_type,
        )
        for c, s in zip(chunks, scores)
    ]
    return sorted(rescored, key=lambda c: c.score, reverse=True)
```

**Step 5: Run, verify pass**

```bash
cd services/integration-agent && python -m pytest tests/test_reranker_service.py -v
# Expected: 3 passed
```

**Step 6: Wire into `HybridRetriever.retrieve()` after RRF**

In `services/retriever.py:retrieve()` replace the `_tfidf_rerank` call with:

```python
        if settings.reranker_enabled:
            from services.reranker_service import cross_encoder_rerank
            top_n = filtered[:settings.reranker_top_n]
            reranked = cross_encoder_rerank(query_text, top_n)
        else:
            reranked = self._tfidf_rerank(filtered, query_text, intent)
```

**Step 7: Run regression**

```bash
cd services/integration-agent && python -m pytest tests/ -v -k "retriev or rerank"
```

**Step 8: Commit**

```bash
git add services/integration-agent/services/reranker_service.py services/integration-agent/services/retriever.py services/integration-agent/requirements.txt services/integration-agent/tests/test_reranker_service.py
git commit -m "feat(adr-x3): cross-encoder reranker service (bge-reranker-base) replacing TF-IDF"
```

---

### Task X3.4: Implement Claude LLM-judge cascade (opt-in, TDD)

**Files:**
- Create: `services/integration-agent/services/llm_judge_service.py`
- Create: `services/integration-agent/tests/test_llm_judge_service.py`

**Step 1: Write failing tests** focusing on:
1. Returns input unchanged when `llm_judge_enabled=False`
2. Returns input unchanged when `ANTHROPIC_API_KEY` absent
3. Sends `cache_control` on system blocks
4. Re-orders chunks by Claude-returned scores

```python
# tests/test_llm_judge_service.py
import os
import pytest
from unittest.mock import MagicMock, patch
from services.llm_judge_service import llm_judge_rerank
from services.retriever import ScoredChunk


def _mk(t, doc_id=None):
    return ScoredChunk(text=t, score=0.5, source_label="x", tags=[], doc_id=doc_id or t)


def test_llm_judge_returns_input_when_disabled(monkeypatch):
    monkeypatch.setattr("config.settings.llm_judge_enabled", False)
    chunks = [_mk("a"), _mk("b")]
    out = pytest_run(llm_judge_rerank, "q", chunks)
    assert out == chunks


def test_llm_judge_returns_input_when_no_key(monkeypatch):
    monkeypatch.setattr("config.settings.llm_judge_enabled", True)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("config.settings.anthropic_api_key", None)
    chunks = [_mk("a"), _mk("b")]
    assert pytest_run(llm_judge_rerank, "q", chunks) == chunks


def test_llm_judge_sends_cache_control_on_system_blocks(monkeypatch):
    monkeypatch.setattr("config.settings.llm_judge_enabled", True)
    monkeypatch.setattr("config.settings.anthropic_api_key", "sk-test")

    captured = {}
    class FakeMsg:
        content = [type("X", (), {"text": '[{"idx":1,"score":0.9},{"idx":0,"score":0.3}]'})()]
    class FakeClient:
        def __init__(self, *a, **k): pass
        class messages:
            @staticmethod
            def create(**kwargs):
                captured.update(kwargs)
                return FakeMsg()
    monkeypatch.setattr("anthropic.Anthropic", FakeClient)

    chunks = [_mk("a"), _mk("b")]
    out = pytest_run(llm_judge_rerank, "q", chunks)
    assert out[0].text == "b"  # idx=1 had higher score
    sys_blocks = captured["system"]
    assert any(b.get("cache_control", {}).get("type") == "ephemeral" for b in sys_blocks)


def pytest_run(fn, *args):
    import asyncio
    return asyncio.run(fn(*args))
```

**Step 2: Run, verify fail**

```bash
cd services/integration-agent && python -m pytest tests/test_llm_judge_service.py -v
```

**Step 3: Implement `llm_judge_service.py`**

```python
# services/llm_judge_service.py
"""Claude Haiku LLM-judge reranker — opt-in (ADR-X3).

Compliance (CLAUDE.md §1):
  - Sends chunks to Claude API (public network) ⇒ MUST be opt-in.
  - Use only with synthetic / public / Accenture-Internal data.
  - Prompt-cached system message reduces costs by ~90%.
"""
from __future__ import annotations
import json
import logging
import os
import re
from typing import Iterable

from config import settings
from services.retriever import ScoredChunk

logger = logging.getLogger(__name__)

_SYSTEM_TEMPLATE = (
    "You are a retrieval relevance judge.  Score each chunk 0-1 for the QUERY.\n"
    "Output JSON only: [{\"idx\": int, \"score\": float}, ...] in original input order.\n"
    "Do not invent chunks; do not skip any.  Be terse."
)


def _api_key() -> str | None:
    return settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")


async def llm_judge_rerank(
    query: str,
    chunks: list[ScoredChunk],
) -> list[ScoredChunk]:
    if not settings.llm_judge_enabled or not chunks:
        return chunks
    key = _api_key()
    if not key:
        logger.info("[LLM-judge] disabled — no ANTHROPIC_API_KEY.")
        return chunks
    try:
        import anthropic
    except ImportError:
        return chunks

    client = anthropic.Anthropic(api_key=key)
    user = "QUERY: " + query + "\n\nCHUNKS:\n" + "\n".join(
        f"[{i}] {c.text[:600]}" for i, c in enumerate(chunks)
    )
    try:
        msg = client.messages.create(
            model=settings.llm_judge_model,
            max_tokens=400,
            system=[
                {"type": "text", "text": _SYSTEM_TEMPLATE,
                 "cache_control": {"type": "ephemeral"}},
            ],
            messages=[{"role": "user", "content": user}],
        )
    except Exception as exc:
        logger.warning("[LLM-judge] Claude error — bypassing: %s", exc)
        return chunks

    raw = msg.content[0].text.strip()
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return chunks
    try:
        scores: list[dict] = json.loads(match.group())
    except Exception:
        return chunks

    rescored: list[ScoredChunk] = []
    for entry in scores:
        idx = entry.get("idx")
        sc = entry.get("score")
        if not isinstance(idx, int) or idx < 0 or idx >= len(chunks):
            continue
        c = chunks[idx]
        rescored.append(ScoredChunk(
            text=c.text, score=float(sc),
            source_label=c.source_label, tags=c.tags,
            doc_id=c.doc_id, semantic_type=c.semantic_type,
        ))
    return sorted(rescored, key=lambda c: c.score, reverse=True) or chunks
```

**Step 4: Run, verify pass**

```bash
cd services/integration-agent && python -m pytest tests/test_llm_judge_service.py -v
```

**Step 5: Wire into `HybridRetriever.retrieve()`** — after `cross_encoder_rerank`, before `top_k = ...`:

```python
        if settings.llm_judge_enabled:
            from services.llm_judge_service import llm_judge_rerank
            reranked = await llm_judge_rerank(
                query_text, reranked[:settings.llm_judge_top_k],
            )
```

**Step 6: Commit**

```bash
git add services/integration-agent/services/llm_judge_service.py services/integration-agent/services/retriever.py services/integration-agent/tests/test_llm_judge_service.py
git commit -m "feat(adr-x3): Claude Haiku LLM-judge reranker — opt-in cascade with prompt caching"
```

---

### Task X3.5: ADR + eval + tag

```bash
# Re-run eval (no re-ingest needed)
cd services/integration-agent
python -m tests.eval.run_rag_eval --label adr-x3-reranker --compare adr-x2-embedder

git add services/integration-agent/tests/eval/reports/adr-x3-reranker.{md,json} docs/adr/ADR-X3-reranker-rrf.md
git commit -m "docs(adr-x3): reranker + RRF — eval delta vs ADR-X2"
git tag pre-adr-x3-merge
```

---

## Phase 4 — ADR-X4 Contextual Retrieval

**Goal:** Prepend ~50–100 token "situating annotations" to every chunk before embedding (Anthropic Contextual Retrieval pattern).

### Task X4.1: Add config + pure prompt builder (TDD)

**Files:**
- Modify: `services/integration-agent/config.py`
- Create: `services/integration-agent/services/contextual_retrieval_service.py`
- Create: `services/integration-agent/tests/test_contextual_retrieval_service.py`

**Step 1: Add config flags**

```python
    # ── Contextual Retrieval (ADR-X4) ─────────────────────────────────────────
    contextual_retrieval_enabled: bool = True
    contextual_provider: str = "claude"     # "claude" | "ollama"
    contextual_model_claude: str = "claude-haiku-4-5"
    contextual_model_ollama: str = "llama3.1:8b"
    contextual_max_tokens: int = 120
```

**Step 2: Write failing tests** for:
1. Disabled → returns chunks unchanged
2. Claude unavailable + key absent → falls back to Ollama
3. `cache_control` present in Claude calls
4. Returned chunks have `<situating>...</situating>` prepended

```python
# tests/test_contextual_retrieval_service.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.contextual_retrieval_service import add_context_to_chunks
from document_parser import DoclingChunk


def _ch(t, idx=0):
    return DoclingChunk(text=t, chunk_type="text", page_num=1,
                        section_header="S", index=idx, metadata={})


@pytest.mark.asyncio
async def test_returns_unchanged_when_disabled(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", False)
    chunks = [_ch("hello")]
    out = await add_context_to_chunks("doc text", chunks)
    assert out == chunks


@pytest.mark.asyncio
async def test_uses_ollama_when_no_claude_key(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", True)
    monkeypatch.setattr("config.settings.contextual_provider", "claude")
    monkeypatch.setattr("config.settings.anthropic_api_key", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    fake_ollama = AsyncMock(return_value="situating phrase")
    monkeypatch.setattr(
        "services.contextual_retrieval_service._call_ollama_for_context", fake_ollama,
    )
    out = await add_context_to_chunks("FULL DOC", [_ch("chunk-x")])
    assert "situating phrase" in out[0].text
    assert "chunk-x" in out[0].text
    fake_ollama.assert_awaited()


@pytest.mark.asyncio
async def test_claude_call_uses_cache_control(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", True)
    monkeypatch.setattr("config.settings.contextual_provider", "claude")
    monkeypatch.setattr("config.settings.anthropic_api_key", "sk-test")

    captured = {}
    class FakeMsg:
        content = [type("T", (), {"text": "situating ctx"})()]

    class FakeClient:
        def __init__(self, *a, **k): pass
        class messages:
            @staticmethod
            def create(**kw):
                captured.update(kw)
                return FakeMsg()

    monkeypatch.setattr("anthropic.Anthropic", FakeClient)
    out = await add_context_to_chunks("DOC", [_ch("c")])
    sys_blocks = captured["system"]
    assert any(b.get("cache_control", {}).get("type") == "ephemeral" for b in sys_blocks)
    assert "situating ctx" in out[0].text


@pytest.mark.asyncio
async def test_failure_returns_original_chunks(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", True)
    monkeypatch.setattr("config.settings.contextual_provider", "claude")
    monkeypatch.setattr("config.settings.anthropic_api_key", "sk")

    class Boom:
        def __init__(self, *a, **k): pass
        class messages:
            @staticmethod
            def create(**kw):
                raise RuntimeError("anthropic down")
    monkeypatch.setattr("anthropic.Anthropic", Boom)

    monkeypatch.setattr(
        "services.contextual_retrieval_service._call_ollama_for_context",
        AsyncMock(side_effect=RuntimeError("ollama down")),
    )
    chunks = [_ch("x")]
    out = await add_context_to_chunks("DOC", chunks)
    assert out == chunks   # graceful — never crashes ingestion
```

**Step 3: Run, verify fail**

```bash
cd services/integration-agent && python -m pytest tests/test_contextual_retrieval_service.py -v
```

**Step 4: Implement `contextual_retrieval_service.py`**

```python
# services/contextual_retrieval_service.py
"""Contextual Retrieval (ADR-X4) — Anthropic Sept-2024 pattern.

Prepends a 50-100 token "situating annotation" to each chunk before embedding.
Anthropic reports +35% recall@20 with embeddings only, +49% with BM25 + reranker.

Provider selection:
  - Claude (default) — uses prompt caching aggressively (system + full doc cached
    once per ingestion, then iterates per chunk).
  - Ollama (fallback) — degraded but offline.

Compliance (CLAUDE.md §1):
  - Doc text is sent to Claude API → only synthetic / public / Accenture-Internal data.
"""
from __future__ import annotations
import asyncio
import logging
import os
from typing import Optional

import httpx

from config import settings
from document_parser import DoclingChunk

logger = logging.getLogger(__name__)

_SITUATING_SYSTEM = (
    "You contextualize text chunks for retrieval.\n"
    "Given a full document and one chunk, write 1-2 sentences (≤100 tokens) that "
    "describe where this chunk sits in the document and what it is about.\n"
    "Output ONLY the situating annotation, no preface, no XML tags."
)

_OLLAMA_PROMPT = (
    "<document>\n{doc}\n</document>\n\n"
    "<chunk>\n{chunk}\n</chunk>\n\n"
    "Situate the chunk in the document in 1-2 sentences (≤100 tokens). "
    "Output the situating annotation only."
)


def _claude_key() -> str | None:
    return settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")


def _wrap(situating: str, original: str) -> str:
    return f"<situating>\n{situating.strip()}\n</situating>\n\n<original>\n{original}\n</original>"


async def _call_claude_for_context(
    client, doc_text: str, chunk_text: str,
) -> str:
    msg = await asyncio.to_thread(
        client.messages.create,
        model=settings.contextual_model_claude,
        max_tokens=settings.contextual_max_tokens,
        system=[
            {"type": "text", "text": _SITUATING_SYSTEM,
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": f"<document>\n{doc_text}\n</document>",
             "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user",
                   "content": f"<chunk>\n{chunk_text}\n</chunk>"}],
    )
    return msg.content[0].text.strip()


async def _call_ollama_for_context(doc_text: str, chunk_text: str) -> str:
    payload = {
        "model": settings.contextual_model_ollama,
        "prompt": _OLLAMA_PROMPT.format(doc=doc_text[:8000], chunk=chunk_text[:2000]),
        "stream": False,
        "options": {"num_predict": settings.contextual_max_tokens, "temperature": 0.0},
    }
    async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as http:
        r = await http.post(f"{settings.ollama_host}/api/generate", json=payload)
        r.raise_for_status()
        return (r.json().get("response") or "").strip()


async def add_context_to_chunks(
    doc_text: str,
    chunks: list[DoclingChunk],
) -> list[DoclingChunk]:
    if not settings.contextual_retrieval_enabled or not chunks:
        return chunks

    use_claude = settings.contextual_provider == "claude" and _claude_key()
    client = None
    if use_claude:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=_claude_key())
        except Exception as exc:
            logger.warning("[Ctx-Retrieval] anthropic init failed (%s) — using Ollama.", exc)
            use_claude = False

    out: list[DoclingChunk] = []
    for c in chunks:
        situating: Optional[str] = None
        try:
            if use_claude and client is not None:
                situating = await _call_claude_for_context(client, doc_text, c.text)
            else:
                situating = await _call_ollama_for_context(doc_text, c.text)
        except Exception as exc:
            logger.warning("[Ctx-Retrieval] failed for chunk %d (%s) — keeping original.",
                           c.index, exc)
        if situating:
            out.append(DoclingChunk(
                text=_wrap(situating, c.text),
                chunk_type=c.chunk_type,
                page_num=c.page_num,
                section_header=c.section_header,
                index=c.index,
                metadata={**c.metadata, "contextualized": True},
            ))
        else:
            out.append(c)
    return out
```

**Step 5: Run, verify pass**

```bash
cd services/integration-agent && python -m pytest tests/test_contextual_retrieval_service.py -v
# Expected: 4 passed
```

**Step 6: Commit**

```bash
git add services/integration-agent/services/contextual_retrieval_service.py services/integration-agent/tests/test_contextual_retrieval_service.py services/integration-agent/config.py
git commit -m "feat(adr-x4): contextual_retrieval_service — Claude with caching, Ollama fallback"
```

---

### Task X4.2: Wire contextual retrieval into kb upload pipeline

**Files:**
- Modify: `services/integration-agent/routers/kb.py:_process_kb_file` (line ~140)

**Step 1: Inject the contextual step between Docling parse and ChromaDB upsert**

```python
    # _process_kb_file — schematic diff, after docling_chunks is produced

    # ADR-X4: prepend situating annotations before embedding
    if settings.contextual_retrieval_enabled and len(docling_chunks) > 1:
        from services.contextual_retrieval_service import add_context_to_chunks
        full_doc = "\n\n".join(c.text for c in docling_chunks)
        try:
            docling_chunks = await add_context_to_chunks(full_doc, docling_chunks)
        except Exception as exc:
            log_agent(f"[KB] Contextual retrieval failed (graceful): {exc}")
```

**Step 2: Apply identical change in ingestion-platform pipeline.**

**Step 3: Add an integration test** in `tests/test_kb_upload_docling.py`:

```python
@pytest.mark.asyncio
async def test_kb_upload_invokes_contextual_retrieval_when_enabled(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", True)
    monkeypatch.setattr(
        "services.contextual_retrieval_service.add_context_to_chunks",
        AsyncMock(side_effect=lambda d, c: c),  # passthrough
    )
    # … upload a sample file via TestClient and assert add_context was awaited
```

**Step 4: Run regression**

```bash
cd services/integration-agent && python -m pytest tests/test_kb_upload_docling.py tests/test_kb_endpoints.py -v
```

**Step 5: Commit**

```bash
git add services/integration-agent/routers/kb.py services/ingestion-platform/ services/integration-agent/tests/test_kb_upload_docling.py
git commit -m "feat(adr-x4): wire contextual retrieval into KB upload pipeline"
```

---

### Task X4.3: ADR + re-ingest + eval

```bash
# Re-ingest KB
# (UI batch-upload of fixtures)

cd services/integration-agent
python -m tests.eval.run_rag_eval --label adr-x4-contextual --compare adr-x3-reranker

git add services/integration-agent/tests/eval/reports/adr-x4-contextual.{md,json} docs/adr/ADR-X4-contextual-retrieval.md
git commit -m "docs(adr-x4): contextual retrieval — eval delta vs ADR-X3 (expecting +35-49% recall@20)"
git tag pre-adr-x4-merge
```

---

## Phase 5 — Final Cleanup

### Task 5.1: Update documentation

**Files:**
- Modify: `docs/architecture_specification.md` (CLAUDE.md §14 mandatory)
- Modify: `functional-guide.md` (CLAUDE.md §14 mandatory)
- Create: `HOW-TO/how-to-rag-pipeline-modernized.md`

```bash
git commit -m "docs: update architecture_specification + functional-guide for ADR-X1..X4"
```

### Task 5.2: Removal of deprecated paths (after 2-sprint observation)

**Optional, do not execute immediately:**
- Remove `_ensemble_merge` and `_tfidf_rerank` from `retriever.py`
- Remove `vision_service._PLACEHOLDER`-only code path (legacy)
- Remove `embedder_provider == "default"` branch

```bash
# After confirming stability for 2 sprints
git commit -m "chore: remove deprecated weighted-merge / TF-IDF rerank / default embedder paths"
```

---

## Definition of Done — entire programme

- [ ] All 5 phases merged in order: Eval → X1 → X2 → X3 → X4
- [ ] All 329+ existing tests still green
- [ ] New tests added: ~60+ across embedding_function, vlm fallback, RRF, reranker, llm_judge, contextual_retrieval
- [ ] Eval reports show monotonically improving recall@5 / MRR / NDCG / recall@20
- [ ] `docs/adr/ADR-X1..X4-*.md` created using `ADR-000-template.md`
- [ ] `architecture_specification.md` + `functional-guide.md` updated
- [ ] `HOW-TO/how-to-rag-eval.md` + `HOW-TO/how-to-rag-pipeline-modernized.md` created
- [ ] No restricted data in `tests/eval/fixtures/sample_kb_corpus/` (CLAUDE.md §1)
- [ ] Compliance G3 mitigation in place: runtime banner + warning log when `ANTHROPIC_API_KEY` is consumed by X3 / X4
- [ ] Per-ADR rollback flags verified by manual smoke test (toggle off → previous behavior restored)
- [ ] Git tags `pre-adr-x{1..4}-merge` annotated on `main`

---

## Quick command reference

```bash
# Run all tests
cd services/integration-agent && python -m pytest tests/ -v

# Run only eval-harness tests
cd services/integration-agent && python -m pytest tests/eval/ -v

# Capture baseline + per-ADR runs
python -m tests.eval.run_rag_eval --label baseline
python -m tests.eval.run_rag_eval --label adr-x1-parser    --compare baseline
python -m tests.eval.run_rag_eval --label adr-x2-embedder  --compare baseline
python -m tests.eval.run_rag_eval --label adr-x3-reranker  --compare adr-x2-embedder
python -m tests.eval.run_rag_eval --label adr-x4-contextual --compare adr-x3-reranker

# Rollback flags (env vars)
export VLM_FORCE_FALLBACK=true                  # X1 → LLaVA only
export EMBEDDER_PROVIDER=default                # X2 → ChromaDB MiniLM
export RERANKER_ENABLED=false                   # X3 → TF-IDF
export RAG_USE_RRF=false                        # X3 → weighted-merge
export CONTEXTUAL_RETRIEVAL_ENABLED=false       # X4 → no situating
```
