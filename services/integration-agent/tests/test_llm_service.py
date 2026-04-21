"""
Unit tests for services.llm_service — generate_with_retry (R13 + ADR-049).

Ollama path:
  - Success on first attempt (no retry)
  - 5xx error triggers retry; success on second attempt
  - ConnectError triggers retry; success on third attempt
  - TimeoutException triggers retry; re-raises after all retries exhausted
  - 4xx error raises immediately without any retry
  - Unknown exception raises immediately without any retry

Gemini path (ADR-049):
  - provider="gemini" dispatches to _generate_with_gemini (not generate_with_ollama)
  - Gemini generic errors are retried (rate limits, transient API failures)
  - ValueError (missing GEMINI_API_KEY) is not retried — config error
  - Gemini success returns response text on first attempt
"""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://localhost/api/generate")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(f"{status_code}", request=request, response=response)


# ── success cases ─────────────────────────────────────────────────────────────

def test_success_on_first_attempt_no_retry():
    """generate_with_retry returns immediately on first success."""
    from services.llm_service import generate_with_retry

    mock_generate = AsyncMock(return_value="result text")

    with patch("services.llm_service.generate_with_ollama", mock_generate):
        with patch("services.llm_service.asyncio.sleep", AsyncMock()) as mock_sleep:
            result = asyncio.run(generate_with_retry("prompt"))

    assert result == "result text"
    mock_generate.assert_called_once()
    mock_sleep.assert_not_called()


def test_retry_on_5xx_success_on_second_attempt():
    """A 5xx HTTPStatusError on attempt 1 triggers one retry; succeeds on attempt 2."""
    from services.llm_service import generate_with_retry

    mock_generate = AsyncMock(
        side_effect=[_make_http_status_error(503), "recovered result"]
    )

    with patch("services.llm_service.generate_with_ollama", mock_generate):
        with patch("services.llm_service.asyncio.sleep", AsyncMock()) as mock_sleep:
            result = asyncio.run(generate_with_retry("prompt", max_retries=3))

    assert result == "recovered result"
    assert mock_generate.call_count == 2
    mock_sleep.assert_called_once_with(5)  # first backoff delay: 5s


def test_retry_on_connect_error_success_on_third_attempt():
    """ConnectError is retryable; succeeds on third attempt after two delays."""
    from services.llm_service import generate_with_retry

    mock_generate = AsyncMock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            httpx.ConnectError("connection refused"),
            "final result",
        ]
    )

    sleep_calls: list[float] = []

    async def _capture_sleep(delay):
        sleep_calls.append(delay)

    with patch("services.llm_service.generate_with_ollama", mock_generate):
        with patch("services.llm_service.asyncio.sleep", _capture_sleep):
            result = asyncio.run(generate_with_retry("prompt", max_retries=3))

    assert result == "final result"
    assert mock_generate.call_count == 3
    assert sleep_calls == [5, 15]  # 5s after attempt 1, 15s after attempt 2


def test_timeout_exception_all_retries_exhausted_reraises():
    """TimeoutException on all attempts re-raises the last exception."""
    from services.llm_service import generate_with_retry

    timeout_exc = httpx.TimeoutException("timed out")
    mock_generate = AsyncMock(side_effect=timeout_exc)

    with patch("services.llm_service.generate_with_ollama", mock_generate):
        with patch("services.llm_service.asyncio.sleep", AsyncMock()):
            with pytest.raises(httpx.TimeoutException):
                asyncio.run(generate_with_retry("prompt", max_retries=3))

    assert mock_generate.call_count == 3


# ── bail-out cases ────────────────────────────────────────────────────────────

def test_4xx_raises_immediately_no_retry():
    """A 4xx HTTPStatusError (client error) raises immediately — no retry."""
    from services.llm_service import generate_with_retry

    err_404 = _make_http_status_error(404)
    mock_generate = AsyncMock(side_effect=err_404)

    with patch("services.llm_service.generate_with_ollama", mock_generate):
        with patch("services.llm_service.asyncio.sleep", AsyncMock()) as mock_sleep:
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                asyncio.run(generate_with_retry("prompt", max_retries=3))

    assert exc_info.value.response.status_code == 404
    mock_generate.assert_called_once()  # no retry
    mock_sleep.assert_not_called()


def test_unknown_exception_raises_immediately_no_retry():
    """An unexpected exception type propagates immediately without retry."""
    from services.llm_service import generate_with_retry

    mock_generate = AsyncMock(side_effect=ValueError("unexpected error"))

    with patch("services.llm_service.generate_with_ollama", mock_generate):
        with patch("services.llm_service.asyncio.sleep", AsyncMock()) as mock_sleep:
            with pytest.raises(ValueError, match="unexpected error"):
                asyncio.run(generate_with_retry("prompt", max_retries=3))

    mock_generate.assert_called_once()
    mock_sleep.assert_not_called()


# ── Gemini provider tests (ADR-049) ───────────────────────────────────────────

def test_gemini_provider_dispatches_to_gemini_not_ollama():
    """provider='gemini' calls _generate_with_gemini, never generate_with_ollama."""
    from services.llm_service import generate_with_retry

    mock_gemini = AsyncMock(return_value="gemini response")
    mock_ollama = AsyncMock(return_value="ollama response")

    with patch("services.llm_service._generate_with_gemini", mock_gemini):
        with patch("services.llm_service.generate_with_ollama", mock_ollama):
            with patch("services.llm_service.asyncio.sleep", AsyncMock()):
                result = asyncio.run(generate_with_retry("prompt", provider="gemini"))

    assert result == "gemini response"
    mock_gemini.assert_called_once()
    mock_ollama.assert_not_called()


def test_gemini_success_on_first_attempt_no_retry():
    """Gemini provider returns immediately on first success without retrying."""
    from services.llm_service import generate_with_retry

    mock_gemini = AsyncMock(return_value="gemini text")

    with patch("services.llm_service._generate_with_gemini", mock_gemini):
        with patch("services.llm_service.asyncio.sleep", AsyncMock()) as mock_sleep:
            result = asyncio.run(generate_with_retry("prompt", provider="gemini"))

    assert result == "gemini text"
    mock_gemini.assert_called_once()
    mock_sleep.assert_not_called()


def test_gemini_generic_error_is_retried():
    """Gemini generic exceptions (rate limits, transient) trigger retry."""
    from services.llm_service import generate_with_retry

    mock_gemini = AsyncMock(
        side_effect=[RuntimeError("rate limit exceeded"), "gemini recovered"]
    )

    with patch("services.llm_service._generate_with_gemini", mock_gemini):
        with patch("services.llm_service.asyncio.sleep", AsyncMock()) as mock_sleep:
            result = asyncio.run(generate_with_retry("prompt", provider="gemini", max_retries=3))

    assert result == "gemini recovered"
    assert mock_gemini.call_count == 2
    mock_sleep.assert_called_once_with(5)


def test_gemini_all_retries_exhausted_reraises():
    """Gemini re-raises the last exception after all retries are exhausted."""
    from services.llm_service import generate_with_retry

    mock_gemini = AsyncMock(side_effect=RuntimeError("persistent API error"))

    with patch("services.llm_service._generate_with_gemini", mock_gemini):
        with patch("services.llm_service.asyncio.sleep", AsyncMock()):
            with pytest.raises(RuntimeError, match="persistent API error"):
                asyncio.run(generate_with_retry("prompt", provider="gemini", max_retries=3))

    assert mock_gemini.call_count == 3


def test_gemini_value_error_not_retried():
    """ValueError (missing API key) from Gemini is never retried — config error."""
    from services.llm_service import generate_with_retry

    mock_gemini = AsyncMock(side_effect=ValueError("GEMINI_API_KEY not set"))

    with patch("services.llm_service._generate_with_gemini", mock_gemini):
        with patch("services.llm_service.asyncio.sleep", AsyncMock()) as mock_sleep:
            with pytest.raises(ValueError, match="GEMINI_API_KEY not set"):
                asyncio.run(generate_with_retry("prompt", provider="gemini", max_retries=3))

    mock_gemini.assert_called_once()
    mock_sleep.assert_not_called()


def test_gemini_generate_no_api_key_raises_value_error(monkeypatch):
    """_generate_with_gemini raises ValueError when GEMINI_API_KEY is not configured."""
    from services.llm_service import _generate_with_gemini
    from config import settings

    monkeypatch.setattr(settings, "gemini_api_key", None)

    with pytest.raises(ValueError, match="GEMINI_API_KEY not set"):
        asyncio.run(_generate_with_gemini("prompt"))
