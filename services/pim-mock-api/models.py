"""
PIM Mock API — Pydantic Models (Akeneo-style)
Simulates an Akeneo-compatible Product Information Management system.
"""

from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
import uuid


# ── Core Data Models ──

class AttributeGroup(BaseModel):
    code: str
    label_en: str
    sort_order: int = 0


class Attribute(BaseModel):
    code: str
    type: str = "text"  # text|number|boolean|price|media|select
    group: str = "general"
    localizable: bool = False
    scopable: bool = False
    allowed_extensions: list[str] = []
    label_en: Optional[str] = None


class Family(BaseModel):
    code: str
    label_en: str
    label_it: Optional[str] = None
    attributes: list[str] = []
    attribute_as_label: str = "name"


class Category(BaseModel):
    code: str
    parent: Optional[str] = None
    label_en: str
    label_it: Optional[str] = None


class ProductValue(BaseModel):
    locale: Optional[str] = None
    scope: Optional[str] = None
    data: Any = None


class MediaFile(BaseModel):
    code: str = Field(default_factory=lambda: f"media-{uuid.uuid4().hex[:8]}")
    original_filename: str
    mime_type: str = "image/jpeg"
    size: int = 0
    s3_key: str = ""


class PIMProduct(BaseModel):
    identifier: str
    family: Optional[str] = None
    enabled: bool = True
    categories: list[str] = []
    values: dict[str, list[ProductValue]] = {}
    media: list[str] = []
    created: datetime = Field(default_factory=datetime.utcnow)
    updated: datetime = Field(default_factory=datetime.utcnow)


class Channel(BaseModel):
    code: str
    label: str
    locales: list[str]
    currencies: list[str]
    category_tree: str


class Locale(BaseModel):
    code: str
    label: str
    enabled: bool = True


# ── Request Models ──

class ProductCreateRequest(BaseModel):
    identifier: str
    family: Optional[str] = None
    enabled: bool = True
    categories: list[str] = []
    values: dict[str, list[ProductValue]] = {}


class ProductUpdateRequest(BaseModel):
    family: Optional[str] = None
    enabled: Optional[bool] = None
    categories: Optional[list[str]] = None
    values: Optional[dict[str, list[ProductValue]]] = None
