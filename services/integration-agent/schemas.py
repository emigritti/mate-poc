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


class CatalogEntry(BaseModel):
    id: str
    name: str
    type: str
    source: Dict[str, str]
    target: Dict[str, str]
    requirements: List[str]
    status: str
    tags: List[str] = []          # confirmed tags (max 5)
    created_at: str


class Document(BaseModel):
    id: str
    integration_id: str
    doc_type: str  # 'functional' or 'technical'
    content: str
    generated_at: str
    kb_status: Literal["staged", "promoted"] = "staged"


class Approval(BaseModel):
    id: str
    integration_id: str
    doc_type: str
    content: str
    status: str  # 'PENDING', 'APPROVED', 'REJECTED'
    generated_at: str
    feedback: Optional[str] = None


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


class ConfirmTagsRequest(BaseModel):
    """Body for POST /api/v1/catalog/integrations/{id}/confirm-tags."""
    tags: List[str] = Field(
        min_length=1,
        max_length=5,
        description="Confirmed tags (1–5 items). Each tag max 50 chars.",
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
