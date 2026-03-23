"""
HTML Collector — Cleaner

Strips HTML boilerplate (scripts, styles, nav, footer, cookie banners)
and returns clean readable text for Claude API semantic extraction.
Uses BeautifulSoup4 for DOM manipulation.
"""
import logging
import re

logger = logging.getLogger(__name__)

# Tags to remove entirely (tag + all content)
_REMOVE_TAGS = {"script", "style", "noscript", "nav", "footer", "aside",
                "header", "form", "button", "svg", "iframe", "img"}

# CSS selectors for boilerplate containers (id/class patterns)
_BOILERPLATE_SELECTORS = [
    "[id*='cookie']", "[id*='banner']", "[id*='popup']", "[id*='modal']",
    "[class*='cookie']", "[class*='banner']", "[class*='popup']",
    "[class*='sidebar']", "[class*='advertisement']", "[class*='ad-']",
]


class HTMLCleaner:
    """
    Extracts clean text from raw HTML.
    Preserves semantic structure (headings, paragraphs, code blocks).
    Removes navigation, scripts, marketing boilerplate.
    """

    def clean(self, html: str) -> str:
        """
        Args:
            html: Raw HTML string.

        Returns:
            Clean text with meaningful content only.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.error("beautifulsoup4 not installed. Run: pip install beautifulsoup4")
            return re.sub(r"<[^>]+>", " ", html)

        soup = BeautifulSoup(html, "html.parser")

        # Remove boilerplate tags
        for tag in _REMOVE_TAGS:
            for element in soup.find_all(tag):
                element.decompose()

        # Remove boilerplate containers by CSS selector
        for selector in _BOILERPLATE_SELECTORS:
            try:
                for element in soup.select(selector):
                    element.decompose()
            except Exception:
                pass  # Ignore selector errors

        # Extract text with structure preserved
        lines: list[str] = []
        for element in soup.find_all(True):
            if element.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                text = element.get_text(strip=True)
                if text:
                    lines.append(f"\n## {text}")
            elif element.name in ("p", "li"):
                text = element.get_text(strip=True)
                if text:
                    lines.append(text)
            elif element.name in ("code", "pre"):
                text = element.get_text(strip=True)
                if text:
                    lines.append(f"```\n{text}\n```")

        # Collapse excessive whitespace/blank lines
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
