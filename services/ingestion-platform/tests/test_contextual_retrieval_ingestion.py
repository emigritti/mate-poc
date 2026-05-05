"""ADR-X4 — ingestion-platform contextual retrieval service unit tests."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from models.capability import CanonicalChunk, CapabilityKind


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_chunks(n: int = 3) -> list[CanonicalChunk]:
    return [
        CanonicalChunk(
            text=f"chunk text {i}",
            index=i,
            source_code="test_api",
            source_type="openapi",
            capability_kind=CapabilityKind.ENDPOINT,
        )
        for i in range(n)
    ]


# ── add_context_to_chunks — disabled ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_disabled_returns_chunks_unchanged(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", False)
    from services.contextual_retrieval_service import add_context_to_chunks

    chunks = _make_chunks(3)
    result = await add_context_to_chunks("doc text", chunks)

    assert result is chunks  # exact same object, no copy


@pytest.mark.asyncio
async def test_empty_chunks_returns_empty(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", True)
    from services.contextual_retrieval_service import add_context_to_chunks

    result = await add_context_to_chunks("doc text", [])
    assert result == []


# ── add_context_to_chunks — Ollama provider ───────────────────────────────────

@pytest.mark.asyncio
async def test_ollama_provider_annotates_chunks(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", True)
    monkeypatch.setattr("config.settings.contextual_provider", "ollama")

    from services import contextual_retrieval_service as svc

    async def _fake_ollama(doc_text: str, chunk_text: str) -> str:
        return f"Situating: {chunk_text[:20]}"

    monkeypatch.setattr(svc, "_call_ollama_for_context", _fake_ollama)

    chunks = _make_chunks(2)
    result = await svc.add_context_to_chunks("full doc", chunks)

    assert len(result) == 2
    for r in result:
        assert "<situating>" in r.text
        assert "<original>" in r.text
    # non-text fields preserved
    assert result[0].source_code == "test_api"
    assert result[0].index == 0


# ── add_context_to_chunks — Claude provider ───────────────────────────────────

@pytest.mark.asyncio
async def test_claude_provider_annotates_chunks(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", True)
    monkeypatch.setattr("config.settings.contextual_provider", "claude")

    # Fake a valid API key so the service tries Claude
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setattr("config.settings.anthropic_api_key", "sk-fake")

    from services import contextual_retrieval_service as svc

    # Mock anthropic client construction
    fake_client = MagicMock()
    with patch.object(svc, "_call_claude_for_context", new=AsyncMock(return_value="Claude annotation")):
        with patch("anthropic.Anthropic", return_value=fake_client):
            chunks = _make_chunks(2)
            result = await svc.add_context_to_chunks("full doc", chunks)

    assert len(result) == 2
    assert "<situating>" in result[0].text
    assert "Claude annotation" in result[0].text


# ── Graceful failure ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ollama_failure_keeps_original_chunk(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", True)
    monkeypatch.setattr("config.settings.contextual_provider", "ollama")

    from services import contextual_retrieval_service as svc

    async def _failing_ollama(doc_text: str, chunk_text: str) -> str:
        raise RuntimeError("Ollama unreachable")

    monkeypatch.setattr(svc, "_call_ollama_for_context", _failing_ollama)

    chunks = _make_chunks(2)
    result = await svc.add_context_to_chunks("full doc", chunks)

    # All original chunks preserved
    assert len(result) == 2
    assert result[0].text == "chunk text 0"
    assert result[1].text == "chunk text 1"


# ── model_copy preserves other fields ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_annotated_chunk_preserves_metadata_fields(monkeypatch):
    monkeypatch.setattr("config.settings.contextual_retrieval_enabled", True)
    monkeypatch.setattr("config.settings.contextual_provider", "ollama")

    from services import contextual_retrieval_service as svc

    async def _fake_ollama(doc_text: str, chunk_text: str) -> str:
        return "This is the overview section."

    monkeypatch.setattr(svc, "_call_ollama_for_context", _fake_ollama)

    chunk = CanonicalChunk(
        text="original text",
        index=5,
        source_code="my_api",
        source_type="html",
        capability_kind=CapabilityKind.GUIDE_STEP,
        section_header="Getting Started",
        tags=["auth", "guide"],
        confidence=0.9,
    )
    result = await svc.add_context_to_chunks("full doc", [chunk])

    r = result[0]
    assert r.index == 5
    assert r.source_code == "my_api"
    assert r.source_type == "html"
    assert r.capability_kind == CapabilityKind.GUIDE_STEP
    assert r.section_header == "Getting Started"
    assert r.tags == ["auth", "guide"]
    assert r.confidence == 0.9
    assert "original text" in r.text
