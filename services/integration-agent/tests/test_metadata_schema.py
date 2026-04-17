"""Unit tests for services/metadata_schema.py — ADR-048."""
import pytest

from services.metadata_schema import (
    ChunkMetadataV2,
    ChunkType,
    SemanticType,
    flatten_to_chroma,
)


# ── ChunkType ─────────────────────────────────────────────────────────────────

class TestChunkType:
    def test_known_values_in_all(self):
        for val in [
            ChunkType.TEXT, ChunkType.TABLE, ChunkType.FIGURE, ChunkType.CODE,
            ChunkType.RULE, ChunkType.MAPPING, ChunkType.UI_FLOW,
            ChunkType.VALIDATION, ChunkType.STATE_TRANSITION,
            ChunkType.ENDPOINT, ChunkType.SCHEMA, ChunkType.SUMMARY,
        ]:
            assert val in ChunkType.ALL

    def test_all_count(self):
        assert len(ChunkType.ALL) == 12


# ── SemanticType ──────────────────────────────────────────────────────────────

class TestSemanticType:
    def test_known_values_in_all(self):
        for val in [
            SemanticType.GENERIC_CONTEXT, SemanticType.BUSINESS_RULE,
            SemanticType.DATA_MAPPING_CANDIDATE, SemanticType.INTEGRATION_FLOW,
            SemanticType.SYSTEM_OVERVIEW, SemanticType.ERROR_HANDLING,
            SemanticType.VALIDATION_RULE, SemanticType.ENTITY_DEFINITION,
            SemanticType.FIELD_DEFINITION, SemanticType.API_CONTRACT,
            SemanticType.EVENT_DEFINITION, SemanticType.UI_INTERACTION,
            SemanticType.STATE_MODEL, SemanticType.SECURITY_REQUIREMENT,
            SemanticType.DIAGRAM_OR_VISUAL,
        ]:
            assert val in SemanticType.ALL

    def test_all_count(self):
        assert len(SemanticType.ALL) == 15


# ── ChunkMetadataV2 defaults ──────────────────────────────────────────────────

class TestChunkMetadataV2Defaults:
    def test_required_fields(self):
        meta = ChunkMetadataV2(chunk_id="c1", document_id="d1")
        assert meta.chunk_id == "c1"
        assert meta.document_id == "d1"
        assert meta.kb_schema_version == "v2"

    def test_list_defaults_are_empty_lists(self):
        meta = ChunkMetadataV2(chunk_id="c1", document_id="d1")
        assert meta.entity_names == []
        assert meta.field_names == []
        assert meta.tags == []

    def test_bool_defaults_are_false(self):
        meta = ChunkMetadataV2(chunk_id="c1", document_id="d1")
        assert meta.contains_table is False
        assert meta.contains_rules is False
        assert meta.contains_mapping is False

    def test_list_mutation_isolated(self):
        a = ChunkMetadataV2(chunk_id="a", document_id="d")
        b = ChunkMetadataV2(chunk_id="b", document_id="d")
        a.entity_names.append("X")
        assert b.entity_names == []


# ── flatten_to_chroma ─────────────────────────────────────────────────────────

class TestFlattenToChroma:
    def _make(self, **kwargs) -> ChunkMetadataV2:
        return ChunkMetadataV2(
            chunk_id="ck-1", document_id="KB-001",
            entity_names=["OrderItem", "Product"],
            field_names=["order_id", "sku"],
            tags=["erp", "order"],
            **kwargs,
        )

    def test_no_list_values_in_output(self):
        flat = flatten_to_chroma(self._make())
        for k, v in flat.items():
            assert not isinstance(v, list), f"Key {k!r} has a list value"

    def test_entity_names_csv(self):
        flat = flatten_to_chroma(self._make())
        assert flat["entity_names"] == "OrderItem,Product"

    def test_tags_csv(self):
        flat = flatten_to_chroma(self._make())
        assert flat["tags_csv"] == "erp,order"

    def test_schema_version_present(self):
        flat = flatten_to_chroma(self._make())
        assert flat["kb_schema_version"] == "v2"

    def test_extra_merged(self):
        flat = flatten_to_chroma(self._make(), extra={"custom_field": "hello"})
        assert flat["custom_field"] == "hello"

    def test_extra_overrides(self):
        flat = flatten_to_chroma(self._make(), extra={"kb_schema_version": "v3"})
        assert flat["kb_schema_version"] == "v3"

    def test_bool_fields_are_bool(self):
        flat = flatten_to_chroma(self._make(contains_table=True))
        assert flat["contains_table"] is True
        assert isinstance(flat["contains_rules"], bool)

    def test_empty_list_becomes_empty_string(self):
        flat = flatten_to_chroma(ChunkMetadataV2(chunk_id="x", document_id="y"))
        assert flat["entity_names"] == ""
        assert flat["tags_csv"] == ""
