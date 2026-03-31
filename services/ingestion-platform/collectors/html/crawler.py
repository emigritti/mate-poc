"""
HTML Collector — Crawler

Fetches HTML pages from entrypoint URLs and discovers linked pages
on the same domain using BFS (breadth-first search).
Uses httpx for async HTTP fetches (static pages — no browser required).

Guardrails:
- Stays within the same domain(s) as the entrypoints
- Hard upper bound: max_pages pages total
- Skips binary file extensions (.pdf, .zip, images, fonts, etc.)
- Skips fragments and mailto: links
- Graceful error handling: failed fetches are logged and skipped
"""
import logging
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

_SKIP_EXTENSIONS = {
    ".pdf", ".zip", ".gz", ".tar",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".woff", ".woff2", ".ttf", ".eot",
    ".css", ".js", ".map",
    ".xml", ".json", ".yaml", ".yml",
}

_TIMEOUT = 15.0  # seconds per request


@dataclass
class CrawledPage:
    url: str
    html: str


class HTMLCrawler:
    """
    BFS crawler for static HTML documentation sites.
    Stays within the same domain(s) as the entrypoint URLs.
    All discovered pages are returned as CrawledPage objects.
    """

    async def crawl(
        self,
        entrypoints: list[str],
        max_pages: int = 20,
    ) -> list[CrawledPage]:
        """
        Crawl up to max_pages HTML pages starting from each entrypoint.

        Args:
            entrypoints: Starting URLs (all must be http/https).
            max_pages: Hard upper bound on total pages fetched.

        Returns:
            List of CrawledPage objects. Empty list if all fetches fail.
        """
        try:
            import httpx
        except ImportError:
            logger.error("httpx not installed — cannot crawl HTML pages")
            return []

        try:
            from bs4 import BeautifulSoup  # noqa: F401 — verify import early
        except ImportError:
            logger.error("beautifulsoup4 not installed — cannot extract links")
            return []

        allowed_domains = {urlparse(u).netloc for u in entrypoints if urlparse(u).netloc}
        visited: set[str] = set()
        queue: list[str] = [self._normalize_url(u) for u in entrypoints if self._normalize_url(u)]
        pages: list[CrawledPage] = []

        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "IntegrationMate-KB-Crawler/1.0"},
        ) as client:
            while queue and len(pages) < max_pages:
                url = queue.pop(0)
                if not url or url in visited:
                    continue
                visited.add(url)

                if not self._is_allowed(url, allowed_domains):
                    continue

                html = await self._fetch(client, url)
                if html is None:
                    continue

                pages.append(CrawledPage(url=url, html=html))

                if len(pages) < max_pages:
                    for link in self._extract_links(html, url):
                        if link not in visited:
                            queue.append(link)

        logger.info(
            "HTMLCrawler: fetched %d pages from %d entrypoints (limit=%d)",
            len(pages), len(entrypoints), max_pages,
        )
        return pages

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _fetch(self, client, url: str) -> str | None:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.debug("Skipping %s — HTTP %d", url, resp.status_code)
                return None
            content_type = resp.headers.get("content-type", "")
            if "html" not in content_type and "text/plain" not in content_type:
                logger.debug("Skipping %s — non-HTML content-type: %s", url, content_type)
                return None
            return resp.text
        except Exception as exc:
            logger.warning("Fetch failed for %s: %s", url, exc)
            return None

    def _extract_links(self, html: str, base_url: str) -> list[str]:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            links: list[str] = []
            for tag in soup.find_all("a", href=True):
                href = tag["href"].strip()
                if not href or href.startswith("#") or href.startswith("mailto:"):
                    continue
                absolute = urljoin(base_url, href)
                normalized = self._normalize_url(absolute)
                if normalized:
                    links.append(normalized)
            return links
        except Exception as exc:
            logger.warning("Link extraction failed for %s: %s", base_url, exc)
            return []

    def _normalize_url(self, url: str) -> str | None:
        """Strip fragment, reject non-HTTP schemes and binary extensions."""
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return None
            # Check file extension of last path segment
            last_segment = parsed.path.rsplit("/", 1)[-1]
            if "." in last_segment:
                ext = "." + last_segment.rsplit(".", 1)[-1].lower()
                if ext in _SKIP_EXTENSIONS:
                    return None
            # Rebuild without fragment
            return parsed._replace(fragment="").geturl()
        except Exception:
            return None

    def _is_allowed(self, url: str, allowed_domains: set[str]) -> bool:
        return urlparse(url).netloc in allowed_domains
