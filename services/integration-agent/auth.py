"""
Auth — authentication dependency for FastAPI endpoints.

Extracted from main.py (R15).
"""

import hmac
import logging

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import settings

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)


async def require_token(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """
    Lightweight token guard for mutating endpoints (G-10).

    Behaviour:
      - API_KEY not configured → log warning, allow through (PoC dev mode).
      - API_KEY configured + valid Bearer token → allow.
      - API_KEY configured + missing/invalid token → 401.
    """
    if settings.api_key is None:
        logger.warning(
            "[Security] API_KEY not set — endpoint unprotected (PoC mode). "
            "Set API_KEY in .env to enable auth."
        )
        return "anonymous"

    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required.")

    # F-10 / OWASP A07: constant-time comparison prevents timing attacks
    if not hmac.compare_digest(creds.credentials, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid token.")

    return creds.credentials
