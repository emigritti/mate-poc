import pytest
from unittest.mock import AsyncMock
from services.contextual_retrieval_service import add_context_to_chunks
from document_parser import DoclingChunk


def _ch(t, idx=0):
    return DoclingChunk(
        text=t, chunk_type="text", page_num=1,
        section_header="S", index=idx, metadata={},
    )


@pytest.mark.asyncio
async def test_returns_unchanged_when_disabled(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", False)
    chunks = [_ch("hello")]
    out = await add_context_to_chunks("doc text", chunks)
    assert out == chunks


@pytest.mark.asyncio
async def test_uses_ollama_when_no_claude_key(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", True)
    monkeypatch.setattr("config.settings.contextual_provider", "claude")
    monkeypatch.setattr("config.settings.anthropic_api_key", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    fake_ollama = AsyncMock(return_value="situating phrase")
    monkeypatch.setattr(
        "services.contextual_retrieval_service._call_ollama_for_context", fake_ollama,
    )
    out = await add_context_to_chunks("FULL DOC", [_ch("chunk-x")])
    assert "situating phrase" in out[0].text
    assert "chunk-x" in out[0].text
    fake_ollama.assert_awaited()


@pytest.mark.asyncio
async def test_claude_call_uses_cache_control(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", True)
    monkeypatch.setattr("config.settings.contextual_provider", "claude")
    monkeypatch.setattr("config.settings.anthropic_api_key", "sk-test")

    captured = {}

    class FakeMsg:
        content = [type("T", (), {"text": "situating ctx"})()]

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        class messages:
            @staticmethod
            def create(**kw):
                captured.update(kw)
                return FakeMsg()

    monkeypatch.setattr("anthropic.Anthropic", FakeClient)
    out = await add_context_to_chunks("DOC", [_ch("c")])
    sys_blocks = captured["system"]
    assert any(b.get("cache_control", {}).get("type") == "ephemeral" for b in sys_blocks)
    assert "situating ctx" in out[0].text


@pytest.mark.asyncio
async def test_failure_returns_original_chunks(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", True)
    monkeypatch.setattr("config.settings.contextual_provider", "claude")
    monkeypatch.setattr("config.settings.anthropic_api_key", "sk")

    class Boom:
        def __init__(self, *a, **k):
            pass

        class messages:
            @staticmethod
            def create(**kw):
                raise RuntimeError("anthropic down")

    monkeypatch.setattr("anthropic.Anthropic", Boom)

    monkeypatch.setattr(
        "services.contextual_retrieval_service._call_ollama_for_context",
        AsyncMock(side_effect=RuntimeError("ollama down")),
    )
    chunks = [_ch("x")]
    out = await add_context_to_chunks("DOC", chunks)
    assert out == chunks   # graceful — never crashes ingestion


@pytest.mark.asyncio
async def test_empty_chunk_list_returns_immediately(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", True)
    out = await add_context_to_chunks("doc", [])
    assert out == []
