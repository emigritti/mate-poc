"""
Integration Agent — Prompt Builder
ADR-014: Prompt construction from versioned reusable-meta-prompt.md.

Reads the fenced ``text`` block from the meta-prompt file at startup and
exposes a single build_prompt() function.  If the file is missing, a
safe inline fallback is used — the agent never crashes due to a missing
prompt file.

This decouples prompt evolution (documentation edit) from code changes,
while keeping the prompt under version control.
"""

import pathlib
import re
import logging

logger = logging.getLogger(__name__)

# Path relative to this file: ../../reusable-meta-prompt.md
_PROMPT_FILE = pathlib.Path(__file__).parent.parent.parent / "reusable-meta-prompt.md"

# Inline fallback — used when the meta-prompt file cannot be loaded.
# Mirrors the same slot names so callers need no changes.
_FALLBACK_TEMPLATE = (
    "You are an elite Enterprise Integration Architect.\n"
    "Write a Functional Specification in strictly formatted Markdown for an "
    "integration between {source_system} (Source) and {target_system} (Target).\n\n"
    "Requirements:\n{formatted_requirements}\n\n"
    "{rag_context}\n\n"
    "Output ONLY valid Markdown. Begin immediately with "
    "`# Functional Specification`."
)


def _load_template() -> str:
    """Extract the fenced ``text`` block from the meta-prompt markdown file."""
    try:
        raw = _PROMPT_FILE.read_text(encoding="utf-8")
        match = re.search(r"```text\n(.*?)```", raw, re.DOTALL)
        if match:
            logger.info("[PromptBuilder] Loaded template from %s", _PROMPT_FILE)
            return match.group(1).strip()
        logger.warning(
            "[PromptBuilder] No ```text``` block in %s — using fallback.", _PROMPT_FILE
        )
    except FileNotFoundError:
        logger.warning(
            "[PromptBuilder] %s not found — using fallback.", _PROMPT_FILE
        )
    return _FALLBACK_TEMPLATE


# Load once at import time; the template is immutable during a run.
_TEMPLATE: str = _load_template()


def build_prompt(
    source_system: str,
    target_system: str,
    formatted_requirements: str,
    rag_context: str = "",
) -> str:
    """
    Populate the meta-prompt template with runtime values.

    Args:
        source_system:           Name of the integration source system.
        target_system:           Name of the integration target system.
        formatted_requirements:  Concatenated requirement descriptions.
        rag_context:             Past approved examples from ChromaDB (may be empty).

    Returns:
        A fully populated prompt string ready to be sent to the LLM.
    """
    rag_block = (
        f"PAST APPROVED EXAMPLES:\n{rag_context}"
        if rag_context.strip()
        else ""
    )
    return _TEMPLATE.format(
        source_system=source_system,
        target_system=target_system,
        formatted_requirements=formatted_requirements,
        rag_context=rag_block,
    )
