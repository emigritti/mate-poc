"""Vision Service — VLM figure captioning via Ollama (ADR-X1).

Primary: Granite-Vision-3.2-2B (IBM, tuned for enterprise documents).
Fallback: LLaVA-7b (legacy, kept for env-var-driven override).

Fallback-first design: any failure (timeout, server error, disabled flag) returns
the "[FIGURE: no caption available]" placeholder so KB ingestion never crashes.
"""

import base64
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

_PLACEHOLDER = "[FIGURE: no caption available]"

_CAPTION_PROMPT = (
    "Describe this image concisely for a technical integration document. "
    "Focus on data flows, field mappings, system names, and chart values if present. "
    "One short paragraph, no bullet points."
)


async def _call_vlm(model: str, image_bytes: bytes) -> str:
    image_b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": _CAPTION_PROMPT,
            "images": [image_b64],
        }],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=settings.tag_timeout_seconds) as client:
        resp = await client.post(f"{settings.ollama_host}/api/chat", json=payload)
        resp.raise_for_status()
        body = resp.json()
        return (body.get("message", {}).get("content") or "").strip()


async def caption_figure(image_bytes: bytes) -> str:
    """Generate a text caption for an image using the configured VLM with fallback.

    Order:
      1. settings.vlm_model_name (Granite-Vision by default)
      2. settings.vlm_fallback_model_name (LLaVA by default) — used on error
         or when settings.vlm_force_fallback is True.
      3. _PLACEHOLDER on both failures.
    """
    if not settings.vision_captioning_enabled:
        return _PLACEHOLDER

    primary = settings.vlm_model_name
    fallback = settings.vlm_fallback_model_name
    models = [fallback] if settings.vlm_force_fallback else [primary, fallback]

    for model in models:
        try:
            caption = await _call_vlm(model, image_bytes)
            if caption:
                logger.info("[Vision] Caption ok (%s, %d chars).", model, len(caption))
                return caption
            logger.warning("[Vision] %s returned empty caption.", model)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
            logger.warning("[Vision] %s failed (%s) — trying next.", model, type(exc).__name__)

    return _PLACEHOLDER
