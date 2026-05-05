"""CLI runner for RAG eval harness.

Usage:
  # List available question domains
  python tests/eval/run_rag_eval.py --list-domains

  # Run a single domain
  python tests/eval/run_rag_eval.py --label baseline --domain plm_pim_dam

  # Run multiple domains (questions merged)
  python tests/eval/run_rag_eval.py --label baseline --domains plm_pim_dam,commerce

  # Run all domains
  python tests/eval/run_rag_eval.py --label baseline --domain all

  # Compare against a previous run
  python tests/eval/run_rag_eval.py --label after-x3 --domain plm_pim_dam --compare baseline

  # Legacy: no --domain flag → defaults to 'all'
  python tests/eval/run_rag_eval.py --label baseline
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


REPORTS_DIR = Path(__file__).parent / "reports"
DOMAINS_DIR = Path(__file__).parent / "domains"

# Kept for backward compatibility (used by legacy tests that pass a path directly)
GOLDEN_PATH = Path(__file__).parent / "golden_questions.yaml"


# ── Domain discovery ──────────────────────────────────────────────────────────

def list_domains() -> list[str]:
    """Return sorted list of available domain names (stem of YAML files in domains/)."""
    if not DOMAINS_DIR.exists():
        return []
    return sorted(p.stem for p in DOMAINS_DIR.glob("*.yaml"))


def load_domain(domain: str) -> list[dict]:
    """Load questions from domains/<domain>.yaml. Raises FileNotFoundError if missing."""
    path = DOMAINS_DIR / f"{domain}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Domain '{domain}' not found. "
            f"Available: {list_domains() or ['(none)']}"
        )
    with open(path) as f:
        return yaml.safe_load(f) or []


def load_golden_questions(
    path: Path | None = None,
    domain: str | None = None,
    domains: list[str] | None = None,
) -> list[dict]:
    """Load golden questions.

    Resolution order:
    1. ``path`` — explicit file path (legacy / test use).
    2. ``domains`` — list of domain names (merged, deduped by id).
    3. ``domain`` — single name or "all" (loads every domain in DOMAINS_DIR).
    4. Default — "all" domains if DOMAINS_DIR exists, else legacy GOLDEN_PATH.
    """
    if path is not None:
        with open(path) as f:
            return yaml.safe_load(f) or []

    if domains:
        return _merge_domains(domains)

    if domain == "all" or (domain is None and DOMAINS_DIR.exists()):
        return _merge_domains(list_domains())

    if domain:
        return load_domain(domain)

    # Absolute fallback: legacy single file
    with open(GOLDEN_PATH) as f:
        return yaml.safe_load(f) or []


def _merge_domains(domain_names: list[str]) -> list[dict]:
    """Load and merge questions from multiple domains, deduped by id."""
    seen: set[str] = set()
    merged: list[dict] = []
    for name in domain_names:
        for q in load_domain(name):
            qid = q.get("id", "")
            if qid not in seen:
                seen.add(qid)
                merged.append(q)
    return merged


# ── Report rendering ──────────────────────────────────────────────────────────

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
    lines = [
        f"# RAG Eval Comparison — {label_a} vs {label_b}",
        "",
        "| metric | A | B | Δ abs | Δ % |",
        "|--------|---|---|-------|-----|",
    ]
    for k in metrics_a.keys() & metrics_b.keys():
        a, b = metrics_a[k], metrics_b[k]
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            d_abs = b - a
            d_pct = (d_abs / a * 100.0) if a != 0 else float("nan")
            lines.append(
                f"| {k} | {a:.3f} | {b:.3f} | {d_abs:+.3f} | {d_pct:+.0f}% |"
            )
    return "\n".join(lines) + "\n"


# ── Persistence ───────────────────────────────────────────────────────────────

def _save_run(label: str, metrics: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{label}.json"
    path.write_text(json.dumps(metrics, indent=2))
    return path


def _load_run(label: str) -> dict:
    return json.loads((REPORTS_DIR / f"{label}.json").read_text())


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run RAG eval harness against a domain question set.",
    )
    parser.add_argument("--label", default=None,
                        help="Name for this run (used as report filename). "
                             "Required unless --list-domains.")
    parser.add_argument("--domain", default=None,
                        help="Single domain name or 'all'. "
                             "Mutually exclusive with --domains.")
    parser.add_argument("--domains", default=None,
                        help="Comma-separated domain names, e.g. plm_pim_dam,commerce.")
    parser.add_argument("--list-domains", action="store_true",
                        help="Print available domains and exit.")
    parser.add_argument("--output", type=Path, default=None,
                        help="Override output .md path (default: reports/<label>.md).")
    parser.add_argument("--compare", default=None,
                        help="Label of a previous run to diff against.")
    args = parser.parse_args(argv)

    if args.list_domains:
        available = list_domains()
        if available:
            print("Available domains:")
            for d in available:
                print(f"  {d}")
        else:
            print("No domains found in", DOMAINS_DIR)
        return 0

    if not args.label:
        parser.error("--label is required unless --list-domains is set.")

    if args.domain and args.domains:
        parser.error("--domain and --domains are mutually exclusive.")

    domains_list = (
        [d.strip() for d in args.domains.split(",") if d.strip()]
        if args.domains else None
    )

    questions = load_golden_questions(
        domain=args.domain,
        domains=domains_list,
    )

    if not questions:
        print("No questions loaded. Check --domain / --domains or add files to", DOMAINS_DIR)
        return 1

    from tests.eval.runner import execute_pipeline
    metrics = execute_pipeline(questions)

    _save_run(args.label, metrics)

    if args.compare:
        baseline = _load_run(args.compare)
        report_md = compare_runs(args.compare, baseline, args.label, metrics)
    else:
        report_md = render_report(args.label, metrics, n_queries=len(questions))

    out = args.output or (REPORTS_DIR / f"{args.label}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_md)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
