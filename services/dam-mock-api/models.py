"""
DAM Mock API — Pydantic Models (Bynder/Canto-style)
Simulates a Digital Asset Management system for binary assets
(images, videos, documents) used downstream by PIM and catalog pipelines.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────


class AssetType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    OTHER = "other"


class AssetStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DRAFT = "draft"


class RenditionFormat(str, Enum):
    THUMBNAIL = "thumbnail"   # 200×200 px
    WEB = "web"               # 1024 px wide, optimised
    PRINT = "print"           # full resolution
    ORIGINAL = "original"     # verbatim upload


class LicenseType(str, Enum):
    ROYALTY_FREE = "royalty_free"
    RIGHTS_MANAGED = "rights_managed"
    CREATIVE_COMMONS = "creative_commons"
    EDITORIAL = "editorial"


# ── Core Data Models ───────────────────────────────────────────────────


class Tag(BaseModel):
    id: str = Field(default_factory=lambda: f"tag-{uuid.uuid4().hex[:8]}")
    name: str
    color: str = "#6c757d"


class License(BaseModel):
    id: str = Field(default_factory=lambda: f"lic-{uuid.uuid4().hex[:8]}")
    type: LicenseType = LicenseType.ROYALTY_FREE
    holder: Optional[str] = None
    expiry_date: Optional[datetime] = None
    notes: Optional[str] = None


class Rendition(BaseModel):
    id: str = Field(default_factory=lambda: f"rnd-{uuid.uuid4().hex[:8]}")
    asset_id: str
    format: RenditionFormat = RenditionFormat.ORIGINAL
    width: Optional[int] = None
    height: Optional[int] = None
    mime_type: str = "image/jpeg"
    s3_key: str = ""
    size_bytes: int = 0


class Asset(BaseModel):
    id: str = Field(default_factory=lambda: f"AST-{uuid.uuid4().hex[:8].upper()}")
    filename: str
    original_filename: str
    asset_type: AssetType = AssetType.IMAGE
    status: AssetStatus = AssetStatus.ACTIVE
    tags: list[str] = []
    collection_ids: list[str] = []
    metadata: dict[str, Any] = {}
    s3_key: str = ""
    s3_bucket: str = "dam-assets"
    size_bytes: int = 0
    mime_type: str = "application/octet-stream"
    description: Optional[str] = None
    copyright: Optional[str] = None
    license: Optional[License] = None
    renditions: list[Rendition] = []
    created: datetime = Field(default_factory=datetime.utcnow)
    updated: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = "system"


class AssetCollection(BaseModel):
    id: str = Field(default_factory=lambda: f"COL-{uuid.uuid4().hex[:8].upper()}")
    name: str
    description: Optional[str] = None
    asset_ids: list[str] = []
    created: datetime = Field(default_factory=datetime.utcnow)
    updated: datetime = Field(default_factory=datetime.utcnow)


# ── Request / Response Models ──────────────────────────────────────────


class AssetUpdateRequest(BaseModel):
    tags: Optional[list[str]] = None
    collection_ids: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None
    description: Optional[str] = Field(None, max_length=2000)
    copyright: Optional[str] = Field(None, max_length=500)
    status: Optional[AssetStatus] = None


class CollectionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    asset_ids: list[str] = []


class CollectionUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    asset_ids: Optional[list[str]] = None


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
    pages: int


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None
