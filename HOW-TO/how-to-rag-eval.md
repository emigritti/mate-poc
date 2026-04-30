# How To — Run RAG Eval Harness

The eval harness produces empirical recall@k / MRR / NDCG / faithfulness metrics
to gate every ADR in the RAG pipeline modernization
(`docs/plans/2026-04-30-rag-pipeline-modernization-design.md`).

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

Note: `faithfulness_substring` is a *retrieval-coverage proxy* — it checks
whether the top-3 retrieved chunks contain the must-include tokens. It is
NOT end-to-end LLM-answer faithfulness (use `llm_judge_faithfulness` for that).

## Compliance note (CLAUDE.md §1)

Use only synthetic / public / Accenture-Internal-classified data in
`tests/eval/fixtures/sample_kb_corpus/`. Never commit real client data.

## Faithfulness (LLM-judge)

When `ANTHROPIC_API_KEY` is exported, `llm_judge_faithfulness` calls Claude
Haiku to score answer-context faithfulness 0-5. Without the key the metric is
reported as `n/a` and the run continues. Inputs sent to Claude must be
synthetic / public / Accenture-Internal data only (CLAUDE.md §1).

## Test-only entry points

- `tests/eval/test_metrics_retrieval.py` — pure-function tests for `recall_at_k`, `mrr`, `ndcg_at_k`
- `tests/eval/test_metrics_faithfulness.py` — substring + mocked LLM-judge tests
- `tests/eval/test_run_rag_eval.py` — CLI helpers (load/render/compare)
- `tests/eval/test_runner.py` — pipeline orchestration with mocked retriever

Run them in isolation (no live stack required):

```bash
cd services/integration-agent && python -m pytest tests/eval/ -v
```

Expected: 22 passed.
