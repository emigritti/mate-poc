"""
Catalog Generator — Façade over integration-agent
ADR-013 (principle): no own database — delegates to integration-agent.
ADR-012: async-first (httpx.AsyncClient for upstream calls).

Port: 3004

This service is a thin composition layer.  It shapes requests from
catalog-domain callers into the integration-agent's REST contract,
then forwards responses back.  No generation logic lives here.

Endpoints:
  POST /api/v1/catalog/generate          — kick off a generation job
  GET  /api/v1/catalog/{job_id}/status   — poll job status
  GET  /api/v1/catalog/jobs              — list recent jobs (proxied)
  GET  /health                           — liveness probe
"""

import os
import logging
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("catalog-generator")

# ── Config ─────────────────────────────────────────────────────────────

_AGENT_BASE_URL: str = os.environ.get(
    "AGENT_BASE_URL", "http://mate-integration-agent:3003"
)
_AGENT_API_KEY: str = os.environ.get("AGENT_API_KEY", "")
_HTTP_TIMEOUT: float = float(os.environ.get("AGENT_TIMEOUT_SECONDS", "30"))

_CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:8080,http://localhost:3000").split(",")
    if o.strip()
]


# ── Pydantic Models ────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    """Request body for catalog generation."""
    source_system: str = Field(
        min_length=1, max_length=100,
        examples=["PLM"],
        description="Source system identifier (e.g. PLM, SAP-ERP)",
    )
    target_system: str = Field(
        min_length=1, max_length=100,
        examples=["PIM"],
        description="Target system identifier (e.g. PIM, DAM)",
    )
    requirements: list[dict] = Field(
        default=[],
        description="List of requirement dicts [{ReqID, Source, Target, Category, Description}]",
    )
    priority: Optional[str] = Field(
        None,
        description="Optional priority label forwarded as metadata (HIGH, MEDIUM, LOW)",
    )


class GenerateResponse(BaseModel):
    status: str
    job_id: Optional[str] = None
    message: str


# ── HTTP client factory ────────────────────────────────────────────────

def _make_headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if _AGENT_API_KEY:
        h["Authorization"] = f"Bearer {_AGENT_API_KEY}"
    return h


# ── Lifespan ───────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.warning(
        "Catalog Generator — upstream agent: %s", _AGENT_BASE_URL
    )
    yield
    logger.warning("Catalog Generator — shutting down")


# ── App ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Catalog Generator",
    description=(
        "Façade service that composes integration-agent calls into a "
        "catalog-domain API.  No own database — delegates all generation "
        "and state management to the integration-agent."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Endpoints ──────────────────────────────────────────────────────────

@app.post("/api/v1/catalog/generate", response_model=GenerateResponse, tags=["Catalog"])
async def generate_catalog(body: GenerateRequest):
    """
    Trigger a catalog generation job.

    Forwards the request to the integration-agent's /api/v1/agent/run
    endpoint after shaping the payload.  Returns the job identifier
    that callers can use to poll /api/v1/catalog/{job_id}/status.
    """
    # Shape the payload for the integration-agent contract
    agent_payload = {
        "source_system": body.source_system,
        "target_system": body.target_system,
        "requirements": body.requirements,
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{_AGENT_BASE_URL}/api/v1/agent/run",
                json=agent_payload,
                headers=_make_headers(),
            )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Cannot reach integration-agent. "
                f"Configured upstream: {_AGENT_BASE_URL}"
            ),
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Integration-agent timed out.",
        )

    if resp.status_code == 409:
        raise HTTPException(
            status_code=409,
            detail="A generation job is already running. Retry after it completes.",
        )

    if resp.status_code not in (200, 201, 202):
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Integration-agent returned: {resp.text[:500]}",
        )

    data = resp.json()
    return GenerateResponse(
        status=data.get("status", "accepted"),
        job_id=data.get("job_id"),
        message=data.get("message", "Generation job accepted"),
    )


@app.get("/api/v1/catalog/{job_id}/status", tags=["Catalog"])
async def get_job_status(job_id: str):
    """
    Poll the status of a catalog generation job.

    Proxies to the integration-agent's approval catalogue endpoint
    and returns the current document state.
    """
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{_AGENT_BASE_URL}/api/v1/approvals/{job_id}",
                headers=_make_headers(),
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Cannot reach integration-agent.")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Integration-agent timed out.")

    if resp.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id!r} not found in integration-agent.",
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Upstream error: {resp.text[:500]}",
        )

    return resp.json()


@app.get("/api/v1/catalog/jobs", tags=["Catalog"])
async def list_jobs():
    """
    List recent catalog generation jobs.

    Proxies to the integration-agent's document catalogue endpoint.
    """
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{_AGENT_BASE_URL}/api/v1/documents",
                headers=_make_headers(),
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Cannot reach integration-agent.")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Integration-agent timed out.")

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])

    return resp.json()


@app.get("/health", tags=["System"])
async def health_check():
    """
    Liveness probe.  Pings the upstream integration-agent /health endpoint
    to report reachability.
    """
    agent_reachable = False
    agent_status = "unknown"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_AGENT_BASE_URL}/health")
            agent_reachable = resp.status_code == 200
            agent_status = resp.json().get("status", "unknown") if agent_reachable else "unreachable"
    except Exception:
        agent_status = "unreachable"

    return {
        "status": "healthy",
        "service": "catalog-generator",
        "port": 3004,
        "upstream_agent": _AGENT_BASE_URL,
        "agent_reachable": agent_reachable,
        "agent_status": agent_status,
    }
