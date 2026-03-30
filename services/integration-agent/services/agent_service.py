"""
Agent Service — core document generation logic.
ADR-026 (R15): extracted from main.py; shared by agent router and approvals router.

Exposes:
  generate_integration_doc() — full RAG + LLM pipeline for one catalog entry.
"""

import logging
from typing import Callable

from config import settings
from output_guard import sanitize_llm_output
from prompt_builder import build_prompt, build_technical_prompt
from services.llm_service import generate_with_retry
from services.rag_service import ContextAssembler, fetch_url_kb_context
from services.retriever import ScoredChunk, hybrid_retriever
import state

logger = logging.getLogger(__name__)


async def generate_integration_doc(
    entry,                                         # CatalogEntry (avoid circular import with schemas)
    requirements: list,                            # list[Requirement]
    reviewer_feedback: str = "",
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """
    Run the full RAG + LLM pipeline for a single catalog entry.

    Performs:
      1. Multi-query hybrid retrieval (approved_integrations + knowledge_base collections)
      2. Live URL KB context fetch
      3. Context assembly via ContextAssembler
      4. Prompt construction (with optional reviewer_feedback injection)
      5. LLM generation with retry
      6. Output sanitization via sanitize_llm_output()

    Args:
        entry:              CatalogEntry with source, target, tags, requirements
        requirements:       List of Requirement objects (descriptions used as query text)
        reviewer_feedback:  Optional feedback from a previous HITL rejection.
                            Injected as "## PREVIOUS REJECTION FEEDBACK" before RAG context.
        log_fn:             Optional logging callback (defaults to module logger.info).

    Returns:
        Sanitized markdown string.

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

    # RAPTOR-lite: retrieve section-level summaries for overview context (ADR-032).
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
    return sanitize_llm_output(raw)


async def generate_technical_doc(
    entry,                                         # CatalogEntry (avoid circular import with schemas)
    functional_spec_content: str,
    reviewer_feedback: str = "",
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """
    Run the RAG + LLM pipeline to generate a technical design document.

    ADR-038: Second phase of two-phase doc generation.
    Uses the approved functional spec as primary context alongside KB RAG.

    Args:
        entry:                   CatalogEntry (source, target, tags)
        functional_spec_content: Approved functional spec markdown (primary context)
        reviewer_feedback:       Optional HITL rejection feedback for regeneration
        log_fn:                  Optional logging callback

    Returns:
        Sanitized markdown string starting with "# Integration Technical Design".

    Raises:
        LLMOutputValidationError: if output guard rejects the LLM output.
        httpx.*: on LLM connectivity errors — caller must handle these.
    """
    _log = log_fn or logger.info

    source = entry.source.get("system", "Unknown")
    target = entry.target.get("system", "Unknown")
    query_text = f"technical design {source} {target} " + " ".join(entry.tags)
    category = entry.tags[0] if entry.tags else ""

    _log(f"[RAG-TECH] KB retrieval for {entry.id} (tags={entry.tags})...")
    kb_scored_chunks = await hybrid_retriever.retrieve(
        query_text, entry.tags, state.kb_collection,
        source=source, target=target, category=category, log_fn=_log,
    )
    summary_chunks = await hybrid_retriever.retrieve_summaries(
        query_text, entry.tags, state.summaries_col,
    )
    url_raw = await fetch_url_kb_context(entry.tags, state.kb_docs, log_fn=_log)
    url_chunks = (
        [ScoredChunk(text=url_raw, score=0.5, source_label="kb_url")]
        if url_raw else []
    )

    assembler = ContextAssembler()
    # approved_chunks intentionally empty — technical phase uses functional_spec as primary context (ADR-038)
    rag_context = assembler.assemble(
        [], kb_scored_chunks, url_chunks,
        max_chars=settings.ollama_rag_max_chars,
        summary_chunks=summary_chunks,
    )
    _log(f"[RAG-TECH] Assembled context: {len(rag_context)} chars")

    prompt = build_technical_prompt(
        source_system=source,
        target_system=target,
        # formatted_requirements is a label here — the approved functional_spec_content
        # is the authoritative requirements source for the technical phase (ADR-038).
        formatted_requirements=f"{source} → {target} integration",
        functional_spec=functional_spec_content,
        rag_context=rag_context,
        reviewer_feedback=reviewer_feedback,
    )
    _log(f"[LLM-TECH] Prompt ready for {entry.id} — {len(prompt)} chars. Calling {settings.ollama_model}...")

    raw = await generate_with_retry(prompt, log_fn=_log)
    return sanitize_llm_output(raw, doc_type="technical")
