"""
DAM Mock API — FastAPI Application
Simulates a Bynder/Canto-style Digital Asset Management system.

Port: 3005
ADR-012 (async-first), ADR-016 (fail-fast config from env vars).

Endpoints:
  GET  /health               — liveness probe
  GET  /openapi-spec         — mock OpenAPI specification
  *    /api/v1/assets        — asset CRUD + upload + download URL
  *    /api/v1/collections   — collection management
  GET  /api/v1/tags          — tag catalogue
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.assets import router as assets_router, seed_sample_data

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("dam-mock-api")

_CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:8080,http://localhost:3000").split(",")
    if o.strip()
]


# ── Lifespan ───────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Seed sample data on startup."""
    logger.warning("DAM Mock API — seeding sample data")
    seed_sample_data()
    logger.warning("DAM Mock API — ready on port 3005")
    yield
    logger.warning("DAM Mock API — shutting down")


# ── App ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="DAM Mock API",
    description=(
        "Simulated Digital Asset Management system (Bynder/Canto-style). "
        "Provides asset CRUD, collection management, and presigned URL generation."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ADR-018: restrict methods/headers to what DAM endpoints actually need
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(assets_router)


# ── Health ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health_check():
    """Liveness probe — returns service status and S3 config presence."""
    s3_configured = all(
        os.environ.get(k) for k in ("S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY")
    )
    return {
        "status": "healthy",
        "service": "dam-mock-api",
        "port": 3005,
        "s3_configured": s3_configured,
    }


# ── OpenAPI Spec ───────────────────────────────────────────────────────

@app.get("/openapi-spec", tags=["System"])
async def openapi_spec():
    """Return a simplified OpenAPI-compatible description of this service."""
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "DAM Mock API",
            "version": "1.0.0",
            "description": "Digital Asset Management mock for integration testing",
        },
        "servers": [{"url": "http://mate-dam-mock:3005"}],
        "paths": {
            "/api/v1/assets": {
                "get": {"summary": "List assets with filtering and pagination"},
                "post": {"summary": "Upload a new asset (multipart/form-data)"},
            },
            "/api/v1/assets/{asset_id}": {
                "get": {"summary": "Retrieve asset details"},
                "patch": {"summary": "Update asset metadata"},
                "delete": {"summary": "Archive asset (soft delete)"},
            },
            "/api/v1/assets/{asset_id}/renditions": {
                "get": {"summary": "List renditions for an asset"},
            },
            "/api/v1/assets/{asset_id}/download-url": {
                "get": {"summary": "Get presigned download URL"},
            },
            "/api/v1/collections": {
                "get": {"summary": "List collections"},
                "post": {"summary": "Create collection"},
            },
            "/api/v1/tags": {
                "get": {"summary": "List all tags"},
            },
        },
    }
