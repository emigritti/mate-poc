from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field
from typing import List, Dict, Optional


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
    created_at: str


class Document(BaseModel):
    id: str
    integration_id: str
    doc_type: str  # 'functional' or 'technical'
    content: str
    generated_at: str


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
