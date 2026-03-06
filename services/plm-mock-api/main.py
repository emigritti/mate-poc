"""
PLM Mock API — FastAPI Application
Simulates a Product Lifecycle Management system (port 3001).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import os

from routes.products import router as products_router, products, bom_items, images, materials, engineering_changes
from models import (
    Product, ProductStatus, Material, BOMItem, ProductImage,
    EngineeringChange, ChangeSeverity, ChangeStatus
)

app = FastAPI(
    title="PLM Mock API",
    description="Product Lifecycle Management — Mock API for Integration Mate PoC",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products_router)


@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": "plm-mock-api",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "1.0.0",
        "counters": {
            "products": len(products),
            "materials": len(materials),
            "engineering_changes": len(engineering_changes),
        },
    }


@app.get("/api/v1/openapi-spec", tags=["System"])
async def get_openapi():
    """Return the OpenAPI spec for this service (used by catalog generator)."""
    return app.openapi()


@app.on_event("startup")
async def load_sample_data():
    """Populate in-memory store with realistic sample data."""

    # ── Materials ──
    sample_materials = [
        Material(id="mat-001", code="ALU-6061", name="Aluminum 6061-T6", type="metal", supplier="MetalCorp", unit_cost=12.50),
        Material(id="mat-002", code="PCB-FR4", name="FR4 PCB Board", type="electronic", supplier="CircuitPro", unit_cost=8.30),
        Material(id="mat-003", code="LCD-55", name="55-inch LCD Panel", type="display", supplier="DisplayTech", unit_cost=285.00),
        Material(id="mat-004", code="PS-500W", name="500W Power Supply", type="electronic", supplier="PowerMax", unit_cost=42.00),
        Material(id="mat-005", code="GLASS-T", name="Tempered Glass Front", type="glass", supplier="GlassPro", unit_cost=18.75),
    ]
    for m in sample_materials:
        materials[m.id] = m

    # ── Products ──
    sample_products = [
        Product(
            id="prod-001", sku="PLM-TV-55PRO", name="Smart TV 55 Pro",
            description="Premium 55-inch 4K Smart TV with HDR10+ and Dolby Vision. AI-powered upscaling engine.",
            status=ProductStatus.PUBLISHED, category="Electronics/TV",
            weight=15.5, weight_unit="kg", tags=["smart-tv", "4k", "hdr", "premium"],
        ),
        Product(
            id="prod-002", sku="PLM-TV-43STD", name="Smart TV 43 Standard",
            description="43-inch Full HD Smart TV with built-in streaming apps. Perfect for bedrooms and offices.",
            status=ProductStatus.PUBLISHED, category="Electronics/TV",
            weight=9.2, weight_unit="kg", tags=["smart-tv", "full-hd", "standard"],
        ),
        Product(
            id="prod-003", sku="PLM-SB-300", name="Soundbar 300",
            description="2.1 Channel Soundbar with wireless subwoofer. Bluetooth 5.0 and HDMI ARC.",
            status=ProductStatus.REVIEW, category="Electronics/Audio",
            weight=3.8, weight_unit="kg", tags=["audio", "soundbar", "bluetooth"],
        ),
        Product(
            id="prod-004", sku="PLM-WC-4K", name="Webcam 4K Ultra",
            description="Professional 4K webcam with auto-focus, noise-canceling microphone, and privacy shutter.",
            status=ProductStatus.DRAFT, category="Electronics/Peripherals",
            weight=0.18, weight_unit="kg", tags=["webcam", "4k", "professional"],
        ),
        Product(
            id="prod-005", sku="PLM-MON-27", name="Monitor 27 QHD",
            description="27-inch QHD IPS monitor with USB-C hub. 95% DCI-P3 color accuracy for creative professionals.",
            status=ProductStatus.PUBLISHED, category="Electronics/Monitors",
            weight=6.5, weight_unit="kg", tags=["monitor", "qhd", "usb-c", "creative"],
        ),
    ]
    for p in sample_products:
        products[p.id] = p
        bom_items[p.id] = []
        images[p.id] = []

    # ── BOM Items ──
    bom_items["prod-001"] = [
        BOMItem(product_id="prod-001", material_id="mat-003", quantity=1, unit="pcs", level=1),
        BOMItem(product_id="prod-001", material_id="mat-001", quantity=1, unit="pcs", level=1),
        BOMItem(product_id="prod-001", material_id="mat-002", quantity=2, unit="pcs", level=2),
        BOMItem(product_id="prod-001", material_id="mat-004", quantity=1, unit="pcs", level=2),
        BOMItem(product_id="prod-001", material_id="mat-005", quantity=1, unit="pcs", level=1),
    ]

    # ── Engineering Changes ──
    engineering_changes.extend([
        EngineeringChange(
            id="ec-001", product_id="prod-001",
            title="HDR10+ Firmware Update", description="Update display firmware to support HDR10+ dynamic metadata.",
            severity=ChangeSeverity.MEDIUM, status=ChangeStatus.APPROVED,
            effective_date=datetime(2026, 4, 1),
        ),
        EngineeringChange(
            id="ec-002", product_id="prod-003",
            title="Bluetooth Codec Upgrade", description="Add LDAC and aptX HD codec support to Soundbar 300.",
            severity=ChangeSeverity.LOW, status=ChangeStatus.IN_REVIEW,
        ),
        EngineeringChange(
            id="ec-003", product_id="prod-001",
            title="Power Supply Safety Recall", description="Replace PS-500W with PS-500W-V2 due to overheat risk in tropical climates.",
            severity=ChangeSeverity.CRITICAL, status=ChangeStatus.OPEN,
        ),
    ])

    print(f"✅ PLM Mock loaded: {len(products)} products, {len(materials)} materials, {len(engineering_changes)} engineering changes")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)
