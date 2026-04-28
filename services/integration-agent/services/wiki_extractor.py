"""
Wiki Extractor — pure functions for entity and relationship extraction.

Operates exclusively on existing v2 chunk metadata (ADR-048); no re-parsing
of original documents.  All functions are synchronous and side-effect-free,
making them easy to unit-test.

Entity types (entity_type field):
  system       — from system_names
  api_entity   — from entity_names where semantic_type in {entity_definition}
  business_term — from business_terms
  state        — nodes of state_transitions ("A -> B")
  rule         — entity_names where semantic_type == business_rule
  field        — field_names (only when ≥3 in chunk)
  process      — entity_names where semantic_type in {integration_flow}
  generic      — everything else

Relationship types (rel_type):
  TRANSITIONS_TO   DEPENDS_ON   CALLS   MAPS_TO   GOVERNS
  TRIGGERS   HANDLES_ERROR   DEFINED_BY   RELATED_TO
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Normalise text to a stable slug usable as an entity_id suffix."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text.strip())
    return text.lower()


def _make_entity_id(name: str) -> str:
    return f"ENT-{_slugify(name)}"


def _split_csv(value: str) -> list[str]:
    """Split a comma- or semicolon-separated string, stripping whitespace."""
    if not value:
        return []
    return [v.strip() for v in re.split(r"[,;]", value) if v.strip()]


_INTEGRATION_FLOW_TYPES = {"integration_flow", "data_flow", "process_description"}
_ENTITY_DEF_TYPES = {"entity_definition", "data_model", "data_schema"}
_SEMANTIC_TYPE_TO_ENTITY_TYPE = {
    "business_rule": "rule",
    **{t: "process" for t in _INTEGRATION_FLOW_TYPES},
    **{t: "api_entity" for t in _ENTITY_DEF_TYPES},
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class EntityCandidate:
    name: str
    entity_type: str
    doc_id: str
    chunk_id: str
    semantic_types: list[str] = field(default_factory=list)
    tags_csv: str = ""
    source_modality: str = ""

    @property
    def entity_id(self) -> str:
        return _make_entity_id(self.name)


@dataclass
class WikiEntity:
    entity_id: str
    name: str
    entity_type: str
    aliases: list[str]
    doc_ids: list[str]
    chunk_ids: list[str]
    semantic_types: list[str]
    tags_csv: str
    source_modalities: list[str]
    chunk_count: int


@dataclass
class RelationshipCandidate:
    from_name: str
    to_name: str
    rel_type: str
    doc_id: str
    chunk_id: str
    weight: float = 0.8
    label: str = ""
    extraction_method: str = "rule_based"

    @property
    def from_entity_id(self) -> str:
        return _make_entity_id(self.from_name)

    @property
    def to_entity_id(self) -> str:
        return _make_entity_id(self.to_name)


# ── Entity extraction ─────────────────────────────────────────────────────────

def extract_entities_from_chunk(
    chunk_id: str,
    chunk_text: str,  # noqa: ARG001 — reserved for future LLM fallback
    metadata: dict,
) -> list[EntityCandidate]:
    """Return EntityCandidate list for one chunk, derived from v2 metadata."""
    doc_id: str = metadata.get("document_id", "")
    semantic_type: str = metadata.get("semantic_type", "")
    tags_csv: str = metadata.get("tags", "")
    source_modality: str = metadata.get("file_type", "")
    candidates: list[EntityCandidate] = []

    # ── system_names ─────────────────────────────────────────────────────────
    for name in _split_csv(metadata.get("system_names", "")):
        candidates.append(EntityCandidate(
            name=name, entity_type="system",
            doc_id=doc_id, chunk_id=chunk_id,
            semantic_types=[semantic_type] if semantic_type else [],
            tags_csv=tags_csv, source_modality=source_modality,
        ))

    # ── business_terms ───────────────────────────────────────────────────────
    for name in _split_csv(metadata.get("business_terms", "")):
        candidates.append(EntityCandidate(
            name=name, entity_type="business_term",
            doc_id=doc_id, chunk_id=chunk_id,
            semantic_types=[semantic_type] if semantic_type else [],
            tags_csv=tags_csv, source_modality=source_modality,
        ))

    # ── state_transitions: "A -> B" ──────────────────────────────────────────
    for transition in _split_csv(metadata.get("state_transitions", "")):
        parts = re.split(r"\s*->\s*", transition)
        for state_name in parts:
            state_name = state_name.strip()
            if state_name:
                candidates.append(EntityCandidate(
                    name=state_name, entity_type="state",
                    doc_id=doc_id, chunk_id=chunk_id,
                    semantic_types=[semantic_type] if semantic_type else [],
                    tags_csv=tags_csv, source_modality=source_modality,
                ))

    # ── entity_names — type deduced from semantic_type ───────────────────────
    entity_type_for_semantic = _SEMANTIC_TYPE_TO_ENTITY_TYPE.get(semantic_type, "generic")
    for name in _split_csv(metadata.get("entity_names", "")):
        candidates.append(EntityCandidate(
            name=name, entity_type=entity_type_for_semantic,
            doc_id=doc_id, chunk_id=chunk_id,
            semantic_types=[semantic_type] if semantic_type else [],
            tags_csv=tags_csv, source_modality=source_modality,
        ))

    # ── field_names — only when ≥3 present (avoids noise) ───────────────────
    field_names = _split_csv(metadata.get("field_names", ""))
    if len(field_names) >= 3:
        for name in field_names:
            candidates.append(EntityCandidate(
                name=name, entity_type="field",
                doc_id=doc_id, chunk_id=chunk_id,
                semantic_types=[semantic_type] if semantic_type else [],
                tags_csv=tags_csv, source_modality=source_modality,
            ))

    return candidates


def merge_entity_candidates(candidates: list[EntityCandidate]) -> list[WikiEntity]:
    """
    Merge EntityCandidates with the same entity_id into a single WikiEntity.

    doc_ids, chunk_ids, semantic_types, and source_modalities are unioned
    (deduplicated, order-preserving).
    """
    merged: dict[str, WikiEntity] = {}

    for c in candidates:
        eid = c.entity_id
        if eid not in merged:
            merged[eid] = WikiEntity(
                entity_id=eid,
                name=c.name,
                entity_type=c.entity_type,
                aliases=[],
                doc_ids=[c.doc_id] if c.doc_id else [],
                chunk_ids=[c.chunk_id],
                semantic_types=list(c.semantic_types),
                tags_csv=c.tags_csv,
                source_modalities=[c.source_modality] if c.source_modality else [],
                chunk_count=1,
            )
        else:
            e = merged[eid]
            if c.doc_id and c.doc_id not in e.doc_ids:
                e.doc_ids.append(c.doc_id)
            if c.chunk_id not in e.chunk_ids:
                e.chunk_ids.append(c.chunk_id)
                e.chunk_count += 1
            for st in c.semantic_types:
                if st and st not in e.semantic_types:
                    e.semantic_types.append(st)
            if c.source_modality and c.source_modality not in e.source_modalities:
                e.source_modalities.append(c.source_modality)
            # prefer longer tags_csv
            if len(c.tags_csv) > len(e.tags_csv):
                e.tags_csv = c.tags_csv

    return list(merged.values())


# ── Relationship extraction ───────────────────────────────────────────────────

def extract_relationships_rule_based(
    chunk_id: str,
    metadata: dict,
) -> list[RelationshipCandidate]:
    """Return typed RelationshipCandidates derived from v2 chunk metadata."""
    doc_id: str = metadata.get("document_id", "")
    semantic_type: str = metadata.get("semantic_type", "")
    candidates: list[RelationshipCandidate] = []

    # TRANSITIONS_TO — from state_transitions field
    transitions = _split_csv(metadata.get("state_transitions", ""))
    for t in transitions:
        parts = re.split(r"\s*->\s*", t)
        for i in range(len(parts) - 1):
            frm = parts[i].strip()
            to = parts[i + 1].strip()
            if frm and to and frm != to:
                candidates.append(RelationshipCandidate(
                    from_name=frm, to_name=to,
                    rel_type="TRANSITIONS_TO",
                    doc_id=doc_id, chunk_id=chunk_id,
                    label="transitions to",
                ))

    entity_names = _split_csv(metadata.get("entity_names", ""))
    system_names = _split_csv(metadata.get("system_names", ""))

    # CALLS — api_contract with ≥2 systems
    if semantic_type == "api_contract" and len(system_names) >= 2:
        for i in range(len(system_names) - 1):
            candidates.append(RelationshipCandidate(
                from_name=system_names[i], to_name=system_names[i + 1],
                rel_type="CALLS",
                doc_id=doc_id, chunk_id=chunk_id,
                label="calls",
            ))

    # GOVERNS — business_rule + entity
    if semantic_type == "business_rule" and entity_names:
        for entity in entity_names:
            candidates.append(RelationshipCandidate(
                from_name=entity, to_name=entity,  # self-governs; builder will skip self-loops
                rel_type="GOVERNS",
                doc_id=doc_id, chunk_id=chunk_id,
                label="governs",
            ))
        # Better: rule governs first entity
        if len(entity_names) >= 2:
            candidates.append(RelationshipCandidate(
                from_name=entity_names[0], to_name=entity_names[1],
                rel_type="GOVERNS",
                doc_id=doc_id, chunk_id=chunk_id,
                label="governs",
            ))

    # TRIGGERS — event_definition + entity
    if semantic_type == "event_definition" and entity_names:
        for entity in entity_names:
            if entity_names.index(entity) > 0:
                candidates.append(RelationshipCandidate(
                    from_name=entity_names[0], to_name=entity,
                    rel_type="TRIGGERS",
                    doc_id=doc_id, chunk_id=chunk_id,
                    label="triggers",
                ))

    # HANDLES_ERROR — error_handling + entity
    if semantic_type == "error_handling" and entity_names:
        for entity in entity_names:
            candidates.append(RelationshipCandidate(
                from_name=entity, to_name=entity_names[0] if entity != entity_names[0] else (entity_names[1] if len(entity_names) > 1 else entity),
                rel_type="HANDLES_ERROR",
                doc_id=doc_id, chunk_id=chunk_id,
                label="handles error",
            ))

    # MAPS_TO — data_mapping_candidate + ≥2 entities
    if semantic_type == "data_mapping_candidate" and len(entity_names) >= 2:
        for i in range(len(entity_names) - 1):
            candidates.append(RelationshipCandidate(
                from_name=entity_names[i], to_name=entity_names[i + 1],
                rel_type="MAPS_TO",
                doc_id=doc_id, chunk_id=chunk_id,
                label="maps to",
            ))

    # DEFINED_BY — field_definition + entity + system
    field_names = _split_csv(metadata.get("field_names", ""))
    if semantic_type == "field_definition" and entity_names and system_names:
        for fn in field_names[:3]:  # cap to avoid combinatorial explosion
            candidates.append(RelationshipCandidate(
                from_name=system_names[0], to_name=fn,
                rel_type="DEFINED_BY",
                doc_id=doc_id, chunk_id=chunk_id,
                label="defines",
            ))

    # RELATED_TO — co-occurrence of ≥2 entities in same chunk
    all_names = entity_names + system_names
    if len(all_names) >= 2:
        seen_pairs: set[tuple[str, str]] = set()
        for i in range(len(all_names)):
            for j in range(i + 1, len(all_names)):
                a, b = all_names[i], all_names[j]
                if a != b:
                    pair = (min(a, b), max(a, b))
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        # Only add if not already covered by a typed edge
                        already_typed = any(
                            (c.from_name == a and c.to_name == b) or
                            (c.from_name == b and c.to_name == a)
                            for c in candidates
                            if c.rel_type != "RELATED_TO"
                        )
                        if not already_typed:
                            candidates.append(RelationshipCandidate(
                                from_name=a, to_name=b,
                                rel_type="RELATED_TO",
                                doc_id=doc_id, chunk_id=chunk_id,
                                label="related to",
                                weight=0.4,
                            ))

    # Filter self-loops
    return [c for c in candidates if c.from_name != c.to_name]


async def enrich_relationships_with_llm(
    candidates: list[RelationshipCandidate],
    chunk_text: str,
    ollama_host: str,
    model: str = "qwen3:8b",
    timeout: int = 60,
) -> list[RelationshipCandidate]:
    """
    Optionally upgrade RELATED_TO edges to more specific types using LLM.

    Only processes RELATED_TO candidates; non-RELATED_TO pass through unchanged.
    On any error the original RELATED_TO candidate is kept (graceful degrade).
    """
    import json
    import httpx

    typed = [c for c in candidates if c.rel_type != "RELATED_TO"]
    ambiguous = [c for c in candidates if c.rel_type == "RELATED_TO"]

    if not ambiguous:
        return candidates

    results = list(typed)

    for c in ambiguous:
        prompt = (
            f"Given this text excerpt:\n\n{chunk_text[:800]}\n\n"
            f'Entities: "{c.from_name}" and "{c.to_name}"\n'
            "What is the most specific relationship type between them?\n"
            "Choose exactly one from: TRANSITIONS_TO, DEPENDS_ON, CALLS, MAPS_TO, "
            "GOVERNS, TRIGGERS, HANDLES_ERROR, DEFINED_BY, RELATED_TO\n"
            'Respond with JSON only: {"rel_type": "...", "label": "...", "confidence": 0.0-1.0}'
        )
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{ollama_host}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False},
                )
                raw = resp.json().get("response", "{}")
                # extract JSON from response
                m = re.search(r"\{[^}]+\}", raw)
                if m:
                    data = json.loads(m.group())
                    rel_type = data.get("rel_type", "RELATED_TO").upper()
                    valid = {
                        "TRANSITIONS_TO", "DEPENDS_ON", "CALLS", "MAPS_TO",
                        "GOVERNS", "TRIGGERS", "HANDLES_ERROR", "DEFINED_BY", "RELATED_TO",
                    }
                    if rel_type in valid and data.get("confidence", 0) >= 0.7:
                        c.rel_type = rel_type
                        c.label = data.get("label", c.label)
                        c.extraction_method = "llm_assisted"
        except Exception:
            pass  # keep original RELATED_TO on any error

        results.append(c)

    return results
