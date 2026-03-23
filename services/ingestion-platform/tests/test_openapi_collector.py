"""
TDD — OpenAPI Collector Unit Tests (RED phase)

Tests fetcher → parser → normalizer → chunker → differ pipeline.
All HTTP calls mocked — no network required.
"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch


# ── Fixtures ──────────────────────────────────────────────────────────────────

PETSTORE_SPEC_MINIMAL = {
    "openapi": "3.0.0",
    "info": {"title": "Pet Store", "version": "1.0.0", "description": "A sample pet store API"},
    "servers": [{"url": "https://petstore.example.com/v1"}],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List all pets",
                "tags": ["pets"],
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}}
                ],
                "responses": {
                    "200": {"description": "A list of pets."}
                },
            },
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet",
                "tags": ["pets"],
                "requestBody": {
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}}
                },
                "responses": {"201": {"description": "Null response."}},
            },
        },
        "/pets/{petId}": {
            "get": {
                "operationId": "showPetById",
                "summary": "Info for a specific pet",
                "parameters": [{"name": "petId", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Expected response."}},
            }
        },
    },
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "required": ["id", "name"],
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "tag": {"type": "string"},
                },
            }
        }
    },
}

SWAGGER_2_SPEC_MINIMAL = {
    "swagger": "2.0",
    "info": {"title": "Simple API", "version": "0.1.0"},
    "host": "api.example.com",
    "basePath": "/v1",
    "paths": {
        "/users": {
            "get": {
                "operationId": "listUsers",
                "summary": "List users",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}


# ── Parser tests ──────────────────────────────────────────────────────────────

class TestOpenAPIParser:
    def test_parses_openapi_3_json(self):
        from collectors.openapi.parser import OpenAPIParser
        parser = OpenAPIParser()
        result = parser.parse(json.dumps(PETSTORE_SPEC_MINIMAL))
        assert result is not None
        assert result["info"]["title"] == "Pet Store"

    def test_parses_openapi_3_yaml(self):
        import yaml
        from collectors.openapi.parser import OpenAPIParser
        parser = OpenAPIParser()
        result = parser.parse(yaml.dump(PETSTORE_SPEC_MINIMAL))
        assert result["openapi"] == "3.0.0"

    def test_parses_swagger_2(self):
        from collectors.openapi.parser import OpenAPIParser
        parser = OpenAPIParser()
        result = parser.parse(json.dumps(SWAGGER_2_SPEC_MINIMAL))
        assert result["swagger"] == "2.0"

    def test_raises_on_invalid_json(self):
        from collectors.openapi.parser import OpenAPIParser, OpenAPIParseError
        parser = OpenAPIParser()
        with pytest.raises(OpenAPIParseError):
            parser.parse("this is not json or yaml {{{")

    def test_raises_on_missing_paths(self):
        from collectors.openapi.parser import OpenAPIParser, OpenAPIParseError
        parser = OpenAPIParser()
        bad_spec = {"openapi": "3.0.0", "info": {"title": "Bad", "version": "1.0"}}
        with pytest.raises(OpenAPIParseError):
            parser.parse(json.dumps(bad_spec))


# ── Normalizer tests ──────────────────────────────────────────────────────────

class TestOpenAPINormalizer:
    def test_normalizes_endpoints_to_capabilities(self):
        from collectors.openapi.normalizer import OpenAPINormalizer
        norm = OpenAPINormalizer()
        caps = norm.normalize(PETSTORE_SPEC_MINIMAL, source_code="petstore")
        endpoint_caps = [c for c in caps if c.kind.value == "endpoint"]
        assert len(endpoint_caps) == 3  # listPets, createPet, showPetById

    def test_each_capability_has_source_trace(self):
        from collectors.openapi.normalizer import OpenAPINormalizer
        norm = OpenAPINormalizer()
        caps = norm.normalize(PETSTORE_SPEC_MINIMAL, source_code="petstore")
        for cap in caps:
            assert cap.source_trace.origin_type == "openapi"
            assert cap.source_trace.origin_pointer != ""

    def test_schema_components_produce_schema_capabilities(self):
        from collectors.openapi.normalizer import OpenAPINormalizer
        norm = OpenAPINormalizer()
        caps = norm.normalize(PETSTORE_SPEC_MINIMAL, source_code="petstore")
        schema_caps = [c for c in caps if c.kind.value == "schema"]
        assert len(schema_caps) >= 1  # at least "Pet" schema

    def test_capability_ids_are_unique(self):
        from collectors.openapi.normalizer import OpenAPINormalizer
        norm = OpenAPINormalizer()
        caps = norm.normalize(PETSTORE_SPEC_MINIMAL, source_code="petstore")
        ids = [c.capability_id for c in caps]
        assert len(ids) == len(set(ids))

    def test_swagger2_endpoints_normalized(self):
        from collectors.openapi.normalizer import OpenAPINormalizer
        norm = OpenAPINormalizer()
        caps = norm.normalize(SWAGGER_2_SPEC_MINIMAL, source_code="simple_api")
        endpoint_caps = [c for c in caps if c.kind.value == "endpoint"]
        assert len(endpoint_caps) == 1
        assert "listUsers" in endpoint_caps[0].capability_id


# ── Chunker tests ─────────────────────────────────────────────────────────────

class TestOpenAPIChunker:
    def test_each_endpoint_produces_at_least_one_chunk(self):
        from collectors.openapi.normalizer import OpenAPINormalizer
        from collectors.openapi.chunker import OpenAPIChunker
        caps = OpenAPINormalizer().normalize(PETSTORE_SPEC_MINIMAL, source_code="petstore")
        chunks = OpenAPIChunker().chunk(caps, source_code="petstore", tags=["pets"])
        endpoint_chunks = [c for c in chunks if c.capability_kind == "endpoint"]
        assert len(endpoint_chunks) >= 3

    def test_chunks_have_source_type_openapi(self):
        from collectors.openapi.normalizer import OpenAPINormalizer
        from collectors.openapi.chunker import OpenAPIChunker
        caps = OpenAPINormalizer().normalize(PETSTORE_SPEC_MINIMAL, source_code="petstore")
        chunks = OpenAPIChunker().chunk(caps, source_code="petstore", tags=["pets"])
        assert all(c.source_type == "openapi" for c in chunks)

    def test_chunks_inherit_tags(self):
        from collectors.openapi.normalizer import OpenAPINormalizer
        from collectors.openapi.chunker import OpenAPIChunker
        caps = OpenAPINormalizer().normalize(PETSTORE_SPEC_MINIMAL, source_code="petstore")
        chunks = OpenAPIChunker().chunk(caps, source_code="petstore", tags=["pets", "api"])
        assert all("pets" in c.tags for c in chunks)

    def test_chunk_indices_are_sequential(self):
        from collectors.openapi.normalizer import OpenAPINormalizer
        from collectors.openapi.chunker import OpenAPIChunker
        caps = OpenAPINormalizer().normalize(PETSTORE_SPEC_MINIMAL, source_code="petstore")
        chunks = OpenAPIChunker().chunk(caps, source_code="petstore", tags=["test"])
        indices = [c.index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_overview_chunk_is_generated(self):
        from collectors.openapi.normalizer import OpenAPINormalizer
        from collectors.openapi.chunker import OpenAPIChunker
        caps = OpenAPINormalizer().normalize(PETSTORE_SPEC_MINIMAL, source_code="petstore")
        chunks = OpenAPIChunker().chunk(caps, source_code="petstore", tags=["test"])
        overview_chunks = [c for c in chunks if c.capability_kind == "overview"]
        assert len(overview_chunks) == 1
        assert "Pet Store" in overview_chunks[0].text


# ── Differ tests ──────────────────────────────────────────────────────────────

class TestOpenAPIDiffer:
    def test_same_spec_produces_no_change(self):
        from collectors.openapi.differ import OpenAPIDiffer
        differ = OpenAPIDiffer()
        hash1 = differ.compute_hash(PETSTORE_SPEC_MINIMAL)
        hash2 = differ.compute_hash(PETSTORE_SPEC_MINIMAL)
        assert hash1 == hash2
        assert not differ.has_changed(hash1, hash2)

    def test_added_endpoint_detected(self):
        from collectors.openapi.differ import OpenAPIDiffer
        differ = OpenAPIDiffer()
        spec_v1 = PETSTORE_SPEC_MINIMAL.copy()
        spec_v2 = {**PETSTORE_SPEC_MINIMAL, "paths": {
            **PETSTORE_SPEC_MINIMAL["paths"],
            "/orders": {"get": {"operationId": "listOrders", "summary": "List orders", "responses": {"200": {"description": "OK"}}}}
        }}
        hash1 = differ.compute_hash(spec_v1)
        hash2 = differ.compute_hash(spec_v2)
        assert differ.has_changed(hash1, hash2)

    def test_removed_endpoint_detected(self):
        from collectors.openapi.differ import OpenAPIDiffer
        differ = OpenAPIDiffer()
        spec_v1 = PETSTORE_SPEC_MINIMAL
        spec_v2 = {**PETSTORE_SPEC_MINIMAL, "paths": {"/pets": PETSTORE_SPEC_MINIMAL["paths"]["/pets"]}}
        hash1 = differ.compute_hash(spec_v1)
        hash2 = differ.compute_hash(spec_v2)
        assert differ.has_changed(hash1, hash2)

    def test_hash_is_sha256_hex_string(self):
        from collectors.openapi.differ import OpenAPIDiffer
        differ = OpenAPIDiffer()
        h = differ.compute_hash(PETSTORE_SPEC_MINIMAL)
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex = 64 chars

    def test_detect_removed_operation_as_breaking(self):
        from collectors.openapi.differ import OpenAPIDiffer
        differ = OpenAPIDiffer()
        v1_ops = {"listPets", "createPet", "showPetById"}
        v2_ops = {"listPets", "createPet"}  # showPetById removed
        result = differ.classify_changes(v1_ops, v2_ops)
        assert result["severity"] == "breaking"
        assert "showPetById" in result["removed"]

    def test_detect_added_operation_as_minor(self):
        from collectors.openapi.differ import OpenAPIDiffer
        differ = OpenAPIDiffer()
        v1_ops = {"listPets"}
        v2_ops = {"listPets", "createPet"}  # new optional endpoint
        result = differ.classify_changes(v1_ops, v2_ops)
        assert result["severity"] == "minor"
        assert "createPet" in result["added"]

    def test_no_changes_returns_none_severity(self):
        from collectors.openapi.differ import OpenAPIDiffer
        differ = OpenAPIDiffer()
        ops = {"listPets", "createPet"}
        result = differ.classify_changes(ops, ops)
        assert result["severity"] is None
        assert result["added"] == set()
        assert result["removed"] == set()
