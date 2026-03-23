"""
OpenAPI Collector — Fetcher

Downloads an OpenAPI spec from a URL with ETag-based caching.
Returns (raw_content, etag, changed) where changed=False means 304 Not Modified.
"""
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
ACCEPT_HEADERS = {
    "Accept": "application/json, application/yaml, text/yaml, text/plain, */*",
    "User-Agent": "integration-mate-ingestion-platform/1.0",
}


class FetchError(Exception):
    """Raised when the spec URL cannot be fetched."""


@dataclass
class FetchResult:
    content: str
    etag: Optional[str]
    changed: bool           # False = 304 Not Modified (ETag matched)
    status_code: int
    content_type: str


class OpenAPIFetcher:
    """
    Downloads OpenAPI spec from URL.
    Supports ETag caching: pass previous_etag to skip re-parsing unchanged specs.
    """

    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout_seconds

    async def fetch(self, url: str, previous_etag: Optional[str] = None) -> FetchResult:
        """
        Fetch spec from URL.

        Args:
            url: HTTP/HTTPS URL of the OpenAPI spec.
            previous_etag: ETag from previous successful fetch (for 304 optimization).

        Returns:
            FetchResult with content, etag, and changed flag.

        Raises:
            FetchError: On connection error, timeout, or non-2xx/304 response.
        """
        headers = dict(ACCEPT_HEADERS)
        if previous_etag:
            headers["If-None-Match"] = previous_etag

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise FetchError(f"Timeout fetching {url}: {exc}") from exc
        except httpx.RequestError as exc:
            raise FetchError(f"Request error fetching {url}: {exc}") from exc

        if response.status_code == 304:
            logger.info("304 Not Modified for %s (ETag matched)", url)
            return FetchResult(
                content="", etag=previous_etag, changed=False,
                status_code=304, content_type="",
            )

        if response.status_code not in (200, 201):
            raise FetchError(
                f"Unexpected HTTP {response.status_code} fetching {url}"
            )

        etag = response.headers.get("ETag")
        content_type = response.headers.get("Content-Type", "")
        logger.info("Fetched %s — %d bytes, ETag=%s", url, len(response.content), etag)

        return FetchResult(
            content=response.text,
            etag=etag,
            changed=True,
            status_code=response.status_code,
            content_type=content_type,
        )
