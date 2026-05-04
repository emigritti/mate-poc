import asyncio
import pytest
from unittest.mock import patch
from services.llm_judge_service import llm_judge_rerank
from services.retriever import ScoredChunk


def _mk(t, doc_id=None):
    return ScoredChunk(text=t, score=0.5, source_label="x", tags=[], doc_id=doc_id or t)


def _run(coro):
    return asyncio.run(coro)


def test_llm_judge_returns_input_when_disabled(monkeypatch):
    monkeypatch.setattr("config.settings.llm_judge_enabled", False)
    chunks = [_mk("a"), _mk("b")]
    out = _run(llm_judge_rerank("q", chunks))
    assert out == chunks


def test_llm_judge_returns_input_when_no_key(monkeypatch):
    monkeypatch.setattr("config.settings.llm_judge_enabled", True)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("config.settings.anthropic_api_key", None)
    chunks = [_mk("a"), _mk("b")]
    assert _run(llm_judge_rerank("q", chunks)) == chunks


def test_llm_judge_sends_cache_control_on_system_blocks(monkeypatch):
    monkeypatch.setattr("config.settings.llm_judge_enabled", True)
    monkeypatch.setattr("config.settings.anthropic_api_key", "sk-test")

    captured = {}

    class FakeMsg:
        content = [type("X", (), {"text": '[{"idx":1,"score":0.9},{"idx":0,"score":0.3}]'})()]

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        class messages:
            @staticmethod
            def create(**kwargs):
                captured.update(kwargs)
                return FakeMsg()

    monkeypatch.setattr("anthropic.Anthropic", FakeClient)

    chunks = [_mk("a"), _mk("b")]
    out = _run(llm_judge_rerank("q", chunks))
    assert out[0].text == "b"  # idx=1 had higher score
    sys_blocks = captured["system"]
    assert any(b.get("cache_control", {}).get("type") == "ephemeral" for b in sys_blocks)


def test_llm_judge_falls_back_to_input_on_api_error(monkeypatch):
    """If Anthropic call raises, return input chunks unchanged."""
    monkeypatch.setattr("config.settings.llm_judge_enabled", True)
    monkeypatch.setattr("config.settings.anthropic_api_key", "sk-test")

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("anthropic down")

    monkeypatch.setattr("anthropic.Anthropic", FakeClient)
    chunks = [_mk("a"), _mk("b")]
    out = _run(llm_judge_rerank("q", chunks))
    assert out == chunks


def test_llm_judge_returns_input_on_unparseable_response(monkeypatch):
    """Non-JSON LLM response → graceful fallback."""
    monkeypatch.setattr("config.settings.llm_judge_enabled", True)
    monkeypatch.setattr("config.settings.anthropic_api_key", "sk-test")

    class FakeMsg:
        content = [type("X", (), {"text": "I cannot parse this question."})()]

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        class messages:
            @staticmethod
            def create(**kwargs):
                return FakeMsg()

    monkeypatch.setattr("anthropic.Anthropic", FakeClient)
    chunks = [_mk("a"), _mk("b")]
    out = _run(llm_judge_rerank("q", chunks))
    assert out == chunks
