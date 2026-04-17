"""Unit tests for services/semantic_classifier.py — ADR-048."""
import pytest

from services.metadata_schema import ChunkType, SemanticType
from services.semantic_classifier import (
    classify_chunk,
    classify_semantic_type,
    contains_flags,
    extract_business_terms,
    extract_entity_names,
    extract_error_markers,
    extract_field_names,
    extract_rule_markers,
    extract_state_transitions,
    extract_system_names,
)


# ── extract_entity_names ──────────────────────────────────────────────────────

class TestExtractEntityNames:
    def test_finds_pascal_case(self):
        names = extract_entity_names("The OrderItem and ProductMaster must be synced.")
        assert "OrderItem" in names
        assert "ProductMaster" in names

    def test_no_single_word_capitals(self):
        names = extract_entity_names("The Order must be confirmed.")
        assert "Order" not in names

    def test_max_ten_results(self):
        text = " ".join(f"EntityName{i}" for i in range(20))
        assert len(extract_entity_names(text)) <= 10


# ── extract_field_names ───────────────────────────────────────────────────────

class TestExtractFieldNames:
    def test_finds_snake_case(self):
        fields = extract_field_names("Use order_id and product_sku for the mapping.")
        assert "order_id" in fields
        assert "product_sku" in fields

    def test_max_fifteen_results(self):
        text = " ".join(f"field_{i}_value" for i in range(20))
        assert len(extract_field_names(text)) <= 15


# ── extract_rule_markers ──────────────────────────────────────────────────────

class TestExtractRuleMarkers:
    def test_detects_mandatory(self):
        markers = extract_rule_markers("This field is mandatory and required.")
        assert "mandatory" in markers
        assert "required" in markers

    def test_no_false_positives(self):
        markers = extract_rule_markers("The product was shipped yesterday.")
        assert markers == []


# ── extract_error_markers ─────────────────────────────────────────────────────

class TestExtractErrorMarkers:
    def test_detects_error_keywords(self):
        markers = extract_error_markers("On error, a fallback retry is attempted.")
        assert "error" in markers
        assert "fallback" in markers
        assert "retry" in markers


# ── extract_system_names ──────────────────────────────────────────────────────

class TestExtractSystemNames:
    def test_finds_system_context(self):
        names = extract_system_names("The Commerce system sends events to the ERP service.")
        assert any("Commerce" in n for n in names) or any("ERP" in n for n in names)


# ── extract_business_terms ────────────────────────────────────────────────────

class TestExtractBusinessTerms:
    def test_finds_domain_terms(self):
        terms = extract_business_terms("The order and invoice are processed by the ERP system.")
        assert "order" in terms
        assert "invoice" in terms
        assert "erp" in terms


# ── extract_state_transitions ─────────────────────────────────────────────────

class TestExtractStateTransitions:
    def test_finds_arrow_transitions(self):
        transitions = extract_state_transitions("Status changes: Created -> Confirmed -> Shipped.")
        assert any("Created" in t for t in transitions)

    def test_empty_when_no_transitions(self):
        assert extract_state_transitions("The product was listed.") == []


# ── contains_flags ────────────────────────────────────────────────────────────

class TestContainsFlags:
    def test_table_chunk_type(self):
        flags = contains_flags("some text", ChunkType.TABLE)
        assert flags["contains_table"] is True
        assert flags["contains_figure"] is False

    def test_figure_chunk_type(self):
        flags = contains_flags("some text", ChunkType.FIGURE)
        assert flags["contains_figure"] is True

    def test_contains_rules_from_text(self):
        flags = contains_flags("This field is mandatory and required.", ChunkType.TEXT)
        assert flags["contains_rules"] is True

    def test_contains_mapping_from_text(self):
        flags = contains_flags("The source maps to the target field.", ChunkType.TEXT)
        assert flags["contains_mapping"] is True

    def test_contains_code_from_backticks(self):
        flags = contains_flags("See ```python\nprint()\n```", ChunkType.TEXT)
        assert flags["contains_code"] is True


# ── classify_semantic_type ────────────────────────────────────────────────────

class TestClassifySemanticType:
    def test_figure_is_diagram(self):
        st = classify_semantic_type("", ChunkType.FIGURE, [], [], [], [])
        assert st == SemanticType.DIAGRAM_OR_VISUAL

    def test_table_is_data_mapping(self):
        st = classify_semantic_type("some table", ChunkType.TABLE, [], [], [], [])
        assert st == SemanticType.DATA_MAPPING_CANDIDATE

    def test_business_rule_from_markers(self):
        st = classify_semantic_type(
            "This field is mandatory and shall be validated.",
            ChunkType.TEXT,
            ["mandatory", "shall"],
            [],
            [],
            [],
        )
        assert st == SemanticType.BUSINESS_RULE

    def test_error_handling_from_markers(self):
        st = classify_semantic_type(
            "On timeout, trigger a rollback and retry.",
            ChunkType.TEXT,
            [],
            ["timeout", "rollback", "retry"],
            [],
            [],
        )
        assert st == SemanticType.ERROR_HANDLING

    def test_field_definition_from_fields(self):
        st = classify_semantic_type(
            "order_id, product_id, customer_id",
            ChunkType.TEXT,
            [],
            [],
            ["order_id", "product_id", "customer_id"],
            [],
        )
        assert st == SemanticType.FIELD_DEFINITION

    def test_generic_context_fallback(self):
        st = classify_semantic_type("The document describes the project.", ChunkType.TEXT, [], [], [], [])
        assert st in (SemanticType.GENERIC_CONTEXT, SemanticType.SYSTEM_OVERVIEW)


# ── classify_chunk (integration) ─────────────────────────────────────────────

class TestClassifyChunk:
    def test_returns_v2_metadata(self):
        meta = classify_chunk(
            text="This mandatory rule must be applied.",
            chunk_type="text",
            chunk_id="KB-001-chunk-0",
            document_id="KB-001",
            source_modality="pdf",
        )
        assert meta.kb_schema_version == "v2"
        assert meta.chunk_id == "KB-001-chunk-0"
        assert meta.document_id == "KB-001"

    def test_unknown_chunk_type_normalised(self):
        meta = classify_chunk(
            text="Some content.",
            chunk_type="bogus_type",
            chunk_id="x",
            document_id="d",
        )
        assert meta.chunk_type == ChunkType.TEXT

    def test_table_chunk_type_preserved(self):
        meta = classify_chunk(
            text="order_id | product_id | qty",
            chunk_type="table",
            chunk_id="x",
            document_id="d",
        )
        assert meta.chunk_type == ChunkType.TABLE
        assert meta.contains_table is True

    def test_confidence_increases_with_signals(self):
        weak = classify_chunk("The document describes things.", "text", "x", "d")
        strong = classify_chunk(
            "The order_id must be mandatory. OrderItem and ProductMaster are entities.",
            "text", "x", "d",
        )
        assert strong.confidence_semantic_enrichment > weak.confidence_semantic_enrichment

    def test_tags_carried_through(self):
        meta = classify_chunk("text", "text", "x", "d", tags=["erp", "order"])
        assert "erp" in meta.tags
        assert "order" in meta.tags
