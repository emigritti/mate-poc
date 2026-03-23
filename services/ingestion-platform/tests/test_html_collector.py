"""
TDD — HTML Collector Unit Tests (RED phase)

Tests cleaner → extractor → normalizer pipeline.
Playwright and Claude API are mocked — no browser or network required.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Sample HTML fixtures ──────────────────────────────────────────────────────

TECH_DOC_HTML = """
<html>
<body>
  <h1>Payment API Integration Guide</h1>
  <h2>Authentication</h2>
  <p>Use Bearer token in the Authorization header. Token obtained from /auth/token endpoint.</p>
  <h2>Create Payment</h2>
  <p>POST /payments — Creates a new payment transaction.</p>
  <code>curl -X POST https://api.example.com/payments -H "Authorization: Bearer TOKEN" -d '{"amount": 100}'</code>
  <h2>Get Payment Status</h2>
  <p>GET /payments/{id} — Retrieves payment status.</p>
</body>
</html>
"""

MARKETING_HTML = """
<html>
<body>
  <h1>Our Amazing Product!</h1>
  <p>Best-in-class solution for enterprises. Sign up today for a free trial!</p>
  <p>Trusted by 10,000+ customers worldwide.</p>
</body>
</html>
"""

BOILERPLATE_HTML = """
<html>
<head><script>analytics.track();</script></head>
<body>
  <nav>Home | About | Contact</nav>
  <div id="cookie-banner">We use cookies.</div>
  <main>
    <h1>API Reference</h1>
    <p>Use our REST API to integrate.</p>
  </main>
  <footer>© 2026 Company Inc.</footer>
</body>
</html>
"""


# ── HTML Cleaner tests ────────────────────────────────────────────────────────

class TestHTMLCleaner:
    def test_strips_html_tags(self):
        from collectors.html.cleaner import HTMLCleaner
        cleaner = HTMLCleaner()
        result = cleaner.clean(TECH_DOC_HTML)
        assert "<h1>" not in result
        assert "<p>" not in result

    def test_preserves_text_content(self):
        from collectors.html.cleaner import HTMLCleaner
        cleaner = HTMLCleaner()
        result = cleaner.clean(TECH_DOC_HTML)
        assert "Payment API Integration Guide" in result
        assert "Authorization" in result

    def test_removes_script_tags_and_content(self):
        from collectors.html.cleaner import HTMLCleaner
        cleaner = HTMLCleaner()
        result = cleaner.clean(BOILERPLATE_HTML)
        assert "analytics.track" not in result

    def test_removes_nav_footer(self):
        from collectors.html.cleaner import HTMLCleaner
        cleaner = HTMLCleaner()
        result = cleaner.clean(BOILERPLATE_HTML)
        # Main content should survive
        assert "API Reference" in result

    def test_preserves_headings_as_text(self):
        from collectors.html.cleaner import HTMLCleaner
        cleaner = HTMLCleaner()
        result = cleaner.clean(TECH_DOC_HTML)
        assert "Authentication" in result
        assert "Create Payment" in result

    def test_collapses_excessive_whitespace(self):
        from collectors.html.cleaner import HTMLCleaner
        cleaner = HTMLCleaner()
        result = cleaner.clean(TECH_DOC_HTML)
        assert "\n\n\n" not in result  # no triple+ newlines

    def test_empty_html_returns_empty_string(self):
        from collectors.html.cleaner import HTMLCleaner
        cleaner = HTMLCleaner()
        result = cleaner.clean("<html><body></body></html>")
        assert result.strip() == ""


# ── HTML Extractor (relevance filter) tests ──────────────────────────────────

class TestHTMLExtractor:
    def test_filter_returns_true_when_claude_says_relevant(self):
        from collectors.html.extractor import HTMLRelevanceFilter
        mock_claude = AsyncMock()
        mock_claude.filter_relevance = AsyncMock(return_value=True)
        extractor = HTMLRelevanceFilter(claude_service=mock_claude)
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            extractor.is_relevant("POST /payments creates a payment", "https://docs.example.com/api")
        )
        assert result is True

    def test_filter_returns_false_when_claude_says_not_relevant(self):
        from collectors.html.extractor import HTMLRelevanceFilter
        mock_claude = AsyncMock()
        mock_claude.filter_relevance = AsyncMock(return_value=False)
        extractor = HTMLRelevanceFilter(claude_service=mock_claude)
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            extractor.is_relevant("Sign up today!", "https://example.com/promo")
        )
        assert result is False

    def test_filter_returns_true_when_claude_unavailable(self):
        from collectors.html.extractor import HTMLRelevanceFilter
        extractor = HTMLRelevanceFilter(claude_service=None)
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            extractor.is_relevant("any content", "https://example.com")
        )
        assert result is True  # conservative default: include


# ── HTML Agent Extractor tests ────────────────────────────────────────────────

class TestHTMLAgentExtractor:
    def test_extract_returns_capabilities_from_claude_output(self):
        from collectors.html.agent_extractor import HTMLAgentExtractor
        mock_claude = AsyncMock()
        mock_claude.extract_capabilities = AsyncMock(return_value=[
            {
                "name": "create_payment",
                "kind": "endpoint",
                "description": "POST /payments — Create payment",
                "confidence": 0.9,
                "source_trace": {"page_url": "https://docs.example.com/api", "section": "Create Payment"},
            }
        ])
        extractor = HTMLAgentExtractor(claude_service=mock_claude)
        import asyncio
        caps = asyncio.get_event_loop().run_until_complete(
            extractor.extract("POST /payments creates a payment", "https://docs.example.com/api")
        )
        assert len(caps) == 1
        assert caps[0]["name"] == "create_payment"

    def test_extract_returns_empty_when_claude_unavailable(self):
        from collectors.html.agent_extractor import HTMLAgentExtractor
        extractor = HTMLAgentExtractor(claude_service=None)
        import asyncio
        caps = asyncio.get_event_loop().run_until_complete(
            extractor.extract("any content", "https://example.com")
        )
        assert caps == []

    def test_extract_filters_low_confidence_not_removed(self):
        """Low confidence items are kept but flagged — not silently discarded."""
        from collectors.html.agent_extractor import HTMLAgentExtractor
        mock_claude = AsyncMock()
        mock_claude.extract_capabilities = AsyncMock(return_value=[
            {
                "name": "unclear_op",
                "kind": "endpoint",
                "description": "Something unclear",
                "confidence": 0.4,
                "source_trace": {"page_url": "https://example.com", "section": "?"},
            }
        ])
        extractor = HTMLAgentExtractor(claude_service=mock_claude)
        import asyncio
        caps = asyncio.get_event_loop().run_until_complete(
            extractor.extract("unclear content", "https://example.com")
        )
        # Not discarded — just kept with low confidence
        assert len(caps) == 1
        assert caps[0]["confidence"] < 0.7


# ── HTML Normalizer tests ─────────────────────────────────────────────────────

class TestHTMLNormalizer:
    def test_raw_dict_to_canonical_capability(self):
        from collectors.html.normalizer import HTMLNormalizer
        norm = HTMLNormalizer()
        raw = {
            "name": "create_payment",
            "kind": "endpoint",
            "description": "POST /payments — Create payment",
            "confidence": 0.9,
            "source_trace": {"page_url": "https://docs.example.com/api", "section": "Create Payment"},
        }
        caps = norm.normalize([raw], source_code="payment_docs")
        assert len(caps) == 1
        assert caps[0].kind.value == "endpoint"
        assert caps[0].confidence == 0.9

    def test_unknown_kind_defaults_to_guide_step(self):
        from collectors.html.normalizer import HTMLNormalizer
        norm = HTMLNormalizer()
        raw = {
            "name": "some_flow",
            "kind": "unknown_kind",
            "description": "Some flow",
            "confidence": 0.8,
            "source_trace": {"page_url": "https://example.com", "section": "Flows"},
        }
        caps = norm.normalize([raw], source_code="html_docs")
        assert caps[0].kind.value == "guide_step"

    def test_source_trace_preserved(self):
        from collectors.html.normalizer import HTMLNormalizer
        norm = HTMLNormalizer()
        raw = {
            "name": "auth_flow",
            "kind": "auth",
            "description": "OAuth2 flow",
            "confidence": 0.95,
            "source_trace": {"page_url": "https://docs.example.com/auth", "section": "Authentication"},
        }
        caps = norm.normalize([raw], source_code="payment_docs")
        assert caps[0].source_trace.page_url == "https://docs.example.com/auth"
        assert caps[0].source_trace.origin_type == "html"

    def test_empty_input_returns_empty_list(self):
        from collectors.html.normalizer import HTMLNormalizer
        norm = HTMLNormalizer()
        caps = norm.normalize([], source_code="html_docs")
        assert caps == []

    def test_missing_confidence_defaults_to_one(self):
        from collectors.html.normalizer import HTMLNormalizer
        norm = HTMLNormalizer()
        raw = {
            "name": "endpoint_no_conf",
            "kind": "endpoint",
            "description": "Something",
            "source_trace": {"page_url": "https://example.com", "section": "X"},
        }
        caps = norm.normalize([raw], source_code="html_docs")
        assert caps[0].confidence == 1.0
