import pytest
import httpx
from unittest.mock import patch
from services.vision_service import caption_figure


@pytest.mark.asyncio
async def test_caption_uses_primary_vlm_first(monkeypatch):
    monkeypatch.setattr("config.settings.vlm_model_name", "granite3.2-vision:2b")
    monkeypatch.setattr("config.settings.vlm_fallback_model_name", "llava:7b")
    monkeypatch.setattr("config.settings.vlm_force_fallback", False)
    monkeypatch.setattr("config.settings.vision_captioning_enabled", True)

    captured_models = []

    async def fake_post(self, url, json, **kw):
        captured_models.append(json["model"])

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"message": {"content": "primary caption"}}

        return R()

    with patch("httpx.AsyncClient.post", new=fake_post):
        out = await caption_figure(b"\x00\x01")
    assert out == "primary caption"
    assert captured_models == ["granite3.2-vision:2b"]


@pytest.mark.asyncio
async def test_caption_falls_back_to_llava_on_primary_error(monkeypatch):
    monkeypatch.setattr("config.settings.vlm_model_name", "granite3.2-vision:2b")
    monkeypatch.setattr("config.settings.vlm_fallback_model_name", "llava:7b")
    monkeypatch.setattr("config.settings.vlm_force_fallback", False)
    monkeypatch.setattr("config.settings.vision_captioning_enabled", True)

    calls = []

    async def fake_post(self, url, json, **kw):
        calls.append(json["model"])
        primary = json["model"] == "granite3.2-vision:2b"

        class R:
            status_code = 500 if primary else 200

            def raise_for_status(self):
                if primary:
                    req = httpx.Request("POST", url)
                    raise httpx.HTTPStatusError(
                        "boom",
                        request=req,
                        response=httpx.Response(500, request=req),
                    )

            def json(self):
                return {"message": {"content": "fallback caption"}}

        return R()

    with patch("httpx.AsyncClient.post", new=fake_post):
        out = await caption_figure(b"\x00\x01")
    assert out == "fallback caption"
    assert calls == ["granite3.2-vision:2b", "llava:7b"]


@pytest.mark.asyncio
async def test_caption_skips_primary_when_force_fallback_set(monkeypatch):
    monkeypatch.setattr("config.settings.vlm_model_name", "granite3.2-vision:2b")
    monkeypatch.setattr("config.settings.vlm_fallback_model_name", "llava:7b")
    monkeypatch.setattr("config.settings.vlm_force_fallback", True)
    monkeypatch.setattr("config.settings.vision_captioning_enabled", True)

    calls = []

    async def fake_post(self, url, json, **kw):
        calls.append(json["model"])

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"message": {"content": "ok"}}

        return R()

    with patch("httpx.AsyncClient.post", new=fake_post):
        await caption_figure(b"\x00")
    assert calls == ["llava:7b"]


@pytest.mark.asyncio
async def test_caption_returns_placeholder_when_disabled(monkeypatch):
    monkeypatch.setattr("config.settings.vision_captioning_enabled", False)
    out = await caption_figure(b"\x00")
    assert out == "[FIGURE: no caption available]"


@pytest.mark.asyncio
async def test_caption_returns_placeholder_when_both_models_fail(monkeypatch):
    monkeypatch.setattr("config.settings.vlm_model_name", "primary:1")
    monkeypatch.setattr("config.settings.vlm_fallback_model_name", "fallback:1")
    monkeypatch.setattr("config.settings.vlm_force_fallback", False)
    monkeypatch.setattr("config.settings.vision_captioning_enabled", True)

    async def fake_post(self, url, json, **kw):
        raise httpx.ConnectError("network down")

    with patch("httpx.AsyncClient.post", new=fake_post):
        out = await caption_figure(b"\x00")
    assert out == "[FIGURE: no caption available]"
