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
from prompt_builder import build_prompt
from services.llm_service import generate_with_retry
from services.rag_service import ContextAssembler, fetch_url_kb_context
from services.retriever import ScoredChunk, hybrid_retriever
import state

logger = logging.getLogger(__name__)


async def _enrich_with_claude(
    content: str,
    source: str,
    target: str,
    requirements_text: str,
) -> str:
    """
    Post-process the LLM output with Claude to fill any 'n/a' or thin sections.

    Called only when:
      - ANTHROPIC_API_KEY is set in the environment
      - The document contains at least one 'n/a' occurrence

    Returns the enriched document, or the original on any error (graceful degradation).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return content

    # Skip enrichment if there are no n/a sections
    if not re.search(r"\bn/a\b", content, re.IGNORECASE):
        return content

    try:
        import anthropic  # lazy import — not required in dev/test environments

        client = anthropic.Anthropic(api_key=api_key)
        logger.info("[Claude] Enriching n/a sections for %s → %s integration...", source, target)

        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=8000,
            messages=[{
                "role": "user",
                "content": (
                    f"You are a senior integration architect specializing in enterprise system integrations.\n\n"
                    f"Below is an Integration Design document for **{source} → {target}**. "
                    f"Some sections are marked `n/a` because the local AI model lacked sufficient context.\n\n"
                    f"**Integration requirements provided by the analyst:**\n{requirements_text}\n\n"
                    f"**Your task:** Replace every `n/a` section with accurate, concise content based on "
                    f"typical {source} to {target} integration patterns and industry best practices. "
                    f"Keep ALL existing non-n/a content unchanged. "
                    f"Output the COMPLETE document starting with `# Integration Design`.\n\n"
                    f"DOCUMENT TO ENRICH:\n\n{content}"
                ),
            }],
        )
        enriched = message.content[0].text.strip()
        logger.info("[Claude] Enrichment complete — %d → %d chars", len(content), len(enriched))
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
    sanitized = sanitize_llm_output(raw, doc_type="integration")

    # Optional: enrich residual n/a sections with Claude API (ANTHROPIC_API_KEY required)
    enriched = await _enrich_with_claude(
        content=sanitized,
        source=source,
        target=target,
        requirements_text=query_text,
    )
    return enriched
