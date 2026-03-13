"""
Integration Agent — Prompt Builder
ADR-014: Prompt construction from versioned reusable-meta-prompt.md.

Reads the fenced ``text`` block from the meta-prompt file at startup and
exposes a single build_prompt() function.  If the file is missing, a
safe inline fallback is used — the agent never crashes due to a missing
prompt file.

The functional design template (template/functional/integration-functional-design.md)
is loaded separately and injected into the prompt via the {document_template} slot.
This decouples template structure from prompt behaviour — both files are versioned
independently under docs control.
"""

import pathlib
import re
import logging

logger = logging.getLogger(__name__)

# ── File paths ──────────────────────────────────────────────────────────────────
# Both paths are relative to this file: ../../<target>
_PROMPT_FILE = pathlib.Path(__file__).parent.parent.parent / "reusable-meta-prompt.md"
_FUNCTIONAL_TEMPLATE_PATH = (
    pathlib.Path(__file__).parent.parent.parent
    / "template"
    / "functional"
    / "integration-functional-design.md"
)

# ── Fallback templates ──────────────────────────────────────────────────────────
# Used when the respective files cannot be loaded.
_FALLBACK_TEMPLATE = (
    "You are an elite Subject Matter Expert in the Product Management Domain.\n"
    "You are supporting companies to address their requirements regarding the integration between PLM, PIM, DAM, Merchandising Tools.\n"
    "extract best practices and patterns for integration design, and produce a functional design document for the integration.\n\n"
    "Fill in EVERY section of the following template for an integration between "
    "{source_system} (Source) and {target_system} (Target).\n"
    "For any section with no information write exactly `n/a`.\n\n"
    "Requirements:\n{formatted_requirements}\n\n"
    "{rag_context}\n\n"
    "TEMPLATE:\n{document_template}\n\n"
    "Output ONLY valid Markdown. Begin immediately with "
    "`# Integration Functional Design`."
)


def _load_template() -> str:
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
        logger.warning(
            "[PromptBuilder] %s not found — using fallback.", _PROMPT_FILE
        )
    return _FALLBACK_TEMPLATE


def _load_functional_template() -> str:
    """Load the functional design template from the template directory.

    The template file uses backslash-escaped markdown (\\#, \\##, \\-) to
    prevent editor rendering.  Those escapes are stripped here at load time
    so the LLM receives clean Markdown syntax, reducing prompt token count
    and avoiding model confusion.
    """
    try:
        content = _FUNCTIONAL_TEMPLATE_PATH.read_text(encoding="utf-8")
        # Strip backslash escapes from Markdown heading/list markers.
        # Process longest prefix first (###, ##, #) to avoid double-stripping.
        content = content.replace(r"\### ", "### ")
        content = content.replace(r"\## ", "## ")
        content = content.replace(r"\# ", "# ")
        content = content.replace(r"\- ", "- ")
        content = content.replace(r"\| ", "| ")
        logger.info(
            "[PromptBuilder] Loaded functional template from %s",
            _FUNCTIONAL_TEMPLATE_PATH,
        )
        return content
    except FileNotFoundError:
        logger.warning(
            "[PromptBuilder] %s not found — {document_template} slot will be empty.",
            _FUNCTIONAL_TEMPLATE_PATH,
        )
        return ""


# Load once at import time; both files are immutable during a run.
_TEMPLATE: str = _load_template()
_FUNCTIONAL_TEMPLATE: str = _load_functional_template()


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
    # F-09 / CLAUDE.md §10: sequential str.replace() instead of str.format()
    # prevents KeyError/ValueError if the template file contains unknown
    # placeholders or if user-supplied values contain '{...}' patterns.
    result = _TEMPLATE
    result = result.replace("{source_system}", source_system)
    result = result.replace("{target_system}", target_system)
    result = result.replace("{formatted_requirements}", formatted_requirements)
    result = result.replace("{rag_context}", rag_block)
    result = result.replace("{document_template}", _FUNCTIONAL_TEMPLATE)
    return result
