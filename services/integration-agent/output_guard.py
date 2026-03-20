"""
Integration Agent — LLM Output Sanitization Guard
ADR-015: LLM output is ALWAYS treated as untrusted input (CLAUDE.md §10-11).

Two functions are exposed:
  - sanitize_llm_output()    : strict guard for machine-generated content.
  - sanitize_human_content() : lenient guard for HITL-edited markdown.

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
_REQUIRED_PREFIX: str = "# Integration Functional Design"

# ── Quality thresholds (R14) ────────────────────────────────────────────────────
_MIN_SECTION_COUNT: int = 5    # at least 5 ## headings expected
_MAX_NA_RATIO: float = 0.5     # max 50% sections can be n/a
_MIN_WORD_COUNT: int = 50      # minimum meaningful content


# ── Exceptions ─────────────────────────────────────────────────────────────────
class LLMOutputValidationError(ValueError):
    """Raised when LLM output fails the structural guard."""


# ── Public API ─────────────────────────────────────────────────────────────────

def sanitize_llm_output(raw: str) -> str:
    """
    Validate and sanitize LLM-generated markdown (strict mode).

    Strategy:
      1. Fast path  — output starts with the required heading: use as-is.
      2. Fallback   — LLM added a preamble: find the heading and strip before it.
                      Small models (llama3.2:3b) routinely add courtesy intros
                      despite explicit instructions — this handles that gracefully.
      3. Hard fail  — required heading not found anywhere: reject. This catches
                      completely off-topic responses and prompt-injection attempts.

    Raises:
        LLMOutputValidationError: if _REQUIRED_PREFIX is absent entirely.

    Returns:
        Sanitized markdown string, truncated to _MAX_CHARS.
    """
    if not raw or not raw.strip():
        raise LLMOutputValidationError("LLM returned empty output.")

    text = raw.strip()

    # Fast path — correct output
    if text.startswith(_REQUIRED_PREFIX):
        return _apply_bleach_and_truncate(text)

    # Fallback — strip preamble added by the model
    idx = text.find(_REQUIRED_PREFIX)
    if idx != -1:
        logger.warning(
            "[OutputGuard] Preamble detected (%d chars stripped) before '%s'.",
            idx,
            _REQUIRED_PREFIX,
        )
        return _apply_bleach_and_truncate(text[idx:])

    # Hard fail — heading not found at all
    raise LLMOutputValidationError(
        f"Output must contain '{_REQUIRED_PREFIX}'. "
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


# ── Quality Assessment (R14) ────────────────────────────────────────────────────

@dataclass
class QualityReport:
    """Non-destructive quality assessment of an LLM-generated document."""
    section_count: int
    na_ratio: float
    word_count: int
    quality_score: float
    passed: bool
    issues: list[str] = field(default_factory=list)


def assess_quality(content: str) -> QualityReport:
    """
    Assess LLM output quality without modifying content.

    Signals checked:
      1. section_count  — number of ## level-2 headings (min: _MIN_SECTION_COUNT)
      2. na_ratio       — fraction of n/a occurrences vs section_count (max: _MAX_NA_RATIO)
      3. word_count     — total word count (min: _MIN_WORD_COUNT)

    Call AFTER sanitize_llm_output() — content is already stripped of HTML.
    Returns a QualityReport with .passed and .issues list (always a list[str], never None).
    """
    issues: list[str] = []

    section_count = len(re.findall(r"^## ", content, re.MULTILINE))
    na_count = len(re.findall(r"\bn/a\b", content, re.IGNORECASE))
    na_ratio = (na_count / section_count) if section_count > 0 else 1.0
    word_count = len(content.split())

    if section_count < _MIN_SECTION_COUNT:
        issues.append(
            f"Too few sections: {section_count} (expected >= {_MIN_SECTION_COUNT})."
        )
    if na_ratio > _MAX_NA_RATIO:
        issues.append(
            f"High n/a ratio: {na_ratio:.0%} of sections lack real content."
        )
    if word_count < _MIN_WORD_COUNT:
        issues.append(
            f"Document too short: {word_count} words (expected >= {_MIN_WORD_COUNT})."
        )

    section_score = min(1.0, section_count / _MIN_SECTION_COUNT)
    na_score = max(0.0, 1.0 - na_ratio / _MAX_NA_RATIO) if _MAX_NA_RATIO > 0 else 0.0
    word_score = min(1.0, word_count / _MIN_WORD_COUNT)
    quality_score = round((section_score + na_score + word_score) / 3, 2)

    return QualityReport(
        section_count=section_count,
        na_ratio=round(na_ratio, 2),
        word_count=word_count,
        quality_score=quality_score,
        passed=len(issues) == 0,
        issues=issues,
    )


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
