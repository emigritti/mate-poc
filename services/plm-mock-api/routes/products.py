"""
PLM Mock API — Product Routes
Full CRUD for products, BOM, images, materials, engineering changes.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from typing import Optional
from datetime import datetime

from models import (
    Product, ProductCreate, ProductUpdate, ProductImage,
    BOMItem, Material, EngineeringChange, ProductStatus
)
from s3_client import upload_asset, get_presigned_url, list_assets

router = APIRouter(prefix="/api/v1", tags=["PLM"])

# ── In-Memory Store ──────────────────────────────────────

products: dict[str, Product] = {}
bom_items: dict[str, list[BOMItem]] = {}
images: dict[str, list[ProductImage]] = {}
materials: dict[str, Material] = {}
engineering_changes: list[EngineeringChange] = []


def _paginate(items: list, page: int, limit: int) -> dict:
    start = (page - 1) * limit
    end = start + limit
    return {
        "status": "success",
        "data": items[start:end],
        "meta": {
            "page": page,
            "limit": limit,
            "total": len(items),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    }


# ── Products ─────────────────────────────────────────────

@router.get("/products")
async def list_products(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[ProductStatus] = None,
    category: Optional[str] = None,
):
    items = list(products.values())
    if status:
        items = [p for p in items if p.status == status]
    if category:
        items = [p for p in items if p.category == category]
    return _paginate([p.model_dump() for p in items], page, limit)


@router.get("/products/{product_id}")
async def get_product(product_id: str):
    if product_id not in products:
        raise HTTPException(
            status_code=404,
            detail={
                "type": "https://integration-mate.local/errors/not-found",
                "title": "Product Not Found",
                "status": 404,
                "detail": f"Product with ID '{product_id}' does not exist in PLM",
                "instance": f"/api/v1/products/{product_id}",
            },
        )
    return {"status": "success", "data": products[product_id].model_dump()}


@router.post("/products", status_code=201)
async def create_product(body: ProductCreate):
    # Check for duplicate SKU
    for p in products.values():
        if p.sku == body.sku:
            raise HTTPException(
                status_code=409,
                detail={
                    "type": "https://integration-mate.local/errors/conflict",
                    "title": "Duplicate SKU",
                    "status": 409,
                    "detail": f"Product with SKU '{body.sku}' already exists",
                },
            )
    product = Product(**body.model_dump())
    products[product.id] = product
    bom_items[product.id] = []
    images[product.id] = []
    return {"status": "success", "data": product.model_dump()}


@router.patch("/products/{product_id}")
async def update_product(product_id: str, body: ProductUpdate):
    if product_id not in products:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")
    product = products[product_id]
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(product, field, value)
    product.updated_at = datetime.utcnow()
    return {"status": "success", "data": product.model_dump()}


# ── BOM ──────────────────────────────────────────────────

@router.get("/products/{product_id}/bom")
async def get_product_bom(product_id: str):
    if product_id not in products:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")
    items = bom_items.get(product_id, [])
    return {
        "status": "success",
        "data": [item.model_dump() for item in items],
        "meta": {"product_id": product_id, "total": len(items)},
    }


# ── Images ───────────────────────────────────────────────

@router.get("/products/{product_id}/images")
async def get_product_images(product_id: str):
    if product_id not in products:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")
    imgs = images.get(product_id, [])
    result = []
    for img in imgs:
        url = await get_presigned_url(img.s3_bucket, img.s3_key)
        result.append({**img.model_dump(), "presigned_url": url})
    return {"status": "success", "data": result}


@router.post("/products/{product_id}/images", status_code=201)
async def upload_product_image(product_id: str, file: UploadFile = File(...)):
    if product_id not in products:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")
    file_data = await file.read()
    s3_key = f"products/{product_id}/{file.filename}"
    bucket = "plm-assets"
    await upload_asset(bucket, s3_key, file_data, file.content_type or "image/jpeg")
    img = ProductImage(
        product_id=product_id,
        filename=file.filename,
        s3_bucket=bucket,
        s3_key=s3_key,
        mime_type=file.content_type or "image/jpeg",
        size_bytes=len(file_data),
    )
    images.setdefault(product_id, []).append(img)
    return {"status": "success", "data": img.model_dump()}


# ── Materials ────────────────────────────────────────────

@router.get("/materials")
async def list_materials(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)):
    items = list(materials.values())
    return _paginate([m.model_dump() for m in items], page, limit)


# ── Engineering Changes ──────────────────────────────────

@router.get("/engineering-changes")
async def list_engineering_changes(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    product_id: Optional[str] = None,
):
    items = engineering_changes
    if product_id:
        items = [ec for ec in items if ec.product_id == product_id]
    return _paginate([ec.model_dump() for ec in items], page, limit)
