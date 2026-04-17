"""KB Metadata v2 schema — ADR-048.

Defines ChunkType / SemanticType enumerations, the ChunkMetadataV2 dataclass,
and a helper that serialises it to a flat ChromaDB-compatible dict.

All ChromaDB metadata values must be plain scalars (str / int / float / bool).
List fields are stored as comma-separated strings for backward compatibility
with the existing tags_csv convention; the originals are available as Python
lists on the dataclass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class ChunkType:
    TEXT             = "text"
    TABLE            = "table"
    FIGURE           = "figure"
    CODE             = "code"
    RULE             = "rule"
    MAPPING          = "mapping"
    UI_FLOW          = "ui_flow"
    VALIDATION       = "validation"
    STATE_TRANSITION = "state_transition"
    ENDPOINT         = "endpoint"
    SCHEMA           = "schema"
    SUMMARY          = "summary"

    ALL = {
        TEXT, TABLE, FIGURE, CODE, RULE, MAPPING, UI_FLOW,
        VALIDATION, STATE_TRANSITION, ENDPOINT, SCHEMA, SUMMARY,
    }


class SemanticType:
    GENERIC_CONTEXT       = "generic_context"
    BUSINESS_RULE         = "business_rule"
    DATA_MAPPING_CANDIDATE = "data_mapping_candidate"
    INTEGRATION_FLOW      = "integration_flow"
    SYSTEM_OVERVIEW       = "system_overview"
    ERROR_HANDLING        = "error_handling"
    VALIDATION_RULE       = "validation_rule"
    ENTITY_DEFINITION     = "entity_definition"
    FIELD_DEFINITION      = "field_definition"
    API_CONTRACT          = "api_contract"
    EVENT_DEFINITION      = "event_definition"
    UI_INTERACTION        = "ui_interaction"
    STATE_MODEL           = "state_model"
    SECURITY_REQUIREMENT  = "security_requirement"
    DIAGRAM_OR_VISUAL     = "diagram_or_visual"

    ALL = {
        GENERIC_CONTEXT, BUSINESS_RULE, DATA_MAPPING_CANDIDATE,
        INTEGRATION_FLOW, SYSTEM_OVERVIEW, ERROR_HANDLING,
        VALIDATION_RULE, ENTITY_DEFINITION, FIELD_DEFINITION,
        API_CONTRACT, EVENT_DEFINITION, UI_INTERACTION,
        STATE_MODEL, SECURITY_REQUIREMENT, DIAGRAM_OR_VISUAL,
    }


@dataclass
class ChunkMetadataV2:
    # Identity
    chunk_id: str
    document_id: str
    kb_schema_version: str = "v2"

    # Provenance
    source_modality: str = "unknown"
    filename: str = ""

    # Structure
    chunk_index: int = 0
    chunk_type: str = ChunkType.TEXT
    semantic_type: str = SemanticType.GENERIC_CONTEXT
    section_header: str = ""
    page_num: int = 0

    # Semantic entities (stored as lists; serialised to CSV for ChromaDB)
    entity_names: list[str] = field(default_factory=list)
    field_names: list[str] = field(default_factory=list)
    system_names: list[str] = field(default_factory=list)
    business_terms: list[str] = field(default_factory=list)
    rule_markers: list[str] = field(default_factory=list)
    integration_keywords: list[str] = field(default_factory=list)
    state_transitions: list[str] = field(default_factory=list)
    error_markers: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    # Boolean content flags
    contains_table: bool = False
    contains_figure: bool = False
    contains_code: bool = False
    contains_rules: bool = False
    contains_mapping: bool = False

    # Quality
    confidence_semantic_enrichment: float = 0.5
    enrichment_method: str = "rule_only"

    # Migration / lifecycle
    is_active: bool = True


def flatten_to_chroma(meta: ChunkMetadataV2, extra: Optional[dict] = None) -> dict:
    """Serialise a ChunkMetadataV2 to a flat ChromaDB-compatible dict.

    List fields become comma-separated strings.  An optional *extra* dict is
    merged last (useful for callers that need to pass through legacy fields
    like tags_csv that already exist in a different format).
    """
    flat: dict = {
        "document_id":                    meta.document_id,
        "kb_schema_version":              meta.kb_schema_version,
        "source_modality":                meta.source_modality,
        "filename":                       meta.filename,
        "chunk_index":                    meta.chunk_index,
        "chunk_type":                     meta.chunk_type,
        "semantic_type":                  meta.semantic_type,
        "section_header":                 meta.section_header,
        "page_num":                       meta.page_num,
        "entity_names":                   ",".join(meta.entity_names),
        "field_names":                    ",".join(meta.field_names),
        "system_names":                   ",".join(meta.system_names),
        "business_terms":                 ",".join(meta.business_terms),
        "rule_markers":                   ",".join(meta.rule_markers),
        "integration_keywords":           ",".join(meta.integration_keywords),
        "state_transitions":              ",".join(meta.state_transitions),
        "error_markers":                  ",".join(meta.error_markers),
        "tags_csv":                       ",".join(meta.tags),
        "contains_table":                 meta.contains_table,
        "contains_figure":                meta.contains_figure,
        "contains_code":                  meta.contains_code,
        "contains_rules":                 meta.contains_rules,
        "contains_mapping":               meta.contains_mapping,
        "confidence_semantic_enrichment": meta.confidence_semantic_enrichment,
        "enrichment_method":              meta.enrichment_method,
        "is_active":                      meta.is_active,
    }
    if extra:
        flat.update(extra)
    return flat
