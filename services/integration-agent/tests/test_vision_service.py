"""
Unit tests for services.vision_service (ADR-031).

TDD: tests written before implementation.

Covers:
  - caption_figure returns a non-empty string when Ollama responds
  - caption_figure returns placeholder when vision_captioning_enabled=False
  - caption_figure returns placeholder when Ollama times out (graceful fallback)
  - caption_figure returns placeholder when Ollama returns 5xx (graceful fallback)
  - caption_figure sends image as base64 in the request body
"""
import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # fake PNG bytes


def _make_ollama_chat_response(content: str) -> MagicMock:
    """Build a fake successful httpx response for /api/chat."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {"role": "assistant", "content": content}
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _mock_settings(enabled: bool = True):
    mock = MagicMock()
    mock.vision_captioning_enabled = enabled
    mock.vision_model_name = "llava:7b"
    mock.ollama_host = "http://localhost:11434"
    mock.tag_timeout_seconds = 15
    return mock


def _async_client_posting(response):
    """Build a mocked httpx.AsyncClient that returns `response` on .post()."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=response)
    return mock_client


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_caption_figure_returns_description_from_ollama():
    """caption_figure returns the LLM description when Ollama responds successfully."""
    from services.vision_service import caption_figure

    expected = "A bar chart showing PLM to PIM field mapping with 5 columns."

    with patch("services.vision_service.settings", _mock_settings()), \
         patch("httpx.AsyncClient", return_value=_async_client_posting(
             _make_ollama_chat_response(expected)
         )):
        result = asyncio.run(caption_figure(SAMPLE_IMAGE_BYTES))

    assert result == expected


def test_caption_figure_returns_placeholder_when_disabled():
    """caption_figure returns placeholder text when vision_captioning_enabled=False."""
    from services.vision_service import caption_figure

    with patch("services.vision_service.settings", _mock_settings(enabled=False)):
        result = asyncio.run(caption_figure(SAMPLE_IMAGE_BYTES))

    assert result == "[FIGURE: no caption available]"


def test_caption_figure_returns_placeholder_on_timeout():
    """caption_figure gracefully returns placeholder when Ollama times out."""
    from services.vision_service import caption_figure

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(
        side_effect=httpx.TimeoutException("timed out", request=MagicMock())
    )

    with patch("services.vision_service.settings", _mock_settings()), \
         patch("httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(caption_figure(SAMPLE_IMAGE_BYTES))

    assert result == "[FIGURE: no caption available]"


def test_caption_figure_returns_placeholder_on_server_error():
    """caption_figure gracefully returns placeholder when Ollama returns 5xx."""
    from services.vision_service import caption_figure

    exc = httpx.HTTPStatusError(
        "service unavailable",
        request=MagicMock(),
        response=MagicMock(status_code=503),
    )
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=exc)

    with patch("services.vision_service.settings", _mock_settings()), \
         patch("httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(caption_figure(SAMPLE_IMAGE_BYTES))

    assert result == "[FIGURE: no caption available]"


def test_caption_figure_sends_image_as_base64():
    """caption_figure encodes image bytes as base64 in the Ollama /api/chat request."""
    from services.vision_service import caption_figure

    expected_b64 = base64.b64encode(SAMPLE_IMAGE_BYTES).decode()
    captured: dict = {}

    async def _capture_post(url, json=None, **kwargs):
        captured.update(json or {})
        return _make_ollama_chat_response("a diagram")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = _capture_post

    with patch("services.vision_service.settings", _mock_settings()), \
         patch("httpx.AsyncClient", return_value=mock_client):
        asyncio.run(caption_figure(SAMPLE_IMAGE_BYTES))

    messages = captured.get("messages", [])
    assert messages, "No messages in payload"
    assert expected_b64 in messages[0].get("images", [])
