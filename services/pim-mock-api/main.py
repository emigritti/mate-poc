"""
PIM Mock API — FastAPI Application
Simulates an Akeneo-compatible PIM system (port 3002).

ADR-018: CORS uses an explicit origin allowlist from CORS_ORIGINS env var
(not wildcard) so that allow_credentials=True is valid per the Fetch spec.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.products import (
    router as products_router, pim_products, families, attributes,
    attribute_groups, categories, channels, locales,
)
from models import (
    PIMProduct, Family, Attribute, AttributeGroup, Category,
    Channel, Locale, ProductValue,
)

# ADR-018: origin allowlist from env var; never wildcard + credentials
_CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:8080,http://localhost:3000").split(",")
    if o.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Seed sample data on startup (replaces deprecated @app.on_event)."""
    await _load_sample_data()
    yield


app = FastAPI(
    title="PIM Mock API",
    description="Product Information Management — Akeneo-style Mock API for Integration Mate PoC",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(products_router)


@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": "pim-mock-api",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "counters": {
            "products": len(pim_products),
            "families": len(families),
            "attributes": len(attributes),
            "categories": len(categories),
        },
    }


@app.get("/api/v1/openapi-spec", tags=["System"])
async def get_openapi():
    return app.openapi()


async def _load_sample_data():
    """Populate with Akeneo-style sample data."""

    # Attribute Groups
    for ag in [
        AttributeGroup(code="general", label_en="General", sort_order=1),
        AttributeGroup(code="marketing", label_en="Marketing", sort_order=2),
        AttributeGroup(code="technical", label_en="Technical", sort_order=3),
        AttributeGroup(code="media", label_en="Media", sort_order=4),
    ]:
        attribute_groups[ag.code] = ag

    # Attributes
    for attr in [
        Attribute(code="name", type="text", group="general", localizable=True, label_en="Product Name"),
        Attribute(code="description", type="text", group="marketing", localizable=True, scopable=True, label_en="Description"),
        Attribute(code="price", type="price", group="general", label_en="Price"),
        Attribute(code="weight", type="number", group="technical", label_en="Weight"),
        Attribute(code="color", type="select", group="general", label_en="Color"),
        Attribute(code="image", type="media", group="media", allowed_extensions=["jpg", "png", "webp"], label_en="Main Image"),
        Attribute(code="ean", type="text", group="technical", label_en="EAN/Barcode"),
    ]:
        attributes[attr.code] = attr

    # Families
    for fam in [
        Family(code="electronics", label_en="Electronics", label_it="Elettronica", attributes=["name", "description", "price", "weight", "image", "ean"], attribute_as_label="name"),
        Family(code="accessories", label_en="Accessories", label_it="Accessori", attributes=["name", "description", "price", "color", "image"], attribute_as_label="name"),
    ]:
        families[fam.code] = fam

    # Categories
    for cat in [
        Category(code="master", label_en="Master Catalog", label_it="Catalogo Master"),
        Category(code="electronics", parent="master", label_en="Electronics", label_it="Elettronica"),
        Category(code="televisions", parent="electronics", label_en="Televisions", label_it="Televisori"),
        Category(code="smart-tv", parent="televisions", label_en="Smart TV"),
        Category(code="audio", parent="electronics", label_en="Audio"),
        Category(code="monitors", parent="electronics", label_en="Monitors"),
        Category(code="accessories", parent="master", label_en="Accessories", label_it="Accessori"),
    ]:
        categories[cat.code] = cat

    # Channels
    channels["ecommerce"] = Channel(code="ecommerce", label="E-Commerce", locales=["en_US", "it_IT"], currencies=["EUR", "USD"], category_tree="master")
    channels["print"] = Channel(code="print", label="Print Catalog", locales=["it_IT"], currencies=["EUR"], category_tree="master")

    # Locales
    for loc in [
        Locale(code="en_US", label="English (US)"),
        Locale(code="it_IT", label="Italiano"),
        Locale(code="de_DE", label="Deutsch", enabled=False),
    ]:
        locales[loc.code] = loc

    # Sample Products
    pim_products["SKU-TV55PRO"] = PIMProduct(
        identifier="SKU-TV55PRO", family="electronics",
        categories=["televisions", "smart-tv"], enabled=True,
        values={
            "name": [
                ProductValue(locale="en_US", data="Smart TV 55 Pro"),
                ProductValue(locale="it_IT", data="Smart TV 55 Pro"),
            ],
            "description": [
                ProductValue(locale="en_US", scope="ecommerce", data="Premium 55-inch 4K Smart TV with HDR10+ and Dolby Vision."),
                ProductValue(locale="it_IT", scope="ecommerce", data="Smart TV 55 pollici 4K premium con HDR10+ e Dolby Vision."),
            ],
            "price": [ProductValue(data=[{"amount": 999.99, "currency": "EUR"}, {"amount": 1099.99, "currency": "USD"}])],
            "weight": [ProductValue(data={"amount": 15.5, "unit": "KILOGRAM"})],
        },
    )

    pim_products["SKU-SB300"] = PIMProduct(
        identifier="SKU-SB300", family="electronics",
        categories=["audio"], enabled=True,
        values={
            "name": [
                ProductValue(locale="en_US", data="Soundbar 300"),
                ProductValue(locale="it_IT", data="Soundbar 300"),
            ],
            "description": [
                ProductValue(locale="en_US", scope="ecommerce", data="2.1 Channel Soundbar with wireless subwoofer."),
            ],
            "price": [ProductValue(data=[{"amount": 249.99, "currency": "EUR"}])],
            "weight": [ProductValue(data={"amount": 3.8, "unit": "KILOGRAM"})],
        },
    )

    print(f"✅ PIM Mock loaded: {len(pim_products)} products, {len(families)} families, {len(attributes)} attributes, {len(categories)} categories")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3002)
