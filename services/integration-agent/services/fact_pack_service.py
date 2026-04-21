"""
FactPack Service — structured fact extraction and document rendering (ADR-041).
ADR-042: Prompt construction delegated to prompt_builder.py.

Introduces a two-step LLM pipeline:
  Step 1 — extract_fact_pack():    LLM extracts structured JSON facts from RAG context.
  Step 2 — render_document_sections(): LLM renders the 16-section markdown from FactPack.

Between steps, validate_fact_pack() performs pure-Python evidence validation.

Graceful degradation: if extraction fails for any reason, all functions return None
(or the original content) — the caller falls back to the single-pass pipeline.

Security:
  - Extraction prompt includes anti-prompt-injection instruction (via prompt_builder).
  - FactPack JSON is treated as untrusted LLM output and validated before use.
  - FactPack is never persisted to DB — only the final markdown is stored.
"""

import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Literal

from config import settings
from prompt_builder import build_fact_extraction_prompt, build_section_render_prompt
from services.llm_service import generate_with_retry

logger = logging.getLogger(__name__)

# ── Confidence type ───────────────────────────────────────────────────────────
ConfidenceLevel = Literal["confirmed", "inferred", "missing_evidence", "to_validate"]

_VALID_CONFIDENCE_LEVELS: frozenset[str] = frozenset(
    {"confirmed", "inferred", "missing_evidence", "to_validate"}
)

# Numeric weight used when computing per-section confidence score
_CONFIDENCE_WEIGHTS: dict[str, float] = {
    "confirmed":        1.0,
    "inferred":         0.7,
    "to_validate":      0.5,
    "missing_evidence": 0.2,
}


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class EvidenceClaim:
    """A single piece of evidence extracted from the RAG context."""
    claim_id: str
    statement: str
    source_chunks: list[str]       # doc_id values from ScoredChunk
    confidence: ConfidenceLevel
    classification: ConfidenceLevel


@dataclass
class FactPack:
    """Structured intermediate representation of integration facts (ADR-041)."""
    integration_scope: dict
    actors: list[dict]
    systems: list[dict]
    entities: list[dict]
    business_rules: list[dict]
    flows: list[dict]
    validations: list[dict]
    errors: list[dict]
    assumptions: list[dict]
    open_questions: list[dict]
    evidence: list[EvidenceClaim] = field(default_factory=list)
    # Extraction metadata (not sent to the render LLM)
    extraction_model: str = ""
    extraction_chars: int = 0
    validation_issues: list[str] = field(default_factory=list)


# ── JSON extraction helper ────────────────────────────────────────────────────

def _extract_json_from_llm_response(raw: str) -> dict:
    """
    Attempt to extract a JSON object from an LLM response string.

    Tries three strategies in order:
      1. Direct json.loads on the stripped string.
      2. Slice from first '{' to last '}' and parse.
      3. Strip ```json ... ``` fences, then retry strategies 1 and 2.

    Raises ValueError if all strategies fail.
    """
    text = raw.strip()

    # Strategy 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: brace scan
    try:
        start = text.index("{")
        end   = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        pass

    # Strategy 3: strip markdown fences, then retry strategies 1 and 2
    fenced = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    fenced = re.sub(r"\s*```$", "", fenced, flags=re.MULTILINE).strip()

    try:
        return json.loads(fenced)
    except json.JSONDecodeError:
        pass

    try:
        start = fenced.index("{")
        end   = fenced.rindex("}") + 1
        return json.loads(fenced[start:end])
    except (ValueError, json.JSONDecodeError):
        pass

    raise ValueError(f"No valid JSON object found in LLM response (first 200 chars): {raw[:200]!r}")


# ── FactPack construction helper ──────────────────────────────────────────────

def _build_fact_pack_from_dict(data: dict, model_name: str, prompt_chars: int) -> FactPack:
    """Convert a parsed JSON dict into a FactPack dataclass."""
    raw_evidence = data.get("evidence", [])
    evidence: list[EvidenceClaim] = []
    for item in raw_evidence:
        conf = item.get("confidence", "missing_evidence")
        cls_ = item.get("classification", conf)
        if conf not in _VALID_CONFIDENCE_LEVELS:
            conf = "missing_evidence"
        if cls_ not in _VALID_CONFIDENCE_LEVELS:
            cls_ = conf
        evidence.append(EvidenceClaim(
            claim_id=str(item.get("claim_id", "")),
            statement=str(item.get("statement", "")),
            source_chunks=[str(s) for s in item.get("source_chunks", [])],
            confidence=conf,
            classification=cls_,
        ))

    return FactPack(
        integration_scope=data.get("integration_scope", {}),
        actors=data.get("actors", []),
        systems=data.get("systems", []),
        entities=data.get("entities", []),
        business_rules=data.get("business_rules", []),
        flows=data.get("flows", []),
        validations=data.get("validations", []),
        errors=data.get("errors", []),
        assumptions=data.get("assumptions", []),
        open_questions=data.get("open_questions", []),
        evidence=evidence,
        extraction_model=model_name,
        extraction_chars=prompt_chars,
    )


# ── Public API ────────────────────────────────────────────────────────────────

async def extract_fact_pack(
    rag_context: str,
    source: str,
    target: str,
    requirements_text: str,
    log_fn: Callable[[str], None] | None = None,
) -> "FactPack | None":
    """
    Step 1 of the FactPack pipeline — extract structured facts from the RAG context.

    Delegates prompt construction to build_fact_extraction_prompt() (ADR-042).

    Prefers Claude API (claude-sonnet-4-6) when ANTHROPIC_API_KEY is set;
    falls back to Ollama with temperature=0.0 and a single retry on JSON parse failure.

    Returns None on any failure — caller triggers graceful degradation to single-pass.
    """
    _log = log_fn or logger.info
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    prompt = build_fact_extraction_prompt(source, target, requirements_text, rag_context)
    prompt_chars = len(prompt)

    # ── Path A: Claude API ────────────────────────────────────────────────────
    if api_key:
        _log(f"[FactPack] Extracting via Claude API ({source} → {target}, {prompt_chars} chars)...")
        try:
            import anthropic  # lazy import — not required in dev/test environments

            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=settings.fact_pack_max_tokens,
                system=(
                    "You are a structured data extractor. "
                    "You output ONLY valid JSON objects. No prose, no markdown."
                ),
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()
            data = _extract_json_from_llm_response(raw)
            fact_pack = _build_fact_pack_from_dict(data, "claude-sonnet-4-6", prompt_chars)
            _log(
                f"[FactPack] Extraction OK (Claude) — "
                f"{len(fact_pack.evidence)} claims, "
                f"{len(fact_pack.business_rules)} rules, "
                f"{len(fact_pack.flows)} flows"
            )
            return fact_pack

        except Exception as exc:
            _log(f"[FactPack] Claude extraction failed (non-blocking): {type(exc).__name__}: {exc}")
            return None

    # ── Path B: Ollama fallback ───────────────────────────────────────────────
    _log(f"[FactPack] Extracting via Ollama ({source} → {target}, {prompt_chars} chars)...")
    model_name = f"ollama/{settings.ollama_model}"
    raw = ""

    for attempt in range(1, 3):  # max 2 attempts
        try:
            raw = await generate_with_retry(
                prompt,
                num_predict=settings.fact_pack_max_tokens,
                timeout=settings.fact_pack_ollama_timeout_seconds,
                temperature=0.0,   # deterministic JSON — override settings.ollama_temperature
                log_fn=_log,
            )
            data = _extract_json_from_llm_response(raw)
            fact_pack = _build_fact_pack_from_dict(data, model_name, prompt_chars)
            _log(
                f"[FactPack] Extraction OK (Ollama, attempt {attempt}) — "
                f"{len(fact_pack.evidence)} claims"
            )
            return fact_pack
        except ValueError as exc:
            _log(f"[FactPack] Ollama JSON parse failed (attempt {attempt}): {exc}")
            if attempt == 2:
                _log("[FactPack] All Ollama extraction attempts failed — graceful degradation.")
                return None
        except Exception as exc:
            _log(f"[FactPack] Ollama extraction error (non-blocking): {type(exc).__name__}: {exc}")
            return None

    return None  # unreachable, but satisfies type checker


def validate_fact_pack(
    fact_pack: FactPack,
    source: str,
    target: str,
) -> FactPack:
    """
    Pure-Python validation of a FactPack — no LLM calls, no exceptions raised.

    Appends advisory messages to fact_pack.validation_issues.
    Returns the (mutated) fact_pack with validation_issues populated.
    """
    issues: list[str] = []

    # 1. Check integration scope
    scope_source = fact_pack.integration_scope.get("source", "")
    scope_target = fact_pack.integration_scope.get("target", "")
    if scope_source.lower() != source.lower():
        issues.append(
            f"integration_scope.source '{scope_source}' does not match expected '{source}'"
        )
    if scope_target.lower() != target.lower():
        issues.append(
            f"integration_scope.target '{scope_target}' does not match expected '{target}'"
        )

    # 2. Require at least one item in key structural lists
    for field_name in ("flows", "business_rules", "systems"):
        lst = getattr(fact_pack, field_name, [])
        if not lst:
            issues.append(f"'{field_name}' list is empty — no evidence extracted")

    # 3. Claim ID uniqueness
    claim_ids = [e.claim_id for e in fact_pack.evidence]
    duplicates = [cid for cid, cnt in Counter(claim_ids).items() if cnt > 1]
    if duplicates:
        issues.append(f"Duplicate claim_ids in evidence: {duplicates}")

    # 4. Confidence literal validation
    invalid_conf = [
        e.claim_id for e in fact_pack.evidence
        if e.confidence not in _VALID_CONFIDENCE_LEVELS
    ]
    if invalid_conf:
        issues.append(f"Invalid confidence values for claims: {invalid_conf}")

    # 5. Confidence distribution summary (advisory, not an error)
    counts = Counter(e.confidence for e in fact_pack.evidence)
    total  = sum(counts.values())
    if total:
        missing_ratio = counts.get("missing_evidence", 0) / total
        if missing_ratio > 0.5:
            issues.append(
                f"High missing_evidence ratio ({missing_ratio:.0%}) — "
                f"context may be insufficient for quality generation"
            )

    fact_pack.validation_issues = issues
    if issues:
        logger.warning("[FactPack] Validation issues (%d): %s", len(issues), issues)
    else:
        logger.info("[FactPack] Validation passed — no issues.")
    return fact_pack


async def render_document_sections(
    fact_pack: FactPack,
    source: str,
    target: str,
    requirements_text: str,
    document_template: str,
    reviewer_feedback: str = "",
    log_fn: Callable[[str], None] | None = None,
    provider: str = "ollama",
    model: str | None = None,
    num_predict: int | None = None,
    timeout: int | None = None,
    temperature: float | None = None,
) -> str:
    """
    Step 2 of the FactPack pipeline — render the 16-section markdown from a FactPack.

    Delegates prompt construction to build_section_render_prompt() (ADR-042), which
    injects per-section FactPack field guidance to reduce cross-section content blending.

    ADR-042 bugfix: reviewer_feedback is now forwarded to the rendering prompt so HITL
    rejection feedback is not silently dropped in the FactPack path.

    Args:
        fact_pack:           Validated FactPack with extracted integration facts.
        source:              Source system name.
        target:              Target system name.
        requirements_text:   Concatenated requirement descriptions.
        document_template:   Full integration base template markdown.
        reviewer_feedback:   Optional HITL rejection feedback. Previously lost in the
                             FactPack path (ADR-041 bug); fixed in ADR-042.
        log_fn:              Optional logging callback.

    Returns:
        Raw markdown string — caller must pipe through sanitize_llm_output().
    """
    _log = log_fn or logger.info

    # Serialize FactPack to a compact JSON for the prompt
    fact_pack_dict = {
        "integration_scope": fact_pack.integration_scope,
        "actors":            fact_pack.actors,
        "systems":           fact_pack.systems,
        "entities":          fact_pack.entities,
        "business_rules":    fact_pack.business_rules,
        "flows":             fact_pack.flows,
        "validations":       fact_pack.validations,
        "errors":            fact_pack.errors,
        "assumptions":       fact_pack.assumptions,
        "open_questions":    fact_pack.open_questions,
        "evidence": [
            {
                "claim_id":      e.claim_id,
                "statement":     e.statement,
                "source_chunks": e.source_chunks,
                "confidence":    e.confidence,
            }
            for e in fact_pack.evidence
        ],
    }
    fact_pack_json = json.dumps(fact_pack_dict, ensure_ascii=False, indent=2)

    prompt = build_section_render_prompt(
        fact_pack_json=fact_pack_json,
        source=source,
        target=target,
        requirements_text=requirements_text,
        document_template=document_template,
        reviewer_feedback=reviewer_feedback,
    )

    _log(
        f"[FactPack] Rendering document from FactPack ({source} → {target}, "
        f"{len(prompt)} chars prompt"
        + (f", feedback: {len(reviewer_feedback)} chars" if reviewer_feedback.strip() else "")
        + ")..."
    )

    raw = await generate_with_retry(
        prompt,
        provider=provider,
        model=model,
        num_predict=num_predict,
        timeout=timeout,
        temperature=temperature,
        log_fn=_log,
    )
    _log(f"[FactPack] Render complete — {len(raw)} chars generated.")
    return raw
