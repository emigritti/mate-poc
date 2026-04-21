"""
LLM Service — multi-provider client with retry and exponential backoff.

Extracted from main.py (R13 + R15).
Provides:
  - generate_with_ollama(): single Ollama call (non-blocking, httpx)
  - _generate_with_gemini(): single Google Gemini API call (ADR-049)
  - generate_with_retry(): wraps provider call with configurable retry

ADR-012: httpx.AsyncClient for non-blocking Ollama calls.
ADR-049: Google Gemini API as alternative provider — per-profile switching.
R13: Retry with exponential backoff (3 attempts, 5s/15s).
"""

import asyncio
import logging
from typing import Callable

import httpx

from config import settings

logger = logging.getLogger(__name__)

# ── LLM runtime overrides (ADR-022) ──────────────────────────────────────────
# Populated at startup from MongoDB llm_settings collection.
# Consulted by generate_with_ollama() and tag suggestion calls
# before falling back to settings.* pydantic defaults.
llm_overrides: dict = {}


def _get_llm_param(key: str, default, *, override: object = None):
    """Resolve an LLM parameter: explicit override > runtime override > settings default."""
    if override is not None:
        return override
    return llm_overrides.get(key, default)


async def generate_with_ollama(
    prompt: str,
    *,
    model: str | None = None,
    num_predict: int | None = None,
    timeout: int | None = None,
    temperature: float | None = None,
    num_ctx: int | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    repeat_penalty: float | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """
    Call Ollama LLM and return the raw response text.

    Uses httpx.AsyncClient — fully non-blocking (G-04 / ADR-012).
    Raises httpx.HTTPStatusError or httpx.RequestError on failure.
    Logs token/timing metrics via log_fn for dashboard visibility.

    Parameter resolution order: explicit kwarg > llm_overrides > settings default.
    The `model` kwarg takes the highest priority and bypasses llm_overrides (ADR-046).
    """
    _num_predict    = _get_llm_param("num_predict",     settings.ollama_num_predict,     override=num_predict)
    _timeout        = _get_llm_param("timeout_seconds", settings.ollama_timeout_seconds, override=timeout)
    _temperature    = _get_llm_param("temperature",     settings.ollama_temperature,     override=temperature)
    _num_ctx        = _get_llm_param("num_ctx",         settings.ollama_num_ctx,         override=num_ctx)
    _top_p          = _get_llm_param("top_p",           settings.ollama_top_p,           override=top_p)
    _top_k          = _get_llm_param("top_k",           settings.ollama_top_k,           override=top_k)
    _repeat_penalty = _get_llm_param("repeat_penalty",  settings.ollama_repeat_penalty,  override=repeat_penalty)
    # Model: explicit kwarg > llm_overrides > settings default
    _model = model if model is not None else llm_overrides.get("model", settings.ollama_model)

    _log = log_fn or (lambda msg: logger.info(msg))

    _log(
        f"[LLM] → model={_model} "
        f"prompt_chars={len(prompt)} "
        f"timeout={_timeout}s "
        f"num_predict={_num_predict} "
        f"num_ctx={_num_ctx}"
    )
    async with httpx.AsyncClient(timeout=_timeout) as client:
        res = await client.post(
            f"{settings.ollama_host}/api/generate",
            json={
                "model": _model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict":    _num_predict,
                    "temperature":    _temperature,
                    "num_ctx":        _num_ctx,
                    "top_p":          _top_p,
                    "top_k":          _top_k,
                    "repeat_penalty": _repeat_penalty,
                },
            },
        )
        res.raise_for_status()
        body = res.json()

        # Log Ollama performance metrics when available
        eval_count        = body.get("eval_count", 0)
        prompt_eval_count = body.get("prompt_eval_count", 0)
        eval_duration_ns  = body.get("eval_duration", 0)
        total_duration_ns = body.get("total_duration", 0)
        load_duration_ns  = body.get("load_duration", 0)

        total_s = total_duration_ns / 1e9
        load_s  = load_duration_ns  / 1e9
        tps     = eval_count / (eval_duration_ns / 1e9) if eval_duration_ns else 0

        _log(
            f"[LLM] ✓ done — "
            f"prompt_tokens={prompt_eval_count} "
            f"generated_tokens={eval_count} "
            f"speed={tps:.1f} tok/s "
            f"total={total_s:.1f}s "
            f"(model_load={load_s:.1f}s)"
        )

        return body.get("response", "")


async def _generate_with_gemini(
    prompt: str,
    *,
    model: str = "gemini-2.0-flash",
    num_predict: int | None = None,
    timeout: int | None = None,
    temperature: float | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """
    Call Google Gemini API and return the response text. (ADR-049)

    Uses google-generativeai SDK with async generation.
    Raises ValueError if GEMINI_API_KEY is not configured.
    Raises google.api_core.exceptions.GoogleAPIError on API failures.

    Ollama-specific params (num_ctx, top_k, repeat_penalty) are not forwarded
    to Gemini — the model handles context internally.
    """
    api_key = settings.gemini_api_key
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY not set — configure it in .env to use the Gemini provider"
        )

    try:
        import google.generativeai as genai
        from google.generativeai.types import GenerationConfig
    except ImportError as exc:
        raise RuntimeError(
            "google-generativeai not installed — add it to requirements.txt"
        ) from exc

    _log = log_fn or (lambda msg: logger.info(msg))
    _timeout = timeout or settings.ollama_timeout_seconds

    _log(
        f"[LLM/Gemini] → model={model} "
        f"prompt_chars={len(prompt)} "
        f"timeout={_timeout}s "
        f"max_output_tokens={num_predict}"
    )

    genai.configure(api_key=api_key)
    genai_model = genai.GenerativeModel(model_name=model)
    gen_config = GenerationConfig(
        max_output_tokens=num_predict,
        temperature=temperature,
    )

    response = await genai_model.generate_content_async(
        prompt,
        generation_config=gen_config,
        request_options={"timeout": _timeout},
    )

    text = response.text
    _log(f"[LLM/Gemini] ✓ done — response_chars={len(text)}")
    return text


async def generate_with_retry(
    prompt: str,
    *,
    provider: str = "ollama",
    max_retries: int = 3,
    model: str | None = None,
    num_predict: int | None = None,
    timeout: int | None = None,
    temperature: float | None = None,
    num_ctx: int | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    repeat_penalty: float | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """
    Retry-enabled LLM generation with exponential backoff.

    Dispatches to Ollama or Gemini based on the `provider` parameter (ADR-049).

    Strategy:
      - Attempt 1: standard parameters
      - Attempt 2: wait 5s, same parameters
      - Attempt 3: wait 15s, same parameters
      - All attempts failed: re-raise the last exception

    Retryable errors (Ollama):
      - httpx.TimeoutException
      - httpx.ConnectError
      - httpx.HTTPStatusError with 5xx status

    Retryable errors (Gemini):
      - Any exception (rate limits, transient API errors)

    Non-retryable:
      - Ollama: httpx.HTTPStatusError with 4xx (client error / model not found)
      - Gemini: ValueError (missing API key — config error, not transient)
    """
    _log = log_fn or (lambda msg: logger.info(msg))
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            if provider == "gemini":
                return await _generate_with_gemini(
                    prompt,
                    model=model or llm_overrides.get("model", "gemini-2.0-flash"),
                    num_predict=num_predict,
                    timeout=timeout,
                    temperature=temperature,
                    log_fn=log_fn,
                )
            else:
                return await generate_with_ollama(
                    prompt,
                    model=model,
                    num_predict=num_predict,
                    timeout=timeout,
                    temperature=temperature,
                    num_ctx=num_ctx,
                    top_p=top_p,
                    top_k=top_k,
                    repeat_penalty=repeat_penalty,
                    log_fn=log_fn,
                )
        except ValueError:
            # Config error (missing API key) — not retryable
            raise
        except httpx.HTTPStatusError as exc:
            # 4xx = client error (model not found, bad request) — don't retry
            if exc.response.status_code < 500:
                raise
            last_exc = exc
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
        except Exception as exc:
            if provider == "gemini":
                # Gemini API errors (rate limit, transient) — retry
                last_exc = exc
            else:
                # Unknown Ollama errors — don't retry
                raise

        if attempt < max_retries:
            delay = 5 * (3 ** (attempt - 1))  # 5s, 15s
            _log(
                f"[LLM] ⚠ Attempt {attempt}/{max_retries} failed: "
                f"{type(last_exc).__name__} — retrying in {delay}s"
            )
            await asyncio.sleep(delay)
        else:
            _log(
                f"[LLM] ✗ All {max_retries} attempts failed: "
                f"{type(last_exc).__name__}: {last_exc}"
            )

    # All retries exhausted — re-raise the last exception
    raise last_exc  # type: ignore[misc]
