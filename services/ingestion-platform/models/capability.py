"""
Ingestion Platform — Canonical Capability Models

CanonicalCapability: unified representation of an API endpoint, MCP tool,
HTML-extracted flow, schema, or auth scheme — regardless of source type.

CanonicalChunk: a chunk ready for ChromaDB indexing with metadata compatible
with the existing integration-agent kb_collection schema.
"""
from enum import Enum
from typing import Optional, Any

from pydantic import BaseModel, Field


class CapabilityKind(str, Enum):
    ENDPOINT = "endpoint"
    TOOL = "tool"
    RESOURCE = "resource"
    SCHEMA = "schema"
    AUTH = "auth"
    INTEGRATION_FLOW = "integration_flow"
    GUIDE_STEP = "guide_step"
    EVENT = "event"
    OVERVIEW = "overview"          # API-level summary (title, description, servers)
    UI_SCREEN = "ui_screen"        # application screen / backoffice page (ADR-045)


class SourceTrace(BaseModel):
    """Citation back to the original source location."""
    origin_type: str        # openapi | html | mcp
    origin_pointer: str     # e.g. "paths./payments.post" or "tools.create_ticket"
    page_url: Optional[str] = None
    section: Optional[str] = None


class CanonicalCapability(BaseModel):
    """
    Unified capability extracted from any source type.
    confidence < 0.7 → low_confidence flag set in ChromaDB metadata.
    """
    capability_id: str
    kind: CapabilityKind
    name: str
    description: str = ""
    source_code: str                    # links back to Source.code
    source_trace: SourceTrace
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalChunk(BaseModel):
    """
    A text chunk ready for ChromaDB upsert into the shared kb_collection.

    Metadata schema is a superset of the integration-agent's existing fields:
    - existing: tags_csv, section_header, chunk_type, page_num, chunk_index, document_id
    - new: source_type, source_code, snapshot_id, capability_kind, low_confidence

    Zero changes required in integration-agent/services/retriever.py.
    """
    text: str
    index: int
    source_code: str                    # e.g. "payment_api_v3"
    source_type: str                    # openapi | mcp | html
    capability_kind: str                # endpoint | tool | resource | schema | auth | ui_screen
    chunk_type: str = "text"            # text | ui_flow_chunk | validation_rule_chunk | state_transition_chunk
    section_header: str = ""
    page_url: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    confidence: float = 1.0

    def chunk_id(self) -> str:
        """ID convention: src_{source_code}-chunk-{index}
        Never collides with integration-agent IDs (those use '{doc_id}-chunk-{n}')."""
        return f"src_{self.source_code}-chunk-{self.index}"

    def to_chroma_metadata(self, snapshot_id: str) -> dict[str, Any]:
        """
        Build ChromaDB metadata dict compatible with kb_collection schema.
        Fields recognized by integration-agent/services/retriever.py:
          tags_csv, section_header, chunk_type, page_num, chunk_index, document_id
        Additional fields for ingestion-platform filtering:
          source_type, source_code, snapshot_id, capability_kind, low_confidence
        """
        return {
            # ── existing kb_collection fields (retriever.py compatible) ──
            "document_id": f"src_{self.source_code}",
            "chunk_index": self.index,
            "tags_csv": ",".join(self.tags),
            "section_header": self.section_header,
            "chunk_type": self.chunk_type,
            "page_num": 0,                  # not applicable for API/MCP sources
            # ── ingestion-platform extension fields ──────────────────────
            "source_type": self.source_type,
            "source_code": self.source_code,
            "snapshot_id": snapshot_id,
            "capability_kind": self.capability_kind,
            "low_confidence": self.confidence < 0.7,
        }
