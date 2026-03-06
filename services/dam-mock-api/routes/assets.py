"""
DAM Mock API — Asset & Collection Routes
ADR-016 / CLAUDE.md §7: Input validation on every mutating endpoint.

In-memory stores simulate the DAM database.
Pagination, tag filtering, and presigned-URL generation follow
the same conventions as the PLM/PIM mock services.
"""

import math
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse

from models import (
    Asset,
    AssetCollection,
    AssetStatus,
    AssetType,
    AssetUpdateRequest,
    CollectionCreateRequest,
    CollectionUpdateRequest,
    License,
    LicenseType,
    PaginatedResponse,
    Rendition,
    RenditionFormat,
    Tag,
)

router = APIRouter(prefix="/api/v1")

# ── In-memory stores ───────────────────────────────────────────────────
_assets: dict[str, Asset] = {}
_collections: dict[str, AssetCollection] = {}
_tags: dict[str, Tag] = {}

# ── Helpers ────────────────────────────────────────────────────────────

_ALLOWED_MIME_PREFIXES = ("image/", "video/", "audio/", "application/pdf",
                          "application/msword",
                          "application/vnd.openxmlformats")
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


def _paginate(items: list, page: int, page_size: int) -> PaginatedResponse:
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return PaginatedResponse(
        items=items[start:end],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


def _infer_asset_type(mime_type: str) -> AssetType:
    if mime_type.startswith("image/"):
        return AssetType.IMAGE
    if mime_type.startswith("video/"):
        return AssetType.VIDEO
    if mime_type.startswith("audio/"):
        return AssetType.AUDIO
    if "pdf" in mime_type or "word" in mime_type or "openxmlformats" in mime_type:
        return AssetType.DOCUMENT
    return AssetType.OTHER


# ── Seed function (called from main.py lifespan) ───────────────────────

def seed_sample_data() -> None:
    """Populate in-memory stores with sample DAM assets and collections."""
    # Tags
    for name, color in [
        ("hero-image", "#e74c3c"),
        ("product-shot", "#3498db"),
        ("lifestyle", "#2ecc71"),
        ("print-ready", "#9b59b6"),
        ("web-optimised", "#f39c12"),
    ]:
        t = Tag(name=name, color=color)
        _tags[t.id] = t

    tag_ids = list(_tags.keys())

    # Sample assets
    sample_assets = [
        {
            "filename": "hero-banner-2024.jpg",
            "original_filename": "hero-banner-2024.jpg",
            "asset_type": AssetType.IMAGE,
            "mime_type": "image/jpeg",
            "size_bytes": 2_456_789,
            "description": "Main hero banner for 2024 campaign",
            "tags": [tag_ids[0], tag_ids[2]],
            "copyright": "© Accenture PoC 2024",
            "s3_key": "hero-banner-2024.jpg",
            "s3_bucket": "dam-assets",
            "license": License(type=LicenseType.ROYALTY_FREE, holder="PoC Demo"),
        },
        {
            "filename": "product-alpha-front.png",
            "original_filename": "product-alpha-front.png",
            "asset_type": AssetType.IMAGE,
            "mime_type": "image/png",
            "size_bytes": 987_654,
            "description": "Front view of Product Alpha (white background)",
            "tags": [tag_ids[1], tag_ids[4]],
            "copyright": "© Accenture PoC 2024",
            "s3_key": "product-alpha-front.png",
            "s3_bucket": "dam-assets",
        },
        {
            "filename": "product-alpha-side.png",
            "original_filename": "product-alpha-side.png",
            "asset_type": AssetType.IMAGE,
            "mime_type": "image/png",
            "size_bytes": 1_023_456,
            "description": "Side view of Product Alpha",
            "tags": [tag_ids[1], tag_ids[3]],
            "copyright": "© Accenture PoC 2024",
            "s3_key": "product-alpha-side.png",
            "s3_bucket": "dam-assets",
        },
        {
            "filename": "campaign-video-q4.mp4",
            "original_filename": "campaign-video-q4.mp4",
            "asset_type": AssetType.VIDEO,
            "mime_type": "video/mp4",
            "size_bytes": 48_234_567,
            "description": "Q4 campaign video — 30 second cut",
            "tags": [tag_ids[0], tag_ids[2]],
            "s3_key": "campaign-video-q4.mp4",
            "s3_bucket": "dam-assets",
        },
        {
            "filename": "brand-guidelines-v3.pdf",
            "original_filename": "brand-guidelines-v3.pdf",
            "asset_type": AssetType.DOCUMENT,
            "mime_type": "application/pdf",
            "size_bytes": 5_678_901,
            "description": "Corporate brand guidelines revision 3",
            "tags": [tag_ids[3]],
            "s3_key": "brand-guidelines-v3.pdf",
            "s3_bucket": "dam-assets",
        },
    ]

    for data in sample_assets:
        a = Asset(**data)
        # Attach mock renditions for image assets
        if a.asset_type == AssetType.IMAGE:
            for fmt, w, h in [
                (RenditionFormat.THUMBNAIL, 200, 200),
                (RenditionFormat.WEB, 1024, None),
                (RenditionFormat.ORIGINAL, None, None),
            ]:
                rnd = Rendition(
                    asset_id=a.id,
                    format=fmt,
                    width=w,
                    height=h,
                    mime_type=a.mime_type,
                    s3_key=f"{fmt.value}-{a.s3_key}",
                    size_bytes=a.size_bytes // (10 if fmt == RenditionFormat.THUMBNAIL else 1),
                )
                a.renditions.append(rnd)
        _assets[a.id] = a

    # Collections
    all_ids = list(_assets.keys())
    for name, desc, ids_slice in [
        ("Product Visuals", "All product photography", all_ids[:3]),
        ("Campaign 2024", "Assets for 2024 marketing campaign", [all_ids[0], all_ids[3]]),
        ("Brand Library", "Brand identity assets", [all_ids[4]]),
    ]:
        c = AssetCollection(name=name, description=desc, asset_ids=ids_slice)
        _collections[c.id] = c


# ── Asset Endpoints ────────────────────────────────────────────────────


@router.get("/assets", response_model=PaginatedResponse, tags=["Assets"])
async def list_assets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    asset_type: Optional[AssetType] = None,
    status: Optional[AssetStatus] = None,
    tag_id: Optional[str] = None,
    collection_id: Optional[str] = None,
    q: Optional[str] = None,
):
    """List assets with optional filtering by type, status, tag, collection, or keyword."""
    items = list(_assets.values())

    if asset_type:
        items = [a for a in items if a.asset_type == asset_type]
    if status:
        items = [a for a in items if a.status == status]
    else:
        items = [a for a in items if a.status != AssetStatus.ARCHIVED]
    if tag_id:
        items = [a for a in items if tag_id in a.tags]
    if collection_id:
        items = [a for a in items if collection_id in a.collection_ids]
    if q:
        q_lower = q.lower()
        items = [
            a for a in items
            if q_lower in a.filename.lower() or q_lower in (a.description or "").lower()
        ]

    items.sort(key=lambda a: a.created, reverse=True)
    return _paginate(items, page, page_size)


@router.get("/assets/{asset_id}", tags=["Assets"])
async def get_asset(asset_id: str):
    """Retrieve a single asset with all metadata and rendition info."""
    asset = _assets.get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id!r} not found")
    return asset


@router.post("/assets/upload", status_code=201, tags=["Assets"])
async def upload_asset(
    file: UploadFile = File(...),
    description: Optional[str] = None,
    copyright: Optional[str] = None,
):
    """
    Upload a new asset (image, video, document, etc.).
    Max 20 MB. MIME type must be an allowed media type.
    """
    # MIME validation
    mime = file.content_type or ""
    if not any(mime.startswith(prefix) for prefix in _ALLOWED_MIME_PREFIXES):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported media type: {mime!r}. Allowed: image/*, video/*, audio/*, PDF, Word.",
        )

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {len(content)} bytes (max {_MAX_UPLOAD_BYTES}).",
        )

    safe_filename = f"{uuid.uuid4().hex[:8]}-{file.filename}"
    asset = Asset(
        filename=safe_filename,
        original_filename=file.filename or "unknown",
        asset_type=_infer_asset_type(mime),
        mime_type=mime,
        size_bytes=len(content),
        description=description,
        copyright=copyright,
        s3_key=safe_filename,
        s3_bucket="dam-assets",
    )

    # Attach mock renditions for image uploads
    if asset.asset_type == AssetType.IMAGE:
        for fmt in [RenditionFormat.THUMBNAIL, RenditionFormat.WEB, RenditionFormat.ORIGINAL]:
            rnd = Rendition(
                asset_id=asset.id,
                format=fmt,
                mime_type=mime,
                s3_key=f"{fmt.value}-{safe_filename}",
                size_bytes=len(content),
            )
            asset.renditions.append(rnd)

    _assets[asset.id] = asset
    return {"status": "uploaded", "asset_id": asset.id, "filename": asset.filename}


@router.patch("/assets/{asset_id}", tags=["Assets"])
async def update_asset(asset_id: str, body: AssetUpdateRequest):
    """Update asset metadata (tags, collections, description, copyright, status)."""
    asset = _assets.get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id!r} not found")

    if body.tags is not None:
        asset.tags = body.tags
    if body.collection_ids is not None:
        asset.collection_ids = body.collection_ids
    if body.metadata is not None:
        asset.metadata.update(body.metadata)
    if body.description is not None:
        asset.description = body.description
    if body.copyright is not None:
        asset.copyright = body.copyright
    if body.status is not None:
        asset.status = body.status

    asset.updated = datetime.utcnow()
    return asset


@router.delete("/assets/{asset_id}", tags=["Assets"])
async def archive_asset(asset_id: str):
    """Soft-delete (archive) an asset. The record is kept; status changes to ARCHIVED."""
    asset = _assets.get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id!r} not found")
    asset.status = AssetStatus.ARCHIVED
    asset.updated = datetime.utcnow()
    return {"status": "archived", "asset_id": asset_id}


@router.get("/assets/{asset_id}/renditions", tags=["Assets"])
async def list_renditions(asset_id: str):
    """List all renditions for an asset."""
    asset = _assets.get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id!r} not found")
    return {"asset_id": asset_id, "renditions": asset.renditions}


@router.get("/assets/{asset_id}/download-url", tags=["Assets"])
async def get_download_url(
    asset_id: str,
    rendition: Optional[RenditionFormat] = RenditionFormat.ORIGINAL,
    expires_in: int = Query(900, ge=60, le=86400),
):
    """
    Return a (simulated) presigned download URL for an asset or specific rendition.
    In the PoC, returns a mock URL — in production this would call S3.
    """
    asset = _assets.get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id!r} not found")

    # Simulate a presigned URL (no real S3 in PoC unit tests)
    mock_url = (
        f"http://mate-minio:9000/dam-assets/"
        f"{rendition.value if rendition else 'original'}-{asset.s3_key}"
        f"?X-Amz-Expires={expires_in}&X-Amz-Signature=mock"
    )
    return {"asset_id": asset_id, "rendition": rendition, "url": mock_url, "expires_in": expires_in}


# ── Collection Endpoints ───────────────────────────────────────────────


@router.get("/collections", tags=["Collections"])
async def list_collections(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List all asset collections."""
    items = sorted(_collections.values(), key=lambda c: c.created, reverse=True)
    return _paginate(list(items), page, page_size)


@router.post("/collections", status_code=201, tags=["Collections"])
async def create_collection(body: CollectionCreateRequest):
    """Create a new asset collection."""
    # Validate that all referenced asset IDs exist
    missing = [aid for aid in body.asset_ids if aid not in _assets]
    if missing:
        raise HTTPException(
            status_code=422, detail=f"Unknown asset IDs: {missing}"
        )
    col = AssetCollection(
        name=body.name,
        description=body.description,
        asset_ids=list(body.asset_ids),
    )
    _collections[col.id] = col
    # Update back-references on assets
    for aid in col.asset_ids:
        if col.id not in _assets[aid].collection_ids:
            _assets[aid].collection_ids.append(col.id)
    return col


@router.get("/collections/{collection_id}", tags=["Collections"])
async def get_collection(collection_id: str):
    """Retrieve a collection with full asset details."""
    col = _collections.get(collection_id)
    if not col:
        raise HTTPException(status_code=404, detail=f"Collection {collection_id!r} not found")
    assets = [_assets[aid] for aid in col.asset_ids if aid in _assets]
    return {**col.model_dump(), "assets": assets}


@router.patch("/collections/{collection_id}", tags=["Collections"])
async def update_collection(collection_id: str, body: CollectionUpdateRequest):
    """Update collection name, description, or asset membership."""
    col = _collections.get(collection_id)
    if not col:
        raise HTTPException(status_code=404, detail=f"Collection {collection_id!r} not found")

    if body.name is not None:
        col.name = body.name
    if body.description is not None:
        col.description = body.description
    if body.asset_ids is not None:
        missing = [aid for aid in body.asset_ids if aid not in _assets]
        if missing:
            raise HTTPException(status_code=422, detail=f"Unknown asset IDs: {missing}")
        col.asset_ids = list(body.asset_ids)

    col.updated = datetime.utcnow()
    return col


# ── Tag Endpoints ──────────────────────────────────────────────────────


@router.get("/tags", tags=["Tags"])
async def list_tags():
    """List all available asset tags."""
    return {"tags": list(_tags.values()), "total": len(_tags)}
