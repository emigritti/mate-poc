"""
TDD — Source Models Unit Tests (RED phase)

Tests run BEFORE models/source.py and models/capability.py exist.
Expected failure: ModuleNotFoundError → confirms feature is missing.
"""
import pytest
from pydantic import ValidationError


# ── Source model tests ──────────────────────────────────────────────────────

class TestSourceCreate:
    def test_valid_openapi_source_creates_successfully(self):
        from models.source import SourceCreate, SourceType
        s = SourceCreate(
            code="payment_api",
            source_type=SourceType.OPENAPI,
            entrypoints=["https://api.example.com/openapi.json"],
            tags=["payment"],
        )
        assert s.source_type == SourceType.OPENAPI
        assert s.code == "payment_api"

    def test_invalid_source_type_raises_validation_error(self):
        from models.source import SourceCreate
        with pytest.raises(ValidationError):
            SourceCreate(
                code="bad",
                source_type="invalid_type",
                entrypoints=["https://example.com"],
                tags=["test"],
            )

    def test_empty_entrypoints_raises_validation_error(self):
        from models.source import SourceCreate, SourceType
        with pytest.raises(ValidationError):
            SourceCreate(
                code="no_endpoints",
                source_type=SourceType.OPENAPI,
                entrypoints=[],
                tags=["test"],
            )

    def test_empty_tags_raises_validation_error(self):
        from models.source import SourceCreate, SourceType
        with pytest.raises(ValidationError):
            SourceCreate(
                code="no_tags",
                source_type=SourceType.MCP,
                entrypoints=["https://example.com"],
                tags=[],
            )

    def test_all_three_source_types_are_valid(self):
        from models.source import SourceCreate, SourceType
        for st in [SourceType.OPENAPI, SourceType.HTML, SourceType.MCP]:
            s = SourceCreate(
                code=f"src_{st.value}",
                source_type=st,
                entrypoints=["https://example.com"],
                tags=["test"],
            )
            assert s.source_type == st

    def test_default_refresh_cron_is_set(self):
        from models.source import SourceCreate, SourceType
        s = SourceCreate(
            code="with_defaults",
            source_type=SourceType.HTML,
            entrypoints=["https://example.com"],
            tags=["test"],
        )
        assert s.refresh_cron is not None
        assert len(s.refresh_cron) > 0


class TestSource:
    def test_source_has_default_active_status(self):
        from models.source import Source, SourceType, SourceState
        s = Source(
            id="src_001",
            code="payment_api",
            source_type=SourceType.OPENAPI,
            entrypoints=["https://example.com"],
            tags=["payment"],
        )
        assert s.status.state == SourceState.ACTIVE

    def test_source_has_created_at_timestamp(self):
        from models.source import Source, SourceType
        from datetime import datetime
        s = Source(
            id="src_002",
            code="mcp_jira",
            source_type=SourceType.MCP,
            entrypoints=["https://mcp.example.com"],
            tags=["jira"],
        )
        assert isinstance(s.created_at, datetime)


class TestSourceRun:
    def test_source_run_default_status_is_pending(self):
        from models.source import SourceRun, SourceType, RunTrigger, RunStatus
        run = SourceRun(
            id="run_001",
            source_id="src_001",
            trigger=RunTrigger.MANUAL,
            collector_type=SourceType.OPENAPI,
        )
        assert run.status == RunStatus.PENDING

    def test_source_run_default_chunks_created_is_zero(self):
        from models.source import SourceRun, SourceType, RunTrigger
        run = SourceRun(
            id="run_002",
            source_id="src_001",
            trigger=RunTrigger.SCHEDULER,
            collector_type=SourceType.MCP,
        )
        assert run.chunks_created == 0
        assert run.changed is False
        assert run.errors == []

    def test_source_run_invalid_trigger_raises_error(self):
        from models.source import SourceRun, SourceType
        with pytest.raises(ValidationError):
            SourceRun(
                id="run_bad",
                source_id="src_001",
                trigger="invalid_trigger",
                collector_type=SourceType.OPENAPI,
            )


class TestSourceSnapshot:
    def test_snapshot_default_is_current(self):
        from models.source import SourceSnapshot
        snap = SourceSnapshot(
            id="snap_001",
            source_id="src_001",
            content_hash="sha256:abc123",
            capabilities_count=12,
        )
        assert snap.is_current is True

    def test_snapshot_capabilities_count_stored(self):
        from models.source import SourceSnapshot
        snap = SourceSnapshot(
            id="snap_002",
            source_id="src_001",
            content_hash="sha256:def456",
            capabilities_count=42,
        )
        assert snap.capabilities_count == 42

    def test_snapshot_diff_summary_optional(self):
        from models.source import SourceSnapshot
        snap = SourceSnapshot(
            id="snap_003",
            source_id="src_001",
            content_hash="sha256:ghi789",
            capabilities_count=5,
        )
        assert snap.diff_summary is None


# ── CanonicalCapability model tests ─────────────────────────────────────────

class TestCanonicalCapability:
    def test_all_capability_kinds_are_valid(self):
        from models.capability import CanonicalCapability, CapabilityKind, SourceTrace
        for kind in CapabilityKind:
            cap = CanonicalCapability(
                capability_id=f"cap_{kind.value}",
                kind=kind,
                name=f"Test {kind.value}",
                source_code="payment_api",
                source_trace=SourceTrace(
                    origin_type="openapi",
                    origin_pointer=f"paths./{kind.value}.get",
                ),
            )
            assert cap.kind == kind

    def test_capability_default_confidence_is_one(self):
        from models.capability import CanonicalCapability, CapabilityKind, SourceTrace
        cap = CanonicalCapability(
            capability_id="cap_001",
            kind=CapabilityKind.ENDPOINT,
            name="Create Payment",
            source_code="payment_api",
            source_trace=SourceTrace(origin_type="openapi", origin_pointer="paths./payments.post"),
        )
        assert cap.confidence == 1.0

    def test_capability_with_low_confidence(self):
        from models.capability import CanonicalCapability, CapabilityKind, SourceTrace
        cap = CanonicalCapability(
            capability_id="cap_low",
            kind=CapabilityKind.ENDPOINT,
            name="Unclear endpoint",
            source_code="html_docs",
            source_trace=SourceTrace(origin_type="html", origin_pointer="page:3 section:auth"),
            confidence=0.5,
        )
        assert cap.confidence < 0.7  # below threshold


class TestCanonicalChunk:
    def test_chunk_id_convention(self):
        from models.capability import CanonicalChunk
        chunk = CanonicalChunk(
            text="POST /payments — create a new payment",
            index=0,
            source_code="payment_api",
            source_type="openapi",
            capability_kind="endpoint",
        )
        expected_id = f"src_{chunk.source_code}-chunk-{chunk.index}"
        assert expected_id == "src_payment_api-chunk-0"

    def test_chunk_tags_default_empty(self):
        from models.capability import CanonicalChunk
        chunk = CanonicalChunk(
            text="Tool: create_ticket",
            index=5,
            source_code="jira_mcp",
            source_type="mcp",
            capability_kind="tool",
        )
        assert chunk.tags == []

    def test_chunk_metadata_dict_has_required_fields(self):
        from models.capability import CanonicalChunk
        chunk = CanonicalChunk(
            text="GET /pets — list all pets",
            index=2,
            source_code="petstore",
            source_type="openapi",
            capability_kind="endpoint",
            section_header="Pets API",
            tags=["pets", "api"],
        )
        meta = chunk.to_chroma_metadata(snapshot_id="snap_001")
        assert meta["source_type"] == "openapi"
        assert meta["source_code"] == "petstore"
        assert meta["snapshot_id"] == "snap_001"
        assert meta["capability_kind"] == "endpoint"
        assert meta["tags_csv"] == "pets,api"
        assert meta["section_header"] == "Pets API"
        # Must be compatible with existing kb_collection schema
        assert "chunk_type" in meta
        assert "page_num" in meta
