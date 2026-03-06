"""
PIM Mock API — Product Routes (Akeneo-style)
Full CRUD for products, families, attributes, categories, channels, locales, media.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from typing import Optional
from datetime import datetime

from models import (
    PIMProduct, ProductCreateRequest, ProductUpdateRequest,
    Family, Attribute, AttributeGroup, Category, Channel, Locale,
    MediaFile, ProductValue,
)
from s3_client import upload_asset, get_presigned_url

router = APIRouter(prefix="/api/v1", tags=["PIM"])

# ── In-Memory Stores ─────────────────────────────────────

pim_products: dict[str, PIMProduct] = {}
families: dict[str, Family] = {}
attributes: dict[str, Attribute] = {}
attribute_groups: dict[str, AttributeGroup] = {}
categories: dict[str, Category] = {}
channels: dict[str, Channel] = {}
locales: dict[str, Locale] = {}
media_files: dict[str, MediaFile] = {}


def _paginate(items: list, page: int, limit: int) -> dict:
    start = (page - 1) * limit
    end = start + limit
    return {
        "status": "success",
        "data": items[start:end],
        "meta": {"page": page, "limit": limit, "total": len(items), "timestamp": datetime.utcnow().isoformat() + "Z"},
    }


# ── Products ─────────────────────────────────────────────

@router.get("/products")
async def list_products(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), family: Optional[str] = None, enabled: Optional[bool] = None):
    items = list(pim_products.values())
    if family:
        items = [p for p in items if p.family == family]
    if enabled is not None:
        items = [p for p in items if p.enabled == enabled]
    return _paginate([p.model_dump() for p in items], page, limit)


@router.post("/products", status_code=201)
async def create_product(body: ProductCreateRequest):
    if body.identifier in pim_products:
        raise HTTPException(status_code=409, detail={"type": "https://integration-mate.local/errors/conflict", "title": "Duplicate Product", "status": 409, "detail": f"Product '{body.identifier}' already exists"})
    product = PIMProduct(**body.model_dump())
    pim_products[product.identifier] = product
    return {"status": "success", "data": product.model_dump()}


@router.get("/products/{identifier}")
async def get_product(identifier: str):
    if identifier not in pim_products:
        raise HTTPException(status_code=404, detail={"type": "https://integration-mate.local/errors/not-found", "title": "Product Not Found", "status": 404, "detail": f"Product '{identifier}' not found"})
    return {"status": "success", "data": pim_products[identifier].model_dump()}


@router.patch("/products/{identifier}")
async def update_product(identifier: str, body: ProductUpdateRequest):
    if identifier not in pim_products:
        raise HTTPException(status_code=404, detail=f"Product '{identifier}' not found")
    product = pim_products[identifier]
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if field == "values" and value:
            product.values.update(value)
        else:
            setattr(product, field, value)
    product.updated = datetime.utcnow()
    return {"status": "success", "data": product.model_dump()}


@router.delete("/products/{identifier}", status_code=204)
async def delete_product(identifier: str):
    if identifier not in pim_products:
        raise HTTPException(status_code=404, detail=f"Product '{identifier}' not found")
    del pim_products[identifier]


# ── Families ─────────────────────────────────────────────

@router.get("/families")
async def list_families(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)):
    return _paginate([f.model_dump() for f in families.values()], page, limit)


@router.post("/families", status_code=201)
async def create_family(body: Family):
    families[body.code] = body
    return {"status": "success", "data": body.model_dump()}


# ── Attributes ───────────────────────────────────────────

@router.get("/attributes")
async def list_attributes(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)):
    return _paginate([a.model_dump() for a in attributes.values()], page, limit)


@router.post("/attributes", status_code=201)
async def create_attribute(body: Attribute):
    attributes[body.code] = body
    return {"status": "success", "data": body.model_dump()}


# ── Attribute Groups ─────────────────────────────────────

@router.get("/attribute-groups")
async def list_attribute_groups():
    return {"status": "success", "data": [ag.model_dump() for ag in attribute_groups.values()]}


# ── Categories ───────────────────────────────────────────

@router.get("/categories")
async def list_categories(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)):
    return _paginate([c.model_dump() for c in categories.values()], page, limit)


@router.post("/categories", status_code=201)
async def create_category(body: Category):
    categories[body.code] = body
    return {"status": "success", "data": body.model_dump()}


# ── Channels ─────────────────────────────────────────────

@router.get("/channels")
async def list_channels():
    return {"status": "success", "data": [c.model_dump() for c in channels.values()]}


# ── Locales ──────────────────────────────────────────────

@router.get("/locales")
async def list_locales():
    return {"status": "success", "data": [l.model_dump() for l in locales.values()]}


# ── Media Files ──────────────────────────────────────────

@router.get("/media-files")
async def list_media(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)):
    return _paginate([m.model_dump() for m in media_files.values()], page, limit)


@router.post("/media-files", status_code=201)
async def upload_media(file: UploadFile = File(...)):
    file_data = await file.read()
    s3_key = f"products/media/{file.filename}"
    bucket = "pim-media"
    await upload_asset(bucket, s3_key, file_data, file.content_type or "image/jpeg")
    media = MediaFile(original_filename=file.filename, mime_type=file.content_type or "image/jpeg", size=len(file_data), s3_key=s3_key)
    media_files[media.code] = media
    return {"status": "success", "data": media.model_dump()}
