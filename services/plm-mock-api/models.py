"""
PLM Mock API — Pydantic Models
Simulates a Product Lifecycle Management system.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum
import uuid


class ProductStatus(str, Enum):
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    PUBLISHED = "PUBLISHED"
    OBSOLETE = "OBSOLETE"


class ChangeSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ChangeStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    IMPLEMENTED = "IMPLEMENTED"


# ── Request Models ──

class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    status: ProductStatus = ProductStatus.DRAFT
    category: Optional[str] = None
    weight: Optional[float] = None
    weight_unit: Optional[str] = "kg"
    tags: list[str] = []


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ProductStatus] = None
    category: Optional[str] = None
    weight: Optional[float] = None
    weight_unit: Optional[str] = None
    tags: Optional[list[str]] = None


# ── Data Models ──

class Material(BaseModel):
    id: str = Field(default_factory=lambda: f"mat-{uuid.uuid4().hex[:8]}")
    code: str
    name: str
    type: str
    supplier: str
    unit_cost: float
    currency: str = "EUR"


class BOMItem(BaseModel):
    id: str = Field(default_factory=lambda: f"bom-{uuid.uuid4().hex[:8]}")
    product_id: str
    material_id: str
    quantity: int
    unit: str = "pcs"
    level: int = 1


class ProductImage(BaseModel):
    id: str = Field(default_factory=lambda: f"img-{uuid.uuid4().hex[:8]}")
    product_id: str
    filename: str
    s3_bucket: str = "plm-assets"
    s3_key: str
    mime_type: str = "image/jpeg"
    size_bytes: int = 0


class EngineeringChange(BaseModel):
    id: str = Field(default_factory=lambda: f"ec-{uuid.uuid4().hex[:8]}")
    product_id: str
    title: str
    description: str
    severity: ChangeSeverity = ChangeSeverity.MEDIUM
    status: ChangeStatus = ChangeStatus.OPEN
    effective_date: Optional[datetime] = None


class Product(BaseModel):
    id: str = Field(default_factory=lambda: f"prod-{uuid.uuid4().hex[:8]}")
    sku: str
    name: str
    description: Optional[str] = None
    status: ProductStatus = ProductStatus.DRAFT
    category: Optional[str] = None
    weight: Optional[float] = None
    weight_unit: Optional[str] = "kg"
    tags: list[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Response Models ──

class PaginatedResponse(BaseModel):
    status: str = "success"
    data: list
    meta: dict


class ErrorResponse(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
