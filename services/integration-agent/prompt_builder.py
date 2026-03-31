"""
Integration Agent — Prompt Builder

Reads the fenced ``text`` block from reusable-meta-prompt.md at startup and
exposes a single build_prompt() function. If the file is missing, a safe
inline fallback is used — the agent never crashes due to a missing prompt file.

The unified integration template (template/integration_base_template.md) is
loaded separately and injected into the prompt via the {document_template} slot.
This decouples template structure from prompt behaviour — both files are versioned
independently under docs control.

All sections of the template MUST be filled. The agent_service layer applies
a Claude API enrichment step to replace any residual 'n/a' placeholders.
"""

import pathlib
import re
import logging

logger = logging.getLogger(__name__)

# ── File paths ──────────────────────────────────────────────────────────────────
_PROMPT_FILE = pathlib.Path(__file__).parent.parent.parent / "reusable-meta-prompt.md"
_TEMPLATE_PATH = (
    pathlib.Path(__file__).parent.parent.parent
    / "template"
    / "integration_base_template.md"
)

# ── Fallback template (used when files cannot be loaded) ──────────────────────
_FALLBACK_TEMPLATE = (
    "You are an elite Subject Matter Expert in enterprise system integration.\n"
    "Fill in EVERY section of the following template for an integration between "
    "{source_system} (Source) and {target_system} (Target).\n"
    "For any section with no information write exactly `n/a`.\n\n"
    "Requirements:\n{formatted_requirements}\n\n"
    "{rag_context}\n\n"
    "TEMPLATE:\n{document_template}\n\n"
    "Output ONLY valid Markdown. Begin immediately with `# Integration Design`."
)


def _load_meta_prompt() -> str:
    """Extract the fenced ``text`` block from the meta-prompt markdown file."""
    try:
        raw = _PROMPT_FILE.read_text(encoding="utf-8")
        match = re.search(r"```text\n(.*?)```", raw, re.DOTALL)
        if match:
            logger.info("[PromptBuilder] Loaded meta-prompt from %s", _PROMPT_FILE)
            return match.group(1).strip()
        logger.warning(
            "[PromptBuilder] No ```text``` block in %s — using fallback.", _PROMPT_FILE
        )
    except FileNotFoundError:
        logger.warning("[PromptBuilder] %s not found — using fallback.", _PROMPT_FILE)
    return _FALLBACK_TEMPLATE


def _load_integration_template() -> str:
    """Load the unified integration design template.

    Strips backslash-escaped markdown markers (\\#, \\##, \\-) that editors
    add to prevent live rendering of template headings/lists.
    Normalises CRLF → LF so Docker (Linux) receives clean line endings.
    """
    try:
        content = _TEMPLATE_PATH.read_text(encoding="utf-8")
        # Normalise Windows line endings before further processing
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        content = content.replace(r"\### ", "### ")
        content = content.replace(r"\## ", "## ")
        content = content.replace(r"\# ", "# ")
        content = content.replace(r"\- ", "- ")
        content = content.replace(r"\| ", "| ")
        content = content.replace(r"\& ", "& ")
        content = content.replace(r"\---", "---")
        logger.info("[PromptBuilder] Loaded integration template from %s", _TEMPLATE_PATH)
        return content
    except FileNotFoundError:
        logger.warning(
            "[PromptBuilder] %s not found — {document_template} slot will be empty.",
            _TEMPLATE_PATH,
        )
        return ""


# Load once at import time — both files are immutable during a run.
_META_PROMPT: str = _load_meta_prompt()
_INTEGRATION_TEMPLATE: str = _load_integration_template()


def get_integration_template() -> str:
    """Return the loaded integration template (used by enrichment to detect missing sections)."""
    return _INTEGRATION_TEMPLATE


def build_prompt(
    source_system: str,
    target_system: str,
    formatted_requirements: str,
    rag_context: str = "",
    kb_context: str = "",
    reviewer_feedback: str = "",
) -> str:
    """
    Populate the meta-prompt with runtime values.

    Args:
        source_system:           Name of the integration source system.
        target_system:           Name of the integration target system.
        formatted_requirements:  Concatenated requirement descriptions.
        rag_context:             Past approved examples from ChromaDB (may be empty).
        kb_context:              Best-practice reference from Knowledge Base (may be empty).
        reviewer_feedback:       Optional feedback from a previous HITL rejection.
                                 Injected before RAG context as "## PREVIOUS REJECTION FEEDBACK".

    Returns:
        A fully populated prompt string ready to be sent to the LLM.
    """
    feedback_block = (
        f"## PREVIOUS REJECTION FEEDBACK (address these issues in your output):\n"
        f"{reviewer_feedback.strip()}\n\n"
        if reviewer_feedback.strip()
        else ""
    )
    rag_block = (
        f"PAST APPROVED EXAMPLES:\n{rag_context}"
        if rag_context.strip()
        else ""
    )
    kb_block = (
        f"BEST PRACTICES REFERENCE:\n{kb_context}"
        if kb_context.strip()
        else ""
    )
    # Feedback prepended before RAG examples — LLM sees previous issues before examples
    combined_context = f"{feedback_block}{rag_block}" if feedback_block else rag_block

    # F-09 / CLAUDE.md §10: sequential str.replace() prevents KeyError/ValueError
    # if the template file contains unknown placeholders or if user-supplied
    # values contain '{...}' patterns.
    result = _META_PROMPT
    result = result.replace("{source_system}", source_system)
    result = result.replace("{target_system}", target_system)
    result = result.replace("{formatted_requirements}", formatted_requirements)
    result = result.replace("{rag_context}", combined_context)
    result = result.replace("{kb_context}", kb_block)
    result = result.replace("{document_template}", _INTEGRATION_TEMPLATE)
    return result
