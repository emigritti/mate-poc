"""Semantic classifier for KB chunk metadata v2 — ADR-048.

Deterministic, rule-based extraction only (no LLM, no I/O).
All extraction functions accept raw text and return plain Python types.
The main entry point is classify_chunk(), which returns a ChunkMetadataV2.
"""
from __future__ import annotations

import re
from typing import Optional

from services.metadata_schema import ChunkMetadataV2, ChunkType, SemanticType

# ── Vocabulary sets (reused from document_parser ADR-044) ────────────────────

_RULE_MARKERS: frozenset[str] = frozenset({
    "mandatory", "must", "required", "shall", "should", "only if",
    "forbidden", "not allowed", "validation", "constraint", "policy",
    "compliance", "eligible", "condition", "prohibited",
})

_INTEGRATION_KEYWORDS: frozenset[str] = frozenset({
    "api", "rest", "soap", "webhook", "oauth", "jwt", "mtls",
    "endpoint", "payload", "request", "response", "idempotent",
    "retry", "queue", "event", "message", "batch", "streaming",
    "connector", "adapter", "middleware", "protocol",
    "grpc", "graphql", "async", "http", "https",
})

_ARCHITECTURE_KEYWORDS: frozenset[str] = frozenset({
    "architecture", "pattern", "flow", "sequence", "diagram",
    "component", "service", "integration", "synchronous",
    "asynchronous", "pipeline", "orchestration", "interface",
})

_ERROR_KEYWORDS: frozenset[str] = frozenset({
    "error", "exception", "fallback", "retry", "timeout",
    "dead-letter", "circuit", "recovery", "compensation",
    "rollback", "failure",
})

_SECURITY_KEYWORDS: frozenset[str] = frozenset({
    "authentication", "authorization", "token", "secret",
    "encrypt", "certificate", "tls", "ssl", "credential",
    "permission", "role", "security",
})

# ── New vocabulary sets (ADR-048 extension) ──────────────────────────────────

_MAPPING_MARKERS: frozenset[str] = frozenset({
    "mapping", "maps to", "transform", "convert", "source", "target",
    "translation", "crosswalk", "lookup", "correspondence",
})

_STATE_MARKERS: frozenset[str] = frozenset({
    "status", "state", "transition", "pending", "active", "inactive",
    "created", "confirmed", "shipped", "closed", "cancelled", "approved",
    "rejected", "completed", "processing",
})

_VALIDATION_MARKERS: frozenset[str] = frozenset({
    "validate", "validation", "check", "verify", "assert",
    "format", "regex", "pattern", "length", "range", "required field",
    "invalid", "missing", "not null", "not empty",
})

_EVENT_MARKERS: frozenset[str] = frozenset({
    "event", "trigger", "publish", "subscribe", "notify",
    "emit", "listen", "handler", "callback", "webhook",
    "on change", "on create", "on update", "on delete",
})

_UI_MARKERS: frozenset[str] = frozenset({
    "button", "form", "screen", "page", "modal", "dialog",
    "input", "field", "click", "submit", "navigate", "ui",
    "user interface", "menu", "dropdown", "checkbox",
})

# Integration domain glossary for business term extraction
_BUSINESS_TERMS: frozenset[str] = frozenset({
    "order", "invoice", "product", "catalog", "customer", "supplier",
    "shipment", "delivery", "payment", "refund", "stock", "inventory",
    "warehouse", "sku", "master data", "reference data", "workflow",
    "approval", "notification", "report", "dashboard", "kpi",
    "erp", "crm", "dam", "pim", "plm", "mdm", "wms",
})

# ── Regex patterns ────────────────────────────────────────────────────────────

# snake_case field names (e.g. product_id, order_status)
_FIELD_PATTERN: re.Pattern = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")
# PascalCase entity names (e.g. ProductMaster, OrderId)
_ENTITY_PATTERN: re.Pattern = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-zA-Z0-9]+)+)\b")
# State transitions: "X → Y", "X -> Y", "X to Y" where X/Y are capitalised words
_STATE_TRANSITION_PATTERN: re.Pattern = re.compile(
    r"\b([A-Z][a-zA-Z]+)\s*(?:->|→|to)\s*([A-Z][a-zA-Z]+)\b"
)
# Capitalised words near "system" / "service" / "platform" in the same sentence
_SYSTEM_CONTEXT_PATTERN: re.Pattern = re.compile(
    r"\b([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)\s+(?:system|service|platform|module|component)\b",
    re.IGNORECASE,
)


# ── Extraction helpers ────────────────────────────────────────────────────────

def extract_entity_names(text: str) -> list[str]:
    return sorted(set(_ENTITY_PATTERN.findall(text)))[:10]


def extract_field_names(text: str) -> list[str]:
    return sorted(set(_FIELD_PATTERN.findall(text)))[:15]


def extract_rule_markers(text: str) -> list[str]:
    tl = text.lower()
    return sorted({m for m in _RULE_MARKERS if m in tl})


def extract_integration_keywords(text: str) -> list[str]:
    tl = text.lower()
    return sorted({k for k in _INTEGRATION_KEYWORDS if k in tl})


def extract_error_markers(text: str) -> list[str]:
    tl = text.lower()
    return sorted({m for m in _ERROR_KEYWORDS if m in tl})


def extract_system_names(text: str) -> list[str]:
    matches = _SYSTEM_CONTEXT_PATTERN.findall(text)
    return sorted({m.strip() for m in matches if len(m.strip()) > 2})[:10]


def extract_business_terms(text: str) -> list[str]:
    tl = text.lower()
    return sorted({t for t in _BUSINESS_TERMS if t in tl})


def extract_state_transitions(text: str) -> list[str]:
    matches = _STATE_TRANSITION_PATTERN.findall(text)
    return [f"{a} -> {b}" for a, b in matches][:10]


def contains_flags(text: str, chunk_type: str) -> dict:
    tl = text.lower()
    return {
        "contains_table":   chunk_type == ChunkType.TABLE,
        "contains_figure":  chunk_type == ChunkType.FIGURE,
        "contains_code":    chunk_type == ChunkType.CODE or "```" in text or "<code>" in tl,
        "contains_rules":   any(m in tl for m in _RULE_MARKERS),
        "contains_mapping": any(m in tl for m in _MAPPING_MARKERS),
    }


# ── Semantic type classifier ──────────────────────────────────────────────────

def classify_semantic_type(  # noqa: C901  (complexity acceptable: priority table)
    text: str,
    chunk_type: str,
    rule_markers: list[str],
    error_markers: list[str],
    field_names: list[str],
    entity_names: list[str],
) -> str:
    """Classify a chunk into one of the 15 SemanticType values.

    Uses a priority-ordered scoring approach — first threshold that fires wins.
    Deterministic, no LLM required.
    """
    tl = text.lower()

    # Hard overrides for structural chunk types
    if chunk_type == ChunkType.FIGURE:
        return SemanticType.DIAGRAM_OR_VISUAL
    if chunk_type == ChunkType.TABLE:
        return SemanticType.DATA_MAPPING_CANDIDATE

    # Score each category
    rule_score     = len(rule_markers)
    error_score    = len(error_markers)
    security_score = sum(1 for k in _SECURITY_KEYWORDS   if k in tl)
    arch_score     = sum(1 for k in _ARCHITECTURE_KEYWORDS if k in tl)
    integ_score    = sum(1 for k in _INTEGRATION_KEYWORDS  if k in tl)
    mapping_score  = sum(1 for m in _MAPPING_MARKERS        if m in tl)
    state_score    = sum(1 for m in _STATE_MARKERS           if m in tl)
    valid_score    = sum(1 for m in _VALIDATION_MARKERS      if m in tl)
    event_score    = sum(1 for m in _EVENT_MARKERS           if m in tl)
    ui_score       = sum(1 for m in _UI_MARKERS              if m in tl)
    field_score    = len(field_names)
    entity_score   = len(entity_names)

    # Priority-ordered classification
    if valid_score >= 3:
        return SemanticType.VALIDATION_RULE
    if rule_score >= 2:
        return SemanticType.BUSINESS_RULE
    if error_score >= 2:
        return SemanticType.ERROR_HANDLING
    if security_score >= 2:
        return SemanticType.SECURITY_REQUIREMENT
    if mapping_score >= 2:
        return SemanticType.DATA_MAPPING_CANDIDATE
    if state_score >= 3:
        return SemanticType.STATE_MODEL
    if event_score >= 2:
        return SemanticType.EVENT_DEFINITION
    if ui_score >= 3:
        return SemanticType.UI_INTERACTION
    if integ_score >= 3:
        return SemanticType.API_CONTRACT
    if arch_score >= 2:
        return SemanticType.INTEGRATION_FLOW
    if field_score >= 3:
        return SemanticType.FIELD_DEFINITION
    if entity_score >= 3:
        return SemanticType.ENTITY_DEFINITION

    # Overview heuristic: non-empty text with no technical signals → likely a descriptor
    if chunk_type == ChunkType.TEXT and len(text) > 100 and field_score == 0 and entity_score <= 1:
        return SemanticType.SYSTEM_OVERVIEW

    return SemanticType.GENERIC_CONTEXT


# ── Main entry point ──────────────────────────────────────────────────────────

def classify_chunk(
    text: str,
    chunk_type: str,
    chunk_id: str,
    document_id: str,
    source_modality: str = "unknown",
    chunk_index: int = 0,
    section_header: str = "",
    page_num: int = 0,
    filename: str = "",
    tags: Optional[list[str]] = None,
    existing_meta: Optional[dict] = None,
) -> ChunkMetadataV2:
    """Classify a raw text chunk and return a populated ChunkMetadataV2.

    All extraction is deterministic (rule-based).  The caller is responsible
    for persisting the result via flatten_to_chroma().
    """
    # Normalise chunk_type against known values; fall back to text
    normalised_ct = chunk_type if chunk_type in ChunkType.ALL else ChunkType.TEXT

    entity_names       = extract_entity_names(text)
    field_names        = extract_field_names(text)
    rule_markers       = extract_rule_markers(text)
    error_markers      = extract_error_markers(text)
    integration_kws    = extract_integration_keywords(text)
    system_names       = extract_system_names(text)
    business_terms     = extract_business_terms(text)
    state_transitions  = extract_state_transitions(text)
    flags              = contains_flags(text, normalised_ct)
    semantic_type      = classify_semantic_type(
        text, normalised_ct, rule_markers, error_markers, field_names, entity_names
    )

    # Confidence heuristic: higher when we have strong signals
    strong_signals = sum([
        len(rule_markers) >= 2,
        len(field_names) >= 3,
        len(entity_names) >= 2,
        len(system_names) >= 1,
        semantic_type not in (SemanticType.GENERIC_CONTEXT, SemanticType.SYSTEM_OVERVIEW),
    ])
    confidence = min(0.5 + strong_signals * 0.1, 0.95)

    return ChunkMetadataV2(
        chunk_id=chunk_id,
        document_id=document_id,
        kb_schema_version="v2",
        source_modality=source_modality,
        filename=filename,
        chunk_index=chunk_index,
        chunk_type=normalised_ct,
        semantic_type=semantic_type,
        section_header=section_header,
        page_num=page_num,
        entity_names=entity_names,
        field_names=field_names,
        system_names=system_names,
        business_terms=business_terms,
        rule_markers=rule_markers,
        integration_keywords=integration_kws,
        state_transitions=state_transitions,
        error_markers=error_markers,
        tags=tags or [],
        contains_table=flags["contains_table"],
        contains_figure=flags["contains_figure"],
        contains_code=flags["contains_code"],
        contains_rules=flags["contains_rules"],
        contains_mapping=flags["contains_mapping"],
        confidence_semantic_enrichment=confidence,
        enrichment_method="rule_only",
        is_active=True,
    )
