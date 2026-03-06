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
