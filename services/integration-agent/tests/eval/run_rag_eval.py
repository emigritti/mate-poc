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
