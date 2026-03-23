"""
Ingestion Platform — Source Domain Models

Defines the core entities: Source (registry entry), SourceRun (execution audit),
SourceSnapshot (lite versioning — current + previous only).
"""
from enum import Enum
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class SourceType(str, Enum):
    OPENAPI = "openapi"
    HTML = "html"
    MCP = "mcp"


class SourceState(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class RunTrigger(str, Enum):
    SCHEDULER = "scheduler"
    MANUAL = "manual"
    WEBHOOK = "webhook"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


# ── Source ──────────────────────────────────────────────────────────────────

class SourceStatus(BaseModel):
    state: SourceState = SourceState.ACTIVE
    last_run_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_error: Optional[str] = None


class SourceCreate(BaseModel):
    """Payload for registering a new ingestion source."""
    code: str                           # unique slug e.g. "payment_api_v3"
    source_type: SourceType
    entrypoints: list[str]              # URLs or MCP server addresses
    tags: list[str]                     # for RAG tag-filtering (inherits to chunks)
    refresh_cron: str = "0 */6 * * *"  # default: every 6 hours
    description: Optional[str] = None

    @field_validator("entrypoints")
    @classmethod
    def must_have_entrypoint(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("at least one entrypoint is required")
        return v

    @field_validator("tags")
    @classmethod
    def must_have_tag(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("at least one tag is required")
        return v


class Source(SourceCreate):
    """Persisted source registry entry (with id + status)."""
    id: str
    status: SourceStatus = Field(default_factory=SourceStatus)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── SourceRun ────────────────────────────────────────────────────────────────

class SourceRun(BaseModel):
    """Audit record for a single ingestion execution."""
    id: str
    source_id: str
    trigger: RunTrigger
    collector_type: SourceType
    status: RunStatus = RunStatus.PENDING
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    chunks_created: int = 0
    changed: bool = False
    errors: list[str] = Field(default_factory=list)


# ── SourceSnapshot ───────────────────────────────────────────────────────────

class SourceSnapshot(BaseModel):
    """
    Lite versioning: stores current + previous snapshot per source.
    Full v3 diff history is out of scope for PoC — extendable later.
    """
    id: str
    source_id: str
    snapshot_no: int = 1
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    content_hash: str                   # SHA-256 of normalized content
    is_current: bool = True
    capabilities_count: int = 0
    diff_summary: Optional[str] = None  # Claude Haiku change summary
