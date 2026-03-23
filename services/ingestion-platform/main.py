"""
Ingestion Platform — FastAPI Application Entry Point

Exposes:
  - Source Registry CRUD  (/api/v1/sources)
  - Run status query      (/api/v1/runs)
  - Ingest triggers       (/api/v1/ingest)
  - Health check          (/health)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient

import state
from config import settings
from routers.sources import router as sources_router
from routers.ingest import router as ingest_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    client = AsyncIOMotorClient(settings.mongo_uri)
    db = client[settings.mongo_db]
    state.sources_col = db["sources"]
    state.runs_col = db["source_runs"]
    state.snapshots_col = db["source_snapshots"]
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────────
    client.close()


app = FastAPI(
    title="Ingestion Platform",
    description="Multi-source KB ingestion: OpenAPI, HTML, MCP collectors with n8n orchestration",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(sources_router)
app.include_router(ingest_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ingestion-platform"}
