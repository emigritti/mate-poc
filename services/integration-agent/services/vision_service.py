"""
Vision Service — LLaVA figure captioning via Ollama (ADR-031).

Provides:
  - caption_figure(image_bytes): call llava:7b via Ollama /api/chat with base64 image.

Fallback-first design: any failure (timeout, server error, disabled flag) returns
the "[FIGURE: no caption available]" placeholder so KB ingestion never crashes.

All processing is local — no external API calls. Ollama must have llava:7b pulled.
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


async def caption_figure(image_bytes: bytes) -> str:
    """
    Generate a text caption for an image using LLaVA via Ollama /api/chat.

    Returns the caption string on success, or _PLACEHOLDER on any failure /
    when vision_captioning_enabled=False.
    """
    if not settings.vision_captioning_enabled:
        return _PLACEHOLDER

    image_b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model": settings.vision_model_name,
        "messages": [
            {
                "role": "user",
                "content": _CAPTION_PROMPT,
                "images": [image_b64],
            }
        ],
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.tag_timeout_seconds) as client:
            resp = await client.post(
                f"{settings.ollama_host}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            body = resp.json()
            caption = body.get("message", {}).get("content", "").strip()
            if not caption:
                logger.warning("[Vision] LLaVA returned empty caption.")
                return _PLACEHOLDER
            logger.info("[Vision] Caption generated (%d chars).", len(caption))
            return caption
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
        logger.warning("[Vision] Caption failed (%s: %s) — using placeholder.", type(exc).__name__, exc)
        return _PLACEHOLDER
