"""
Integration Agent — LLM Output Sanitization Guard
ADR-015: LLM output is ALWAYS treated as untrusted input (CLAUDE.md §10-11).

Two functions are exposed:
  - sanitize_llm_output()    : strict guard for machine-generated content.
  - sanitize_human_content() : lenient guard for HITL-edited markdown.

Quality gate (document-quality improvement #1):
  - assess_quality()         : non-destructive quality assessment (5 signals).
  - enforce_quality_gate()   : raises QualityGateError or warns based on mode.

OWASP A03 / Agentic AI injection mitigations:
  1. Structural guard — LLM output MUST start with the expected heading.
  2. HTML strip via bleach allowlist — prevents stored XSS in the dashboard.
  3. Hard truncation — prevents resource exhaustion from runaway generation.
"""

import logging
import bleach
from dataclasses import dataclass, field
import re

logger = logging.getLogger(__name__)

# ── Allowlist ──────────────────────────────────────────────────────────────────
# Only elements that a standard markdown renderer produces are allowed.
# <script>, <iframe>, <object>, <embed>, event handlers — all stripped.
_ALLOWED_TAGS: list[str] = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr",
    "ul", "ol", "li",
    "strong", "em", "code", "pre", "blockquote",
    "table", "thead", "tbody", "tr", "th", "td",
    "a",
]
_ALLOWED_ATTRS: dict[str, list[str]] = {"a": ["href", "title"]}

# ── Constants ──────────────────────────────────────────────────────────────────
_MAX_CHARS: int = 50_000
_REQUIRED_PREFIX: str = "# Integration Design"
# Legacy map kept for backward compatibility with existing tests
_REQUIRED_PREFIX_BY_TYPE: dict[str, str] = {
    "integration": _REQUIRED_PREFIX,
    "functional":  _REQUIRED_PREFIX,   # legacy alias
    "technical":   _REQUIRED_PREFIX,   # legacy alias
}

# ── Quality thresholds ─────────────────────────────────────────────────────────
# The integration_base_template.md has 16 ## sections; tolerate up to 6 missing.
_MIN_SECTION_COUNT: int = 10       # at least 10 ## headings expected
_MAX_NA_RATIO: float = 0.30        # max 30% of sections can be n/a
_MIN_WORD_COUNT: int = 300         # minimum meaningful word count
_MIN_MAPPING_TABLES: int = 1       # at least 1 Markdown pipe table (data mapping)

# Patterns for new quality signals
_MERMAID_RE = re.compile(r"```mermaid", re.IGNORECASE)
_TABLE_SEP_RE = re.compile(r"^\|[\s\-|:]+\|", re.MULTILINE)   # separator row
_PLACEHOLDER_RE = re.compile(
    r"\[TODO\]|\[TBD\]|\[PLACEHOLDER\]|\[INSERT[^\]]*\]|\bTODO:|\[ADD HERE\]",
    re.IGNORECASE,
)

# ── Quality gate threshold ─────────────────────────────────────────────────────
_QUALITY_GATE_MIN_SCORE: float = 0.60


# ── Exceptions ─────────────────────────────────────────────────────────────────
class LLMOutputValidationError(ValueError):
    """Raised when LLM output fails the structural guard."""


class QualityGateError(ValueError):
    """Raised when document quality is below the minimum threshold (block mode)."""


# ── Public API ─────────────────────────────────────────────────────────────────

def sanitize_llm_output(raw: str, doc_type: str = "integration") -> str:
    """
    Validate and sanitize LLM-generated markdown (strict mode).

    Strategy:
      1. Fast path  — output starts with the required heading: use as-is.
      2. Fallback   — LLM added a preamble: find the heading and strip before it.
      3. Hard fail  — required heading not found anywhere: reject.

    Args:
        raw:      Raw LLM output string.
        doc_type: "integration" (default). Legacy values "functional"/"technical" are accepted.

    Raises:
        LLMOutputValidationError: if the required prefix is absent entirely.

    Returns:
        Sanitized markdown string, truncated to _MAX_CHARS.
    """
    required_prefix = _REQUIRED_PREFIX_BY_TYPE.get(doc_type, _REQUIRED_PREFIX_BY_TYPE["functional"])

    if not raw or not raw.strip():
        raise LLMOutputValidationError("LLM returned empty output.")

    text = raw.strip()

    # Fast path — correct output
    if text.startswith(required_prefix):
        return _apply_bleach_and_truncate(text)

    # Fallback 1 — exact heading present but preceded by a preamble
    idx = text.find(required_prefix)
    if idx != -1:
        logger.warning(
            "[OutputGuard] Preamble detected (%d chars stripped) before '%s'.",
            idx,
            required_prefix,
        )
        return _apply_bleach_and_truncate(text[idx:])

    # Fallback 2 — model used a slightly different heading (case / extra words).
    # Matches: "# Integration Design", "# Integration Design Document",
    # "# PLM to SAP Integration Design", etc. — any H1 containing the key phrase.
    relaxed = re.search(r"^#[^#].*Integration\s+Design", text, re.MULTILINE | re.IGNORECASE)
    if relaxed:
        stripped_chars = relaxed.start()
        logger.warning(
            "[OutputGuard] Relaxed heading match '%s' at offset %d — preamble stripped.",
            text[relaxed.start(): relaxed.start() + 60].replace("\n", " "),
            stripped_chars,
        )
        return _apply_bleach_and_truncate(text[relaxed.start():])

    # Hard fail — no integration design heading found anywhere
    logger.error(
        "[OutputGuard] Structural guard hard-fail. First 300 chars: %r", text[:300]
    )
    raise LLMOutputValidationError(
        f"Output must contain '{required_prefix}'. "
        "Got: {!r}".format(text[:120])
    )


def sanitize_human_content(raw: str) -> str:
    """
    Sanitize human-edited markdown (lenient mode — no structural guard).

    Used for HITL reviewer edits in approve_doc().  The reviewer may
    legitimately change headings, so the structural guard is NOT applied.
    HTML stripping and truncation still protect against clipboard paste attacks.

    Returns:
        Sanitized markdown string, truncated to _MAX_CHARS.
    """
    if not raw:
        return ""
    return _apply_bleach_and_truncate(raw)


# ── Quality Assessment ─────────────────────────────────────────────────────────

@dataclass
class QualityReport:
    """Non-destructive quality assessment of an LLM-generated document."""
    section_count: int
    na_ratio: float
    word_count: int
    has_mermaid_diagram: bool
    mapping_table_count: int
    placeholder_count: int
    quality_score: float
    passed: bool
    issues: list[str] = field(default_factory=list)


def assess_quality(content: str) -> QualityReport:
    """
    Assess LLM output quality without modifying content.

    Signals checked (6 total):
      1. section_count      — number of ## level-2 headings (min: _MIN_SECTION_COUNT)
      2. na_ratio           — fraction of n/a vs section_count (max: _MAX_NA_RATIO)
      3. word_count         — total word count (min: _MIN_WORD_COUNT)
      4. has_mermaid_diagram — at least one ```mermaid block required
      5. mapping_table_count — at least _MIN_MAPPING_TABLES pipe tables required
      6. placeholder_count  — zero [TODO]/[TBD]/[PLACEHOLDER] markers allowed

    Call AFTER sanitize_llm_output() — content is already stripped of HTML.
    Returns a QualityReport with .passed and .issues (always list[str], never None).
    """
    issues: list[str] = []

    # ── Signal 1: section count ────────────────────────────────────────────────
    section_count = len(re.findall(r"^## ", content, re.MULTILINE))
    if section_count < _MIN_SECTION_COUNT:
        issues.append(
            f"Too few sections: {section_count} (expected >= {_MIN_SECTION_COUNT})."
        )

    # ── Signal 2: n/a ratio ────────────────────────────────────────────────────
    na_count = len(re.findall(r"\bn/a\b", content, re.IGNORECASE))
    na_ratio = (na_count / section_count) if section_count > 0 else 1.0
    if na_ratio > _MAX_NA_RATIO:
        issues.append(
            f"High n/a ratio: {na_ratio:.0%} of sections lack real content "
            f"(max allowed: {_MAX_NA_RATIO:.0%})."
        )

    # ── Signal 3: word count ───────────────────────────────────────────────────
    word_count = len(content.split())
    if word_count < _MIN_WORD_COUNT:
        issues.append(
            f"Document too short: {word_count} words (expected >= {_MIN_WORD_COUNT})."
        )

    # ── Signal 4: Mermaid diagram ──────────────────────────────────────────────
    has_mermaid_diagram = bool(_MERMAID_RE.search(content))
    if not has_mermaid_diagram:
        issues.append("Missing Mermaid diagram — at least one ```mermaid block required.")

    # ── Signal 5: mapping/data tables ─────────────────────────────────────────
    # Count Markdown table separator rows (e.g. "| --- | --- |") as table proxies.
    mapping_table_count = len(_TABLE_SEP_RE.findall(content))
    if mapping_table_count < _MIN_MAPPING_TABLES:
        issues.append(
            f"No data mapping table found — at least {_MIN_MAPPING_TABLES} Markdown "
            "pipe table(s) required."
        )

    # ── Signal 6: placeholder markers ─────────────────────────────────────────
    placeholder_count = len(_PLACEHOLDER_RE.findall(content))
    if placeholder_count > 0:
        issues.append(
            f"Document contains {placeholder_count} unfilled placeholder(s) "
            "([TODO]/[TBD]/[PLACEHOLDER]/TODO: etc.)."
        )

    # ── Composite score ────────────────────────────────────────────────────────
    section_score   = min(1.0, section_count / _MIN_SECTION_COUNT)
    na_score        = max(0.0, 1.0 - na_ratio / _MAX_NA_RATIO) if _MAX_NA_RATIO > 0 else 0.0
    word_score      = min(1.0, word_count / _MIN_WORD_COUNT)
    diagram_score   = 1.0 if has_mermaid_diagram else 0.0
    table_score     = min(1.0, mapping_table_count / _MIN_MAPPING_TABLES)
    placeholder_score = 1.0 if placeholder_count == 0 else max(0.0, 1.0 - placeholder_count * 0.25)
    quality_score = round(
        (section_score + na_score + word_score + diagram_score + table_score + placeholder_score) / 6,
        2,
    )

    return QualityReport(
        section_count=section_count,
        na_ratio=round(na_ratio, 2),
        word_count=word_count,
        has_mermaid_diagram=has_mermaid_diagram,
        mapping_table_count=mapping_table_count,
        placeholder_count=placeholder_count,
        quality_score=quality_score,
        passed=len(issues) == 0,
        issues=issues,
    )


def enforce_quality_gate(
    report: QualityReport,
    min_score: float = _QUALITY_GATE_MIN_SCORE,
    mode: str = "warn",
) -> None:
    """
    Enforce quality gate before HITL dispatch.

    Args:
        report:    QualityReport from assess_quality().
        min_score: Minimum composite score required to pass (default 0.60).
        mode:      "block" → raises QualityGateError on failure.
                   "warn"  → logs warning, allows document through (default).

    Raises:
        QualityGateError: only when mode="block" and quality is insufficient.
    """
    failed = not report.passed or report.quality_score < min_score
    if not failed:
        return

    issue_summary = "; ".join(report.issues) if report.issues else "score below threshold"
    msg = (
        f"Quality gate failed — score={report.quality_score:.2f} "
        f"(min={min_score:.2f}): {issue_summary}"
    )
    if mode == "block":
        raise QualityGateError(msg)
    else:
        logger.warning("[QualityGate] %s (mode=warn — document forwarded to HITL)", msg)


# ── Internal ───────────────────────────────────────────────────────────────────

def _apply_bleach_and_truncate(text: str) -> str:
    if len(text) > _MAX_CHARS:
        logger.warning(
            "[OutputGuard] Content truncated from %d to %d chars.", len(text), _MAX_CHARS
        )
        text = text[:_MAX_CHARS]

    return bleach.clean(
        text,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        strip=True,        # strip disallowed tags rather than escaping them
    )
