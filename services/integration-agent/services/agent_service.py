"""
Agent Service — core document generation logic.
ADR-026 (R15): extracted from main.py; shared by agent router and approvals router.

Exposes:
  generate_integration_doc() — full RAG + LLM pipeline for one catalog entry.
  _enrich_with_claude()      — optional post-processing via Claude API to fill
                               any residual 'n/a' sections (ANTHROPIC_API_KEY required).
"""

import logging
import os
import re
from typing import Callable

from config import settings
from output_guard import sanitize_llm_output
from prompt_builder import build_prompt, get_integration_template
from services.llm_service import generate_with_retry
from services.rag_service import ContextAssembler, fetch_url_kb_context
from services.retriever import ScoredChunk, hybrid_retriever
import state

logger = logging.getLogger(__name__)


_TEMPLATE_SECTION_COUNT = 16  # number of ## sections in integration_base_template.md
_MIN_SECTIONS_FOR_COMPLETE = 14  # tolerate up to 2 missing sections before forcing completion


async def _enrich_with_claude(
    content: str,
    source: str,
    target: str,
    requirements_text: str,
) -> str:
    """
    Post-process the LLM output with Claude to fix incomplete or n/a-heavy documents.

    Called when ANTHROPIC_API_KEY is set AND at least one of:
      - The document has fewer than _MIN_SECTIONS_FOR_COMPLETE '##' sections
        (Ollama hit the num_predict token cap before finishing all 16 sections)
      - The document contains at least one 'n/a' occurrence

    Returns the enriched/completed document, or the original on any error.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return content

    generated_sections = len(re.findall(r"^## ", content, re.MULTILINE))
    is_truncated = generated_sections < _MIN_SECTIONS_FOR_COMPLETE
    has_na = bool(re.search(r"\bn/a\b", content, re.IGNORECASE))

    if not is_truncated and not has_na:
        return content

    try:
        import anthropic  # lazy import — not required in dev/test environments

        client = anthropic.Anthropic(api_key=api_key)

        if is_truncated:
            logger.info(
                "[Claude] Document truncated (%d/%d sections) for %s → %s — completing...",
                generated_sections, _TEMPLATE_SECTION_COUNT, source, target,
            )
            task_description = (
                f"The document is INCOMPLETE — the local model stopped after section "
                f"{generated_sections} of {_TEMPLATE_SECTION_COUNT} due to token limits.\n\n"
                f"**Your task:**\n"
                f"1. Keep ALL existing content unchanged.\n"
                f"2. Add every MISSING section (those not yet present) following the "
                f"standard integration template structure below.\n"
                f"3. Also replace any `n/a` entries with real content where possible.\n\n"
                f"EXPECTED TEMPLATE STRUCTURE (use section headings exactly as shown):\n"
                f"{get_integration_template()}"
            )
        else:
            logger.info(
                "[Claude] Enriching n/a sections (%d sections present) for %s → %s...",
                generated_sections, source, target,
            )
            task_description = (
                "Some sections are marked `n/a` because the local model lacked context.\n\n"
                "**Your task:** Replace every `n/a` section with accurate, concise content "
                f"based on typical {source} to {target} integration patterns and industry "
                "best practices. Keep ALL existing non-n/a content unchanged."
            )

        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=8000,
            messages=[{
                "role": "user",
                "content": (
                    f"You are a senior integration architect specializing in enterprise "
                    f"system integrations.\n\n"
                    f"Below is an Integration Design document for **{source} → {target}**.\n\n"
                    f"**Integration requirements:**\n{requirements_text}\n\n"
                    f"{task_description}\n\n"
                    f"Output the COMPLETE document starting with `# Integration Design`.\n"
                    f"Do NOT add any preamble or explanation before the document heading.\n\n"
                    f"DOCUMENT SO FAR:\n\n{content}"
                ),
            }],
        )
        enriched = message.content[0].text.strip()
        logger.info(
            "[Claude] Enrichment complete — %d → %d chars", len(content), len(enriched)
        )
        return enriched

    except Exception as exc:
        logger.warning("[Claude] Enrichment failed (non-blocking): %s", exc)
        return content


async def generate_integration_doc(
    entry,                                         # CatalogEntry (avoid circular import with schemas)
    requirements: list,                            # list[Requirement]
    reviewer_feedback: str = "",
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """
    Run the full RAG + LLM pipeline for a single catalog entry.

    Pipeline:
      1. Multi-query hybrid retrieval (approved_integrations + knowledge_base collections)
      2. Live URL KB context fetch
      3. RAPTOR-lite section summary retrieval (ADR-032)
      4. Context assembly via ContextAssembler
      5. Prompt construction (with optional reviewer_feedback injection)
      6. LLM generation with retry (Ollama)
      7. Output sanitization via sanitize_llm_output()
      8. Optional Claude enrichment to fill residual 'n/a' sections

    Args:
        entry:              CatalogEntry with source, target, tags, requirements
        requirements:       List of Requirement objects
        reviewer_feedback:  Optional feedback from a previous HITL rejection.
                            Injected as "## PREVIOUS REJECTION FEEDBACK" before RAG context.
        log_fn:             Optional logging callback (defaults to module logger.info).

    Returns:
        Sanitized (and optionally enriched) markdown string starting with
        '# Integration Design'.

    Raises:
        LLMOutputValidationError: if sanitize_llm_output() rejects the output.
        httpx.*: on LLM connectivity errors — caller must handle these.
    """
    _log = log_fn or logger.info

    source = entry.source.get("system", "Unknown")
    target = entry.target.get("system", "Unknown")
    query_text = " ".join(r.description for r in requirements)
    category = entry.tags[0] if entry.tags else ""

    _log(f"[RAG] Hybrid retrieval for {entry.id} (tags={entry.tags})...")
    approved_chunks = await hybrid_retriever.retrieve(
        query_text, entry.tags, state.collection,
        source=source, target=target, category=category, log_fn=_log,
    )
    kb_scored_chunks = await hybrid_retriever.retrieve(
        query_text, entry.tags, state.kb_collection,
        source=source, target=target, category=category, log_fn=_log,
    )
    url_raw = await fetch_url_kb_context(entry.tags, state.kb_docs, log_fn=_log)
    url_chunks = (
        [ScoredChunk(text=url_raw, score=0.5, source_label="kb_url")]
        if url_raw else []
    )

    # RAPTOR-lite: retrieve section-level summaries for overview context (ADR-032)
    summary_chunks = await hybrid_retriever.retrieve_summaries(
        query_text, entry.tags, state.summaries_col,
    )

    assembler = ContextAssembler()
    rag_context = assembler.assemble(
        approved_chunks, kb_scored_chunks, url_chunks,
        max_chars=settings.ollama_rag_max_chars,
        summary_chunks=summary_chunks,
    )
    _log(
        f"[RAG] Assembled context: {len(rag_context)} chars"
        + (f" [with feedback: {len(reviewer_feedback)} chars]" if reviewer_feedback else "")
    )

    prompt = build_prompt(
        source_system=source,
        target_system=target,
        formatted_requirements=query_text,
        rag_context=rag_context,
        reviewer_feedback=reviewer_feedback,
    )
    _log(f"[LLM] Prompt ready for {entry.id} — {len(prompt)} chars. Calling {settings.ollama_model}...")

    raw = await generate_with_retry(prompt, log_fn=_log)
    # The prompt ends with "# Integration Design" as a continuation seed so the
    # model generates the document body directly (no preamble).  Ollama returns
    # only the continuation — prepend the heading so the guard always finds it.
    if not raw.lstrip().startswith("# Integration Design"):
        raw = "# Integration Design\n" + raw
    sanitized = sanitize_llm_output(raw, doc_type="integration")

    # Optional: enrich residual n/a sections with Claude API (ANTHROPIC_API_KEY required)
    enriched = await _enrich_with_claude(
        content=sanitized,
        source=source,
        target=target,
        requirements_text=query_text,
    )
    return enriched
