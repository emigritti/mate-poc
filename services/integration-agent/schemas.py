from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field
from typing import Dict, List, Literal, Optional


class LogLevel(str, Enum):
    INFO    = "INFO"
    LLM     = "LLM"
    RAG     = "RAG"
    SUCCESS = "SUCCESS"
    WARN    = "WARN"
    ERROR   = "ERROR"
    CANCEL  = "CANCEL"


class LogEntry(BaseModel):
    ts:      datetime
    level:   LogLevel
    message: str


class Requirement(BaseModel):
    req_id: str
    source_system: str
    target_system: str
    category: str
    description: str
    mandatory: bool = False
    upload_id: Optional[str] = None   # UUID of the upload session (ADR-050)
    project_id: Optional[str] = None  # set on finalize (ADR-050)


class CatalogEntry(BaseModel):
    id: str
    name: str
    type: str
    source: Dict[str, str]
    target: Dict[str, str]
    requirements: List[str]
    status: str
    tags: List[str] = []          # confirmed tags (max 15)
    project_id: str = "LEGACY"    # FK to Project.prefix; "LEGACY" for pre-ADR-025 entries
    created_at: str


class Document(BaseModel):
    id: str
    integration_id: str
    doc_type: str = "integration"  # always "integration" (unified single-doc model)
    content: str
    generated_at: str
    kb_status: Literal["staged", "promoted"] = "staged"


# ── Generation Source Report (traceability for each generated document) ────────

class SourceChunkInfo(BaseModel):
    """Metadata for a single retrieved chunk used during generation."""
    source_label: str   # "approved_example" | "kb_document" | "kb_url" | "summary"
    doc_id: str         # ChromaDB / KB document identifier
    score: float        # relevance score
    preview: str        # first 150 chars of the chunk text


class SectionReport(BaseModel):
    """Per-section confidence and evidence attribution (ADR-041)."""
    section: str                    # e.g. "Error Handling"
    source_chunk_ids: List[str] = []
    confidence: float               # 0.0–1.0, weighted average of claim confidence levels
    issues: List[str] = []         # e.g. ["low_evidence_density", "missing_evidence"]


class ClaimReport(BaseModel):
    """Per-claim evidence record surfaced from FactPack.evidence (ADR-041)."""
    claim_id: str
    statement: str
    confidence: str                 # "confirmed"|"inferred"|"missing_evidence"|"to_validate"
    source_chunk_count: int


class GenerationReport(BaseModel):
    """
    Traceability report attached to every generated Approval.

    Captures which sources informed the LLM, quality metrics,
    and whether Claude API enrichment was applied.

    ADR-041 adds optional FactPack fields (all default to safe values so
    existing callers that omit them remain backward-compatible).
    """
    model: str
    prompt_chars: int
    context_chars: int
    sources: List[SourceChunkInfo]
    sections_count: int
    na_count: int
    quality_score: float
    quality_issues: List[str]
    claude_enriched: bool
    # ── FactPack fields (ADR-041) — optional; None-equivalent defaults ──
    fact_pack_used: bool = False
    fact_pack_extraction_model: str = ""
    section_reports: List[SectionReport] = []
    claim_reports: List[ClaimReport] = []
    confirmed_claim_count: int = 0
    inferred_claim_count: int = 0
    missing_evidence_count: int = 0
    to_validate_count: int = 0
    # ── Generation path (document-quality improvement #4) ─────────────
    # "fact_pack"           — two-step FactPack pipeline succeeded
    # "single_pass_fallback"— FactPack enabled but extraction failed/returned None
    # "single_pass_disabled"— FactPack kill-switch off (FACT_PACK_ENABLED=false)
    generation_path: str = "single_pass_disabled"
    fallback_reason: str = ""   # populated when generation_path != "fact_pack"


class Approval(BaseModel):
    id: str
    integration_id: str
    doc_type: str = "integration"  # always "integration" (unified single-doc model)
    content: str
    status: str  # 'PENDING', 'APPROVED', 'REJECTED'
    generated_at: str
    feedback: Optional[str] = None
    generation_report: Optional[GenerationReport] = None


# ── Typed request bodies (replaces bare dict — ADR-016 / OWASP A03) ──────────

class ApproveRequest(BaseModel):
    """Body for POST /api/v1/approvals/{id}/approve.

    final_markdown is the (optionally edited) content the HITL reviewer
    approves.  It will be sanitized before storage.
    """
    final_markdown: str = Field(
        min_length=1,
        max_length=50_000,
        description="Reviewed markdown content to approve and store.",
    )


class RejectRequest(BaseModel):
    """Body for POST /api/v1/approvals/{id}/reject."""
    feedback: str = Field(
        min_length=1,
        max_length=2_000,
        description="Reason for rejection — used as context for agent retry.",
    )


class SectionPromptRequest(BaseModel):
    """Body for POST /api/v1/approvals/build-improvement-prompt.

    The backend builds a contextual LLM prompt to improve the section,
    returning it for the reviewer to read and edit before execution.
    """
    section_title: str = Field(
        min_length=1,
        max_length=300,
        description="Heading text of the section (without leading # characters).",
    )
    section_content: str = Field(
        min_length=1,
        max_length=20_000,
        description="Current markdown content of the section (including the heading line).",
    )


class SectionImprovementRequest(BaseModel):
    """Body for POST /api/v1/approvals/run-improvement.

    Executes the (possibly reviewer-edited) prompt against the LLM and
    returns the suggested improved markdown for the section.
    """
    section_title: str = Field(
        min_length=1,
        max_length=300,
    )
    section_content: str = Field(
        min_length=1,
        max_length=20_000,
    )
    improvement_prompt: str = Field(
        min_length=1,
        max_length=4_000,
        description="The improvement prompt the reviewer approved (may have been edited).",
    )


class ConfirmTagsRequest(BaseModel):
    """Body for POST /api/v1/catalog/integrations/{id}/confirm-tags."""
    tags: List[str] = Field(
        min_length=1,
        max_length=15,
        description="Confirmed tags (1–15 items). Each tag max 50 chars.",
    )


class SuggestTagsResponse(BaseModel):
    """Response for GET /api/v1/catalog/integrations/{id}/suggest-tags."""
    integration_id: str
    suggested_tags: List[str]
    source: Dict[str, List[str]]


# ── Knowledge Base models ─────────────────────────────────────────────────────

class KBDocument(BaseModel):
    """Metadata record for a Knowledge Base document stored in MongoDB.

    source_type distinguishes file uploads ("file") from registered HTTP/HTTPS
    URLs ("url"). URL entries have chunk_count=0 and no ChromaDB data — their
    content is fetched live at generation time.
    """
    id: str
    filename: str
    file_type: str                  # "pdf", "docx", "xlsx", "pptx", "md", "url"
    file_size_bytes: int
    tags: List[str] = []
    chunk_count: int
    content_preview: str            # first ~500 chars of extracted text (empty for URLs)
    uploaded_at: str
    source_type: Literal["file", "url"] = "file"
    url: Optional[str] = None       # populated for source_type="url" entries only


class KBUploadResponse(BaseModel):
    """Response for POST /api/v1/kb/upload."""
    id: str
    filename: str
    file_type: str
    chunks_created: int
    auto_tags: List[str]
    raptor_status: str = "done"  # "pending" = summarization in background; "done" = completed inline


class KBAddUrlRequest(BaseModel):
    """Body for POST /api/v1/kb/add-url."""
    url: str = Field(
        description="HTTP or HTTPS URL to register as a KB reference link.",
    )
    title: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional display name. Defaults to the URL hostname.",
    )
    tags: List[str] = Field(
        min_length=1,
        max_length=10,
        description="Tags used to filter this URL during generation (1–10 items).",
    )


class KBUpdateTagsRequest(BaseModel):
    """Body for PUT /api/v1/kb/documents/{id}/tags."""
    tags: List[str] = Field(
        min_length=1,
        max_length=10,
        description="Updated tags (1–10 items). Each tag max 50 chars.",
    )


class KBSearchRequest(BaseModel):
    """Query parameters for GET /api/v1/kb/search."""
    query: str = Field(
        min_length=1,
        max_length=500,
        description="Semantic search query.",
    )


class KBSearchResult(BaseModel):
    """A single search result from the Knowledge Base."""
    chunk_text: str
    document_id: str
    filename: str
    score: Optional[float] = None


class KBSearchResponse(BaseModel):
    """Response for GET /api/v1/kb/search."""
    results: List[KBSearchResult]
    query: str
    total_results: int


class KBStatsResponse(BaseModel):
    """Response for GET /api/v1/kb/stats."""
    total_documents: int
    total_chunks: int
    file_types: Dict[str, int]
    all_tags: List[str]


class KBExportChunk(BaseModel):
    """A single ChromaDB chunk serialised for export."""
    id: str
    text: str
    metadata: Dict


class KBExportBundle(BaseModel):
    """
    Portable KB snapshot produced by GET /api/v1/kb/export (ADR-051).

    Contains KBDocument metadata records (file + url source types) and the
    raw chunk text + metadata for all source types.  Embeddings are NOT
    included — ChromaDB re-embeds chunks on import.
    """
    export_version: str = "1.0"
    exported_at: str
    source_types_included: List[str]
    kb_documents: List[KBDocument]
    chunks: List[KBExportChunk]


class KBImportResult(BaseModel):
    """Summary returned by POST /api/v1/kb/import (ADR-051)."""
    documents_imported: int
    documents_skipped: int
    chunks_imported: int
    chunks_skipped: int
    errors: List[str]


# ── Project models (ADR-025) ──────────────────────────────────────────────────

class Project(BaseModel):
    """A client project that groups one or more CSV upload sessions.

    prefix is the natural unique key (1-3 uppercase alphanumeric chars).
    It is used as the ID prefix for all CatalogEntries in this project
    (e.g., prefix="ACM" → entry IDs like "ACM-4F2A1B").
    """
    prefix: str                            # e.g., "ACM"
    client_name: str
    domain: str
    description: Optional[str] = None
    accenture_ref: Optional[str] = None
    created_at: str


class ProjectCreateRequest(BaseModel):
    """Body for POST /api/v1/projects."""
    prefix: str = Field(
        ...,
        pattern=r"^[A-Z0-9]{1,3}$",
        description="1-3 uppercase alphanumeric chars. Auto-generated from client initials.",
    )
    client_name: str = Field(..., min_length=1, max_length=100)
    domain: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    accenture_ref: Optional[str] = Field(None, max_length=100)


class FinalizeRequirementsRequest(BaseModel):
    """Body for POST /api/v1/requirements/finalize."""
    project_id: str = Field(
        ...,
        pattern=r"^[A-Za-z0-9]{1,3}$",
        description="Prefix of an existing Project. CatalogEntries will use this as ID prefix.",
    )
    field_overrides: Optional[dict[str, dict[str, str]]] = Field(
        None,
        description=(
            "Optional per-req_id overrides supplied by the user when source/target "
            "could not be extracted automatically. "
            "Format: {req_id: {source_system?: str, target_system?: str}}"
        ),
    )
