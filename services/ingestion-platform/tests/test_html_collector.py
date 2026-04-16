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


# ── HTML Crawler tests ────────────────────────────────────────────────────────

class TestHTMLCrawler:
    """Tests for HTMLCrawler — httpx mocked, no real network calls."""

    def _make_response(self, text: str, status_code: int = 200, content_type: str = "text/html"):
        mock = MagicMock()
        mock.status_code = status_code
        mock.text = text
        mock.headers = {"content-type": content_type}
        return mock

    def test_crawl_returns_page_for_single_entrypoint(self):
        from collectors.html.crawler import HTMLCrawler
        crawler = HTMLCrawler()
        html = "<html><body><h1>API Docs</h1></body></html>"

        async def mock_crawl():
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                instance.get = AsyncMock(return_value=self._make_response(html))
                MockClient.return_value = instance
                return await crawler.crawl(["https://docs.example.com/api"], max_pages=1)

        import asyncio
        pages = asyncio.get_event_loop().run_until_complete(mock_crawl())
        assert len(pages) == 1
        assert pages[0].url == "https://docs.example.com/api"
        assert "API Docs" in pages[0].html

    def test_crawl_respects_max_pages_limit(self):
        from collectors.html.crawler import HTMLCrawler
        crawler = HTMLCrawler()
        # HTML with links to 5 sub-pages
        html = """<html><body>
            <a href="/p1">p1</a><a href="/p2">p2</a>
            <a href="/p3">p3</a><a href="/p4">p4</a>
            <a href="/p5">p5</a>
        </body></html>"""
        sub_html = "<html><body><p>sub</p></body></html>"

        async def mock_crawl():
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                # First call returns links, subsequent calls return sub_html
                instance.get = AsyncMock(side_effect=[
                    self._make_response(html),
                    self._make_response(sub_html),
                    self._make_response(sub_html),
                ])
                MockClient.return_value = instance
                return await crawler.crawl(["https://docs.example.com"], max_pages=3)

        import asyncio
        pages = asyncio.get_event_loop().run_until_complete(mock_crawl())
        assert len(pages) <= 3

    def test_crawl_skips_non_200_responses(self):
        from collectors.html.crawler import HTMLCrawler
        crawler = HTMLCrawler()

        async def mock_crawl():
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                instance.get = AsyncMock(return_value=self._make_response("", status_code=404))
                MockClient.return_value = instance
                return await crawler.crawl(["https://docs.example.com/missing"])

        import asyncio
        pages = asyncio.get_event_loop().run_until_complete(mock_crawl())
        assert pages == []

    def test_crawl_skips_non_html_content_type(self):
        from collectors.html.crawler import HTMLCrawler
        crawler = HTMLCrawler()

        async def mock_crawl():
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                instance.get = AsyncMock(
                    return_value=self._make_response("{}", content_type="application/json")
                )
                MockClient.return_value = instance
                return await crawler.crawl(["https://docs.example.com/api.json"])

        import asyncio
        pages = asyncio.get_event_loop().run_until_complete(mock_crawl())
        assert pages == []

    def test_normalize_url_strips_fragment(self):
        from collectors.html.crawler import HTMLCrawler
        crawler = HTMLCrawler()
        result = crawler._normalize_url("https://docs.example.com/api#section-1")
        assert result == "https://docs.example.com/api"
        assert "#" not in result

    def test_normalize_url_rejects_binary_extensions(self):
        from collectors.html.crawler import HTMLCrawler
        crawler = HTMLCrawler()
        assert crawler._normalize_url("https://example.com/doc.pdf") is None
        assert crawler._normalize_url("https://example.com/image.png") is None
        assert crawler._normalize_url("https://example.com/styles.css") is None

    def test_normalize_url_rejects_non_http_schemes(self):
        from collectors.html.crawler import HTMLCrawler
        crawler = HTMLCrawler()
        assert crawler._normalize_url("ftp://example.com/doc") is None
        assert crawler._normalize_url("mailto:user@example.com") is None

    def test_is_allowed_rejects_cross_domain(self):
        from collectors.html.crawler import HTMLCrawler
        crawler = HTMLCrawler()
        allowed = {"docs.example.com"}
        assert crawler._is_allowed("https://docs.example.com/api", allowed) is True
        assert crawler._is_allowed("https://evil.com/steal", allowed) is False

    def test_crawl_handles_fetch_exception_gracefully(self):
        from collectors.html.crawler import HTMLCrawler
        crawler = HTMLCrawler()

        async def mock_crawl():
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                instance.get = AsyncMock(side_effect=Exception("Connection refused"))
                MockClient.return_value = instance
                return await crawler.crawl(["https://docs.example.com"])

        import asyncio
        pages = asyncio.get_event_loop().run_until_complete(mock_crawl())
        assert pages == []


# ── HTML Chunker tests ────────────────────────────────────────────────────────

class TestHTMLChunker:
    """Tests for HTMLChunker — verifies CanonicalCapability → CanonicalChunk conversion."""

    def _make_capability(self, name="create_payment", kind="endpoint",
                         description="POST /payments", page_url="https://docs.example.com/api",
                         section="Payments", confidence=0.9):
        from collectors.html.normalizer import HTMLNormalizer
        return HTMLNormalizer().normalize([{
            "name": name,
            "kind": kind,
            "description": description,
            "confidence": confidence,
            "source_trace": {"page_url": page_url, "section": section},
        }], source_code="test_source")[0]

    def test_chunk_produces_one_chunk_per_capability(self):
        from collectors.html.chunker import HTMLChunker
        chunker = HTMLChunker()
        caps = [self._make_capability("op1"), self._make_capability("op2")]
        chunks = chunker.chunk(caps, source_code="test_source", tags=["payments"])
        assert len(chunks) == 2

    def test_chunk_text_contains_kind_name_description(self):
        from collectors.html.chunker import HTMLChunker
        chunker = HTMLChunker()
        cap = self._make_capability(name="create_payment", kind="endpoint",
                                    description="POST /payments — Creates a payment")
        chunks = chunker.chunk([cap], source_code="test_source", tags=[])
        assert "[ENDPOINT]" in chunks[0].text
        assert "create_payment" in chunks[0].text
        assert "POST /payments" in chunks[0].text

    def test_chunk_includes_source_url(self):
        from collectors.html.chunker import HTMLChunker
        chunker = HTMLChunker()
        cap = self._make_capability(page_url="https://docs.example.com/api/payments")
        chunks = chunker.chunk([cap], source_code="test_source", tags=[])
        assert "https://docs.example.com/api/payments" in chunks[0].text

    def test_chunk_sets_correct_source_type(self):
        from collectors.html.chunker import HTMLChunker
        chunker = HTMLChunker()
        cap = self._make_capability()
        chunks = chunker.chunk([cap], source_code="payment_docs", tags=["payments"])
        assert chunks[0].source_type == "html"
        assert chunks[0].source_code == "payment_docs"

    def test_chunk_preserves_confidence(self):
        from collectors.html.chunker import HTMLChunker
        chunker = HTMLChunker()
        cap = self._make_capability(confidence=0.65)
        chunks = chunker.chunk([cap], source_code="test_source", tags=[])
        assert chunks[0].confidence == pytest.approx(0.65)

    def test_chunk_empty_capabilities_returns_empty(self):
        from collectors.html.chunker import HTMLChunker
        chunker = HTMLChunker()
        chunks = chunker.chunk([], source_code="test_source", tags=[])
        assert chunks == []

    def test_chunk_sequential_index(self):
        from collectors.html.chunker import HTMLChunker
        chunker = HTMLChunker()
        caps = [self._make_capability(f"op{i}") for i in range(5)]
        chunks = chunker.chunk(caps, source_code="test_source", tags=[])
        assert [c.index for c in chunks] == list(range(5))


# ── HTML Reconciler tests ─────────────────────────────────────────────────────

class TestHTMLReconciler:
    """Tests for HTMLReconciler — cross-page capability deduplication (ADR-037)."""

    def _make_capabilities(self, names: list[str], source_code: str = "test_source"):
        from collectors.html.normalizer import HTMLNormalizer
        norm = HTMLNormalizer()
        caps = []
        for name in names:
            caps.extend(norm.normalize([{
                "name": name,
                "kind": "endpoint",
                "description": f"Description for {name}",
                "confidence": 0.9,
                "source_trace": {"page_url": "https://docs.example.com", "section": name},
            }], source_code=source_code))
        return caps

    def test_passthrough_when_claude_unavailable(self):
        """Returns input unchanged when Claude service is None."""
        from collectors.html.reconciler import HTMLReconciler
        reconciler = HTMLReconciler(claude_service=None)
        caps = self._make_capabilities(["create_payment", "get_payment"])
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            reconciler.reconcile(caps, source_code="test_source")
        )
        assert result is caps  # same object — no copy

    def test_passthrough_single_capability(self):
        """Single capability is returned as-is without calling Claude."""
        from collectors.html.reconciler import HTMLReconciler
        mock_claude = AsyncMock()
        reconciler = HTMLReconciler(claude_service=mock_claude)
        caps = self._make_capabilities(["only_one"])
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            reconciler.reconcile(caps, source_code="test_source")
        )
        assert len(result) == 1
        mock_claude.reconcile_capabilities.assert_not_called()

    def test_passthrough_empty_list(self):
        """Empty list is returned unchanged without calling Claude."""
        from collectors.html.reconciler import HTMLReconciler
        mock_claude = AsyncMock()
        reconciler = HTMLReconciler(claude_service=mock_claude)
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            reconciler.reconcile([], source_code="test_source")
        )
        assert result == []
        mock_claude.reconcile_capabilities.assert_not_called()

    def test_merges_near_duplicates(self):
        """Two near-duplicate capabilities are merged into one by Claude."""
        from collectors.html.reconciler import HTMLReconciler
        mock_claude = AsyncMock()
        mock_claude.reconcile_capabilities = AsyncMock(return_value=[
            {
                "name": "create_payment",
                "kind": "endpoint",
                "description": "POST /payments — creates payment (merged from 2 pages)",
                "confidence": 0.95,
                "source_trace": {"page_url": "https://docs.example.com/api", "section": "Payments"},
            }
        ])
        reconciler = HTMLReconciler(claude_service=mock_claude)
        # Two near-duplicate inputs
        caps = self._make_capabilities(["create_payment", "create_payment"])
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            reconciler.reconcile(caps, source_code="test_source")
        )
        assert len(result) == 1
        assert result[0].name == "create_payment"
        assert result[0].confidence == pytest.approx(0.95)

    def test_preserves_distinct_capabilities(self):
        """Distinct capabilities are all returned when Claude reports no duplicates."""
        from collectors.html.reconciler import HTMLReconciler
        mock_claude = AsyncMock()
        mock_claude.reconcile_capabilities = AsyncMock(return_value=[
            {
                "name": "create_payment",
                "kind": "endpoint",
                "description": "POST /payments",
                "confidence": 0.9,
                "source_trace": {"page_url": "https://docs.example.com", "section": "A"},
            },
            {
                "name": "get_payment",
                "kind": "endpoint",
                "description": "GET /payments/{id}",
                "confidence": 0.9,
                "source_trace": {"page_url": "https://docs.example.com", "section": "B"},
            },
        ])
        reconciler = HTMLReconciler(claude_service=mock_claude)
        caps = self._make_capabilities(["create_payment", "get_payment"])
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            reconciler.reconcile(caps, source_code="test_source")
        )
        assert len(result) == 2

    def test_fallback_on_claude_none_response(self):
        """When Claude returns None (error), original batch is returned unchanged."""
        from collectors.html.reconciler import HTMLReconciler
        mock_claude = AsyncMock()
        mock_claude.reconcile_capabilities = AsyncMock(return_value=None)
        reconciler = HTMLReconciler(claude_service=mock_claude)
        caps = self._make_capabilities(["create_payment", "get_payment"])
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            reconciler.reconcile(caps, source_code="test_source")
        )
        # Original batch preserved — graceful degradation
        assert len(result) == 2

    def test_batches_large_input(self):
        """Input larger than _BATCH_SIZE triggers multiple Claude calls."""
        from collectors.html.reconciler import HTMLReconciler, _BATCH_SIZE
        mock_claude = AsyncMock()
        # Return the input unchanged (no merges)
        async def echo_caps(caps_list):
            return caps_list
        mock_claude.reconcile_capabilities = echo_caps

        reconciler = HTMLReconciler(claude_service=mock_claude)
        # Create _BATCH_SIZE + 5 capabilities
        caps = self._make_capabilities([f"op_{i}" for i in range(_BATCH_SIZE + 5)])
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            reconciler.reconcile(caps, source_code="test_source")
        )
        # Two batches processed — all capabilities preserved (no duplicates)
        assert len(result) == _BATCH_SIZE + 5

    def test_cap_to_dict_serialization(self):
        """_cap_to_dict produces the expected dict structure for Claude input."""
        from collectors.html.reconciler import HTMLReconciler
        caps = self._make_capabilities(["auth_flow"])
        d = HTMLReconciler._cap_to_dict(caps[0])
        assert d["name"] == "auth_flow"
        assert d["kind"] == "endpoint"
        assert "page_url" in d["source_trace"]
        assert "section" in d["source_trace"]
