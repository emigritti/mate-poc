"""
Unit tests — wiki_extractor pure extraction functions (ADR-052).

Coverage:
  - extract_entities_from_chunk: state transitions → state entities
  - extract_entities_from_chunk: system_names → system entities
  - extract_entities_from_chunk: business_terms → business_term entities
  - extract_entities_from_chunk: field_names threshold (< 3 → skipped, ≥ 3 → extracted)
  - extract_entities_from_chunk: entity_names + semantic_type mapping
  - merge_entity_candidates: deduplication of same entity from multiple chunks
  - merge_entity_candidates: no duplicate doc_ids / chunk_ids after merge
  - extract_relationships_rule_based: TRANSITIONS_TO from state_transitions
  - extract_relationships_rule_based: CALLS from api_contract + ≥2 systems
  - extract_relationships_rule_based: RELATED_TO co-occurrence
  - extract_relationships_rule_based: self-loops filtered
  - extract_relationships_rule_based: MAPS_TO from data_mapping_candidate
  - extract_relationships_rule_based: GOVERNS from business_rule
"""

import pytest
from services.wiki_extractor import (
    EntityCandidate,
    extract_entities_from_chunk,
    extract_relationships_rule_based,
    merge_entity_candidates,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _meta(**kwargs) -> dict:
    """Build a minimal v2 metadata dict with defaults."""
    return {
        "document_id": kwargs.get("document_id", "KB-TEST0001"),
        "semantic_type": kwargs.get("semantic_type", ""),
        "tags": kwargs.get("tags", ""),
        "file_type": kwargs.get("file_type", "pdf"),
        **{k: v for k, v in kwargs.items() if k not in ("document_id", "semantic_type", "tags", "file_type")},
    }


# ── Entity extraction ─────────────────────────────────────────────────────────

class TestExtractEntitiesFromChunk:
    def test_state_transitions_produces_state_entities(self):
        meta = _meta(state_transitions="Pending -> Confirmed -> Shipped")
        candidates = extract_entities_from_chunk("chunk-1", "...", meta)
        state_names = {c.name for c in candidates if c.entity_type == "state"}
        assert state_names == {"Pending", "Confirmed", "Shipped"}

    def test_system_names_produces_system_entities(self):
        meta = _meta(system_names="SAP ERP, Salesforce")
        candidates = extract_entities_from_chunk("chunk-1", "...", meta)
        system_names = {c.name for c in candidates if c.entity_type == "system"}
        assert system_names == {"SAP ERP", "Salesforce"}

    def test_business_terms_produces_business_term_entities(self):
        meta = _meta(business_terms="Order, Invoice")
        candidates = extract_entities_from_chunk("chunk-1", "...", meta)
        bt_names = {c.name for c in candidates if c.entity_type == "business_term"}
        assert bt_names == {"Order", "Invoice"}

    def test_field_names_below_threshold_skipped(self):
        meta = _meta(field_names="name, age")  # only 2 — below threshold
        candidates = extract_entities_from_chunk("chunk-1", "...", meta)
        field_names = {c.name for c in candidates if c.entity_type == "field"}
        assert len(field_names) == 0

    def test_field_names_at_threshold_extracted(self):
        meta = _meta(field_names="name, age, email")  # exactly 3
        candidates = extract_entities_from_chunk("chunk-1", "...", meta)
        field_names = {c.name for c in candidates if c.entity_type == "field"}
        assert field_names == {"name", "age", "email"}

    def test_entity_names_business_rule_semantic_type(self):
        meta = _meta(entity_names="DiscountRule", semantic_type="business_rule")
        candidates = extract_entities_from_chunk("chunk-1", "...", meta)
        rules = {c.name for c in candidates if c.entity_type == "rule"}
        assert "DiscountRule" in rules

    def test_entity_names_integration_flow_semantic_type(self):
        meta = _meta(entity_names="OrderProcess", semantic_type="integration_flow")
        candidates = extract_entities_from_chunk("chunk-1", "...", meta)
        processes = {c.name for c in candidates if c.entity_type == "process"}
        assert "OrderProcess" in processes

    def test_entity_names_entity_definition_semantic_type(self):
        meta = _meta(entity_names="CustomerEntity", semantic_type="entity_definition")
        candidates = extract_entities_from_chunk("chunk-1", "...", meta)
        apis = {c.name for c in candidates if c.entity_type == "api_entity"}
        assert "CustomerEntity" in apis

    def test_empty_metadata_returns_empty_list(self):
        candidates = extract_entities_from_chunk("chunk-1", "...", {})
        assert candidates == []

    def test_doc_id_and_chunk_id_set_correctly(self):
        meta = _meta(document_id="KB-ABCD1234", system_names="MySystem")
        candidates = extract_entities_from_chunk("KB-ABCD1234-chunk-0", "...", meta)
        assert candidates[0].doc_id == "KB-ABCD1234"
        assert candidates[0].chunk_id == "KB-ABCD1234-chunk-0"


# ── Merge candidates ──────────────────────────────────────────────────────────

class TestMergeEntityCandidates:
    def test_deduplicates_same_entity_across_chunks(self):
        c1 = EntityCandidate(
            name="OrderStatus", entity_type="state",
            doc_id="KB-A", chunk_id="KB-A-chunk-0",
        )
        c2 = EntityCandidate(
            name="OrderStatus", entity_type="state",
            doc_id="KB-A", chunk_id="KB-A-chunk-1",
        )
        entities = merge_entity_candidates([c1, c2])
        assert len(entities) == 1
        assert entities[0].chunk_count == 2
        assert len(entities[0].chunk_ids) == 2

    def test_no_duplicate_doc_ids(self):
        c1 = EntityCandidate(
            name="SAP", entity_type="system",
            doc_id="KB-A", chunk_id="KB-A-chunk-0",
        )
        c2 = EntityCandidate(
            name="SAP", entity_type="system",
            doc_id="KB-A", chunk_id="KB-A-chunk-1",
        )
        entities = merge_entity_candidates([c1, c2])
        assert entities[0].doc_ids.count("KB-A") == 1

    def test_merges_doc_ids_from_different_documents(self):
        c1 = EntityCandidate(
            name="SAP", entity_type="system",
            doc_id="KB-A", chunk_id="KB-A-chunk-0",
        )
        c2 = EntityCandidate(
            name="SAP", entity_type="system",
            doc_id="KB-B", chunk_id="KB-B-chunk-0",
        )
        entities = merge_entity_candidates([c1, c2])
        assert set(entities[0].doc_ids) == {"KB-A", "KB-B"}

    def test_entity_id_is_stable_slug(self):
        c = EntityCandidate(
            name="OrderStatus", entity_type="state",
            doc_id="KB-A", chunk_id="chunk-0",
        )
        entities = merge_entity_candidates([c])
        assert entities[0].entity_id == "ENT-orderstatus"

    def test_empty_input_returns_empty(self):
        assert merge_entity_candidates([]) == []


# ── Relationship extraction ───────────────────────────────────────────────────

class TestExtractRelationshipsRuleBased:
    def test_transitions_to_from_state_transitions(self):
        meta = _meta(state_transitions="Pending -> Confirmed")
        rels = extract_relationships_rule_based("chunk-1", meta)
        trans = [r for r in rels if r.rel_type == "TRANSITIONS_TO"]
        assert len(trans) == 1
        assert trans[0].from_name == "Pending"
        assert trans[0].to_name == "Confirmed"

    def test_transitions_to_multi_hop(self):
        meta = _meta(state_transitions="A -> B -> C")
        rels = extract_relationships_rule_based("chunk-1", meta)
        trans = [r for r in rels if r.rel_type == "TRANSITIONS_TO"]
        pairs = {(r.from_name, r.to_name) for r in trans}
        assert ("A", "B") in pairs
        assert ("B", "C") in pairs

    def test_calls_from_api_contract_two_systems(self):
        meta = _meta(
            system_names="SAP, Salesforce",
            semantic_type="api_contract",
        )
        rels = extract_relationships_rule_based("chunk-1", meta)
        calls = [r for r in rels if r.rel_type == "CALLS"]
        assert len(calls) >= 1
        assert calls[0].from_name == "SAP"
        assert calls[0].to_name == "Salesforce"

    def test_calls_not_emitted_with_single_system(self):
        meta = _meta(system_names="SAP", semantic_type="api_contract")
        rels = extract_relationships_rule_based("chunk-1", meta)
        calls = [r for r in rels if r.rel_type == "CALLS"]
        assert len(calls) == 0

    def test_related_to_co_occurrence(self):
        meta = _meta(entity_names="OrderService, InventoryService")
        rels = extract_relationships_rule_based("chunk-1", meta)
        related = [r for r in rels if r.rel_type == "RELATED_TO"]
        assert len(related) >= 1

    def test_self_loops_filtered(self):
        meta = _meta(entity_names="OnlyOne")
        rels = extract_relationships_rule_based("chunk-1", meta)
        self_loops = [r for r in rels if r.from_name == r.to_name]
        assert self_loops == []

    def test_maps_to_from_data_mapping_candidate(self):
        meta = _meta(
            entity_names="SourceEntity, TargetEntity",
            semantic_type="data_mapping_candidate",
        )
        rels = extract_relationships_rule_based("chunk-1", meta)
        maps = [r for r in rels if r.rel_type == "MAPS_TO"]
        assert len(maps) >= 1
        assert maps[0].from_name == "SourceEntity"
        assert maps[0].to_name == "TargetEntity"

    def test_governs_from_business_rule(self):
        meta = _meta(
            entity_names="DiscountPolicy, Customer",
            semantic_type="business_rule",
        )
        rels = extract_relationships_rule_based("chunk-1", meta)
        governs = [r for r in rels if r.rel_type == "GOVERNS"]
        assert len(governs) >= 1

    def test_empty_metadata_returns_empty(self):
        rels = extract_relationships_rule_based("chunk-1", {})
        assert rels == []

    def test_relationship_has_doc_id_and_chunk_id(self):
        meta = _meta(document_id="KB-X", state_transitions="A -> B")
        rels = extract_relationships_rule_based("chunk-X", meta)
        assert rels[0].doc_id == "KB-X"
        assert rels[0].chunk_id == "chunk-X"
