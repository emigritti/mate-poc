"""
Agent Service — core document generation logic.
ADR-026 (R15): extracted from main.py; shared by agent router and approvals router.
ADR-041: FactPack intermediate layer for two-step LLM pipeline.

Exposes:
  generate_integration_doc() — full RAG + LLM pipeline for one catalog entry.
  _enrich_with_claude()      — optional post-processing via Claude API to fill
                               any residual 'n/a' sections (ANTHROPIC_API_KEY required).
                               Only invoked in the single-pass fallback path.
"""

import logging
import os
import re
from collections import Counter
from typing import Callable

from config import settings
from output_guard import assess_quality, sanitize_llm_output
from prompt_builder import build_prompt, get_integration_template
from schemas import ClaimReport, GenerationReport, SectionReport, SourceChunkInfo
from services.fact_pack_service import (
    FactPack,
    extract_fact_pack,
    render_document_sections,
    validate_fact_pack,
    _CONFIDENCE_WEIGHTS,
)
from services.llm_service import generate_with_retry, llm_overrides
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

    Called only in the single-pass fallback path when ANTHROPIC_API_KEY is set AND
    at least one of:
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


def _chunks_to_source_info(
    chunks: list[ScoredChunk],
    label_override: str | None = None,
) -> list[SourceChunkInfo]:
    """Convert a list of ScoredChunk objects into SourceChunkInfo records."""
    seen_previews: set[str] = set()
    result: list[SourceChunkInfo] = []
    for i, c in enumerate(chunks):
        label = label_override or c.source_label
        # Prefer explicit doc_id from ChromaDB metadata; fall back to tags or index
        doc_id = c.doc_id or (" / ".join(c.tags) if c.tags else f"chunk-{i}")
        preview = c.text[:150].replace("\n", " ").strip()
        if preview in seen_previews:
            continue
        seen_previews.add(preview)
        result.append(SourceChunkInfo(
            source_label=label,
            doc_id=doc_id,
            score=round(c.score, 3),
            preview=preview,
        ))
    return result


def _build_section_reports(
    fact_pack: FactPack,
    document_content: str,
) -> tuple[list[SectionReport], list[ClaimReport]]:
    """
    Derive per-section and per-claim reports from FactPack.evidence (ADR-041).

    Algorithm:
      1. Parse ## headings from document_content to build section list.
      2. For each section, find EvidenceClaims whose statement keywords appear
         in the corresponding section text (simple substring matching).
      3. Compute section confidence as weighted average of matched claim levels.
         Sections with no matched claims default to 0.5 (neutral / unverified).
      4. Build ClaimReport for every EvidenceClaim in the FactPack.

    Returns:
        (list[SectionReport], list[ClaimReport])
    """
    # Build claim reports from all evidence
    claim_reports: list[ClaimReport] = [
        ClaimReport(
            claim_id=e.claim_id,
            statement=e.statement,
            confidence=e.confidence,
            source_chunk_count=len(e.source_chunks),
        )
        for e in fact_pack.evidence
    ]

    # Parse ## headings and their body text from the document
    section_pattern = re.compile(r"^## (.+)$", re.MULTILINE)
    heading_matches = list(section_pattern.finditer(document_content))

    section_reports: list[SectionReport] = []
    for idx, match in enumerate(heading_matches):
        section_name = match.group(1).strip()
        section_start = match.start()
        section_end = (
            heading_matches[idx + 1].start()
            if idx + 1 < len(heading_matches)
            else len(document_content)
        )
        section_text = document_content[section_start:section_end].lower()

        # Find claims whose key terms appear in this section
        matched_claims = [
            e for e in fact_pack.evidence
            if any(
                word.lower() in section_text
                for word in e.statement.split()
                if len(word) > 4  # skip short words
            )
        ]

        if matched_claims:
            weights = [_CONFIDENCE_WEIGHTS.get(e.confidence, 0.5) for e in matched_claims]
            section_confidence = round(sum(weights) / len(weights), 3)
            source_chunk_ids = list({
                chunk_id
                for e in matched_claims
                for chunk_id in e.source_chunks
            })
            issues: list[str] = []
            if section_confidence < 0.4:
                issues.append("low_evidence_density")
            if any(e.confidence == "missing_evidence" for e in matched_claims):
                issues.append("missing_evidence")
        else:
            section_confidence = 0.5  # unverified — no matched claims
            source_chunk_ids = []
            issues = ["unverified"]

        section_reports.append(SectionReport(
            section=section_name,
            source_chunk_ids=source_chunk_ids,
            confidence=section_confidence,
            issues=issues,
        ))

    return section_reports, claim_reports


async def generate_integration_doc(
    entry,                                         # CatalogEntry (avoid circular import with schemas)
    requirements: list,                            # list[Requirement]
    reviewer_feedback: str = "",
    log_fn: Callable[[str], None] | None = None,
    pinned_chunks: list | None = None,
    llm_profile: str = "default",                  # "default" | "high_quality" (ADR-046)
) -> tuple[str, GenerationReport]:
    """
    Run the full RAG + LLM pipeline for a single catalog entry.

    Pipeline (ADR-041 two-step path, with graceful degradation to single-pass):
      1. Multi-query hybrid retrieval (approved_integrations + knowledge_base collections)
      2. Live URL KB context fetch
      3. RAPTOR-lite section summary retrieval (ADR-032)
      4. Context assembly via ContextAssembler
      --- ADR-041 two-step path (when settings.fact_pack_enabled=True) ---
      5a. extract_fact_pack()    — LLM extracts structured JSON facts
      5b. validate_fact_pack()   — pure-Python evidence validation
      5c. render_document_sections() — LLM renders 16 sections from FactPack
      --- single-pass fallback (when FactPack extraction fails or is disabled) ---
      5d. build_prompt() + generate_with_retry() — original single-pass pipeline
      5e. _enrich_with_claude() — fills residual n/a (only in fallback path)
      ---
      6. sanitize_llm_output()   — structural guard + XSS sanitization
      7. assess_quality()        — quality metrics
      8. build GenerationReport  — enhanced with section_reports / claim_reports

    Args:
        entry:              CatalogEntry with source, target, tags, requirements
        requirements:       List of Requirement objects
        reviewer_feedback:  Optional feedback from a previous HITL rejection.
                            Injected as "## PREVIOUS REJECTION FEEDBACK" in the
                            single-pass fallback path only.
        log_fn:             Optional logging callback (defaults to module logger.info).
        pinned_chunks:      Optional pre-selected chunks (pinned KB references).

    Returns:
        Tuple of (sanitized markdown string, GenerationReport).

    Raises:
        LLMOutputValidationError: if sanitize_llm_output() rejects the output.
        httpx.*: on LLM connectivity errors — caller must handle these.
    """
    _log = log_fn or logger.info

    # Resolve LLM model and sampling parameters for this profile (ADR-046).
    # "high_quality" is the user-facing name; "premium" accepted as legacy alias.
    if llm_profile in ("high_quality", "premium"):
        _llm_model = llm_overrides.get("premium_model", settings.premium_model)
        _llm_kw: dict = dict(
            model=_llm_model,
            num_predict=llm_overrides.get("premium_num_predict",    settings.premium_num_predict),
            timeout=llm_overrides.get("premium_timeout_seconds",    settings.premium_timeout_seconds),
            temperature=llm_overrides.get("premium_temperature",    settings.premium_temperature),
            num_ctx=llm_overrides.get("premium_num_ctx",            settings.premium_num_ctx),
            top_p=llm_overrides.get("premium_top_p",                settings.premium_top_p),
            top_k=llm_overrides.get("premium_top_k",                settings.premium_top_k),
            repeat_penalty=llm_overrides.get("premium_repeat_penalty", settings.premium_repeat_penalty),
        )
    else:
        _llm_model = llm_overrides.get("model", settings.ollama_model)
        _llm_kw = {}   # generate_with_retry reads defaults from llm_overrides / settings

    _log(f"[LLM] profile={llm_profile!r} model={_llm_model}")

    source = entry.source.get("system", "Unknown")
    target = entry.target.get("system", "Unknown")
    query_text = " ".join(r.description for r in requirements)
    category = entry.tags[0] if entry.tags else ""

    # ── Stage 1: Retrieval (unchanged) ───────────────────────────────────────
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

    # ── Stage 2: Context Assembly (unchanged) ────────────────────────────────
    assembler = ContextAssembler()
    rag_context = assembler.assemble(
        approved_chunks, kb_scored_chunks, url_chunks,
        max_chars=settings.ollama_rag_max_chars,
        summary_chunks=summary_chunks,
        pinned_chunks=pinned_chunks or [],
    )
    _log(
        f"[RAG] Assembled context: {len(rag_context)} chars"
        + (f" [with feedback: {len(reviewer_feedback)} chars]" if reviewer_feedback else "")
    )

    # ── Stage 3: Generation (two-step or single-pass) ─────────────────────────
    fact_pack: FactPack | None = None
    prompt_chars: int = 0
    claude_was_applied = False

    if settings.fact_pack_enabled:
        # ADR-041 two-step path
        fact_pack = await extract_fact_pack(
            rag_context=rag_context,
            source=source,
            target=target,
            requirements_text=query_text,
            log_fn=_log,
        )
        if fact_pack is not None:
            fact_pack = validate_fact_pack(fact_pack, source, target)

    if fact_pack is not None:
        # Two-step path: render document from FactPack
        # ADR-042 bugfix: reviewer_feedback is now forwarded so HITL feedback is
        # not silently dropped when fact_pack_used=True.
        prompt_chars = fact_pack.extraction_chars
        raw = await render_document_sections(
            fact_pack=fact_pack,
            source=source,
            target=target,
            requirements_text=query_text,
            document_template=get_integration_template(),
            reviewer_feedback=reviewer_feedback,
            log_fn=_log,
        )
    else:
        # Single-pass fallback: original pipeline (always used when fact_pack disabled or failed)
        if settings.fact_pack_enabled:
            _log("[FactPack] Extraction unavailable — falling back to single-pass pipeline.")
        prompt = build_prompt(
            source_system=source,
            target_system=target,
            formatted_requirements=query_text,
            rag_context=rag_context,
            reviewer_feedback=reviewer_feedback,
        )
        prompt_chars = len(prompt)
        _log(f"[LLM] Prompt ready for {entry.id} — {prompt_chars} chars. Calling {_llm_model}...")
        raw = await generate_with_retry(prompt, log_fn=_log, **_llm_kw)

    # ── Stage 4: Sanitization (unchanged) ────────────────────────────────────
    # The prompt ends with "# Integration Design" as a continuation seed so the
    # model generates the document body directly (no preamble). Ollama returns
    # only the continuation — prepend the heading so the guard always finds it.
    if not raw.lstrip().startswith("# Integration Design"):
        raw = "# Integration Design\n" + raw
    sanitized = sanitize_llm_output(raw, doc_type="integration")

    # ── Stage 5: Enrichment (single-pass path only) ───────────────────────────
    # In the FactPack path, evidence gaps are rendered explicitly — no n/a filling needed.
    if fact_pack is None:
        enriched = await _enrich_with_claude(
            content=sanitized,
            source=source,
            target=target,
            requirements_text=query_text,
        )
        claude_was_applied = enriched != sanitized
    else:
        enriched = sanitized

    # ── Stage 6: Quality Assessment (unchanged) ───────────────────────────────
    quality = assess_quality(enriched)

    # ── Stage 7: Build enhanced GenerationReport ──────────────────────────────
    all_sources: list[SourceChunkInfo] = (
        _chunks_to_source_info(approved_chunks, label_override="approved_example")
        + _chunks_to_source_info(kb_scored_chunks)   # label derived from metadata
        + _chunks_to_source_info(url_chunks, label_override="kb_url")
        + _chunks_to_source_info(summary_chunks, label_override="summary")
    )
    model_used = _llm_model

    section_reports: list[SectionReport] = []
    claim_reports: list[ClaimReport] = []
    confirmed_count = inferred_count = missing_count = validate_count = 0

    if fact_pack is not None:
        section_reports, claim_reports = _build_section_reports(fact_pack, enriched)
        conf_counts = Counter(e.confidence for e in fact_pack.evidence)
        confirmed_count = conf_counts["confirmed"]
        inferred_count  = conf_counts["inferred"]
        missing_count   = conf_counts["missing_evidence"]
        validate_count  = conf_counts["to_validate"]

    report = GenerationReport(
        model=model_used,
        prompt_chars=prompt_chars,
        context_chars=len(rag_context),
        sources=all_sources,
        sections_count=quality.section_count,
        na_count=len(re.findall(r"\bn/a\b", enriched, re.IGNORECASE)),
        quality_score=quality.quality_score,
        quality_issues=quality.issues,
        claude_enriched=claude_was_applied,
        # FactPack fields (ADR-041)
        fact_pack_used=(fact_pack is not None),
        fact_pack_extraction_model=fact_pack.extraction_model if fact_pack else "",
        section_reports=section_reports,
        claim_reports=claim_reports,
        confirmed_claim_count=confirmed_count,
        inferred_claim_count=inferred_count,
        missing_evidence_count=missing_count,
        to_validate_count=validate_count,
    )

    return enriched, report
