"""
Security Middleware — JWT issuance and validation service
ADR-016: Secrets from environment variables (no hardcoded values).
ADR-012: Async-first (FastAPI async endpoints).

Port: 3000

Endpoints:
  POST /auth/token      — issue a JWT for a known service
  GET  /auth/validate   — validate a Bearer token
  GET  /health          — liveness probe

Service API keys are configured via environment variables:
  JWT_SECRET            — HMAC signing secret (REQUIRED in production)
  JWT_EXPIRY_SECONDS    — token lifetime (default: 3600)
  API_KEY_{SERVICE}     — per-service API key (e.g. API_KEY_AGENT)

In PoC mode, weak dev-only defaults are accepted so the stack starts
without a mandatory .env file.  All defaults must be overridden in production.
"""

import os
import logging
import time
from datetime import datetime, timezone

import jwt
from fastapi import FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("security-middleware")

# ── Config ─────────────────────────────────────────────────────────────

_JWT_SECRET: str = os.environ.get("JWT_SECRET", "dev-only-change-in-production")
_JWT_ALGORITHM: str = "HS256"
_JWT_EXPIRY: int = int(os.environ.get("JWT_EXPIRY_SECONDS", "3600"))

# Known services and their API keys.
# In production each key must come from a secrets manager (Vault, AWS SM, etc.)
_SERVICE_KEYS: dict[str, str] = {
    "integration-agent": os.environ.get("API_KEY_AGENT", "agent-key-dev"),
    "catalog-generator": os.environ.get("API_KEY_CATALOG", "catalog-key-dev"),
    "plm-mock":          os.environ.get("API_KEY_PLM",     "plm-key-dev"),
    "pim-mock":          os.environ.get("API_KEY_PIM",     "pim-key-dev"),
    "dam-mock":          os.environ.get("API_KEY_DAM",     "dam-key-dev"),
}

if _JWT_SECRET == "dev-only-change-in-production":
    logger.warning(
        "JWT_SECRET is using the insecure dev default. "
        "Set JWT_SECRET env var before deploying to production."
    )

_security = HTTPBearer(auto_error=False)

_CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:8080,http://localhost:3000").split(",")
    if o.strip()
]


# ── Pydantic Models ────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    service_id: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=1, max_length=500)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ValidateResponse(BaseModel):
    valid: bool
    service_id: str | None = None
    issued_at: str | None = None
    expires_at: str | None = None
    error: str | None = None


# ── App ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Security Middleware",
    description="JWT issuance and validation for the Integration Mate PoC platform.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ADR-018: restrict methods/headers to what auth endpoints actually need
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── Helpers ────────────────────────────────────────────────────────────

def _issue_token(service_id: str) -> str:
    """Create a signed JWT for the given service_id."""
    now = int(time.time())
    payload = {
        "sub": service_id,
        "iat": now,
        "exp": now + _JWT_EXPIRY,
        "iss": "integration-mate-security",
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def _validate_token(token: str) -> dict:
    """Decode and validate a JWT. Raises jwt.InvalidTokenError on failure."""
    return jwt.decode(
        token,
        _JWT_SECRET,
        algorithms=[_JWT_ALGORITHM],
        options={"require": ["sub", "exp", "iat"]},
    )


# ── Endpoints ──────────────────────────────────────────────────────────

@app.post("/auth/token", response_model=TokenResponse, tags=["Auth"])
async def issue_token(body: TokenRequest):
    """
    Issue a JWT for a known service.

    The caller must provide a valid (service_id, api_key) pair.
    Returns a Bearer token valid for JWT_EXPIRY_SECONDS seconds.
    """
    expected_key = _SERVICE_KEYS.get(body.service_id)
    if not expected_key or body.api_key != expected_key:
        # Constant-time-like response: avoid revealing which field is wrong
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = _issue_token(body.service_id)
    return TokenResponse(access_token=token, expires_in=_JWT_EXPIRY)


@app.get("/auth/validate", response_model=ValidateResponse, tags=["Auth"])
async def validate_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_security),
):
    """
    Validate a Bearer token passed in the Authorization header.

    Returns:
      valid=True  + claims if the token is authentic and not expired
      valid=False + error  if the token is missing, malformed, or expired
    """
    if not credentials:
        return ValidateResponse(valid=False, error="Missing Authorization header")

    try:
        claims = _validate_token(credentials.credentials)
        return ValidateResponse(
            valid=True,
            service_id=claims.get("sub"),
            issued_at=datetime.fromtimestamp(claims["iat"], tz=timezone.utc).isoformat(),
            expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat(),
        )
    except jwt.ExpiredSignatureError:
        return ValidateResponse(valid=False, error="Token has expired")
    except jwt.InvalidTokenError as exc:
        return ValidateResponse(valid=False, error=f"Invalid token: {exc}")


@app.get("/health", tags=["System"])
async def health_check():
    """Liveness probe — returns JWT config status."""
    using_dev_secret = (_JWT_SECRET == "dev-only-change-in-production")
    return {
        "status": "healthy",
        "service": "security-middleware",
        "port": 3000,
        "jwt_algorithm": _JWT_ALGORITHM,
        "jwt_expiry_seconds": _JWT_EXPIRY,
        "using_dev_secret": using_dev_secret,
        "registered_services": list(_SERVICE_KEYS.keys()),
    }
