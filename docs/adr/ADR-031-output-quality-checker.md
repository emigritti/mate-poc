# ADR-031 — Output Quality Checker

| Field        | Value                                                     |
|--------------|-----------------------------------------------------------|
| **Status**   | Accepted                                                  |
| **Date**     | 2026-03-20                                                |
| **Tags**     | output-guard, quality, llm, phase3                        |

## Context
The LLM output guard (`output_guard.py`) validates structural safety (injection, length, forbidden patterns)
but does not assess content completeness. Generated functional specs may pass structural validation yet
contain excessive `n/a` placeholders, fewer sections than required, or insufficient word count — making
them uninformative for HITL reviewers.

## Decision
Add `assess_quality(content: str) -> QualityReport` to `output_guard.py`.
Three signals are checked:
- **Section count** ≥ 5 (`## ` headings in Markdown)
- **n/a ratio** < 50% of sections
- **Word count** ≥ 100

`QualityReport` is a dataclass with `quality_score` (0.0–1.0, average of three sub-scores),
`passed` (bool), and `issues` (list of human-readable warnings).

Quality assessment is **warning-only** — it never rejects content or triggers automatic retry.
The quality score and issues are logged to the agent log stream so HITL reviewers can use them
as signal during manual review.

## Alternatives Considered
- **LLM-as-judge**: call a second LLM to rate output quality — too slow and expensive for a PoC; adds a second point of Ollama dependency
- **Regex-per-section**: parse each section's content individually — too brittle; heading names are not standardised
- **Auto-retry on low score**: regenerate automatically if quality is poor — would remove HITL control over retry timing and increase latency unpredictably

## Validation Plan
- Unit tests: `tests/test_output_guard.py` — `TestAssessQuality` class, 7 tests covering: good doc passes, all-na doc fails, low word count fails, short section count fails, zero sections, partial na mix, score calculation

## Rollback
Remove `assess_quality()` import and call from `routers/agent.py`. No data migration needed.
