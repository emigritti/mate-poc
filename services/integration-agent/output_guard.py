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
_REQUIRED_PREFIX: str = "# Functional Specification"


# ── Exceptions ─────────────────────────────────────────────────────────────────
class LLMOutputValidationError(ValueError):
    """Raised when LLM output fails the structural guard."""


# ── Public API ─────────────────────────────────────────────────────────────────

def sanitize_llm_output(raw: str) -> str:
    """
    Validate and sanitize LLM-generated markdown (strict mode).

    Raises:
        LLMOutputValidationError: if the output does not start with the
            expected heading, indicating the LLM deviated from instructions
            or an injection replaced the real output.

    Returns:
        Sanitized markdown string, truncated to _MAX_CHARS.
    """
    if not raw or not raw.strip().startswith(_REQUIRED_PREFIX):
        raise LLMOutputValidationError(
            f"Output must begin with '{_REQUIRED_PREFIX}'. "
            "Got: {!r}".format((raw or "")[:80])
        )

    return _apply_bleach_and_truncate(raw)


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
