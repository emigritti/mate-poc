"""Tests for tag suggestion logic (Task 2 + Task 3)."""
import pytest
from schemas import Requirement


# ── Helpers ──────────────────────────────────────────────────────────────────
def _make_req(category: str, source: str = "ERP", target: str = "PLM") -> Requirement:
    return Requirement(
        req_id="R-001", source_system=source, target_system=target,
        category=category, description="test req",
    )


# ── Task 2: category extraction ───────────────────────────────────────────────
def test_extract_category_tags_unique():
    from main import _extract_category_tags
    reqs = [_make_req("Sync"), _make_req("Sync"), _make_req("Enrichment")]
    tags = _extract_category_tags(reqs)
    assert tags == ["Sync", "Enrichment"]  # unique, order-preserving


def test_extract_category_tags_empty():
    from main import _extract_category_tags
    assert _extract_category_tags([]) == []


def test_extract_category_tags_strips_whitespace():
    from main import _extract_category_tags
    reqs = [_make_req("  Sync  "), _make_req("Sync")]
    tags = _extract_category_tags(reqs)
    assert tags == ["Sync"]


def test_extract_category_tags_max_5():
    from main import _extract_category_tags
    reqs = [_make_req(f"Cat{i}") for i in range(10)]
    tags = _extract_category_tags(reqs)
    assert len(tags) <= 5


# ── Task 3: LLM tag suggestion ────────────────────────────────────────────────
import asyncio
from unittest.mock import AsyncMock, patch


def test_suggest_tags_via_llm_valid_json(monkeypatch):
    from main import _suggest_tags_via_llm
    monkeypatch.setattr(
        "main.generate_with_ollama",
        AsyncMock(return_value='["Data Sync", "Real-time"]'),
    )
    result = asyncio.run(_suggest_tags_via_llm("ERP", "PLM", "sync products daily"))
    assert result == ["Data Sync", "Real-time"]


def test_suggest_tags_via_llm_malformed_json(monkeypatch):
    from main import _suggest_tags_via_llm
    monkeypatch.setattr(
        "main.generate_with_ollama",
        AsyncMock(return_value="Sure! Tags are: Sync, Export"),
    )
    result = asyncio.run(_suggest_tags_via_llm("ERP", "PLM", "sync products"))
    assert result == []   # graceful fallback on parse failure


def test_suggest_tags_via_llm_exception(monkeypatch):
    from main import _suggest_tags_via_llm
    monkeypatch.setattr(
        "main.generate_with_ollama",
        AsyncMock(side_effect=Exception("Ollama timeout")),
    )
    result = asyncio.run(_suggest_tags_via_llm("ERP", "PLM", "sync products"))
    assert result == []   # never raises


def test_suggest_tags_via_llm_max_2(monkeypatch):
    from main import _suggest_tags_via_llm
    monkeypatch.setattr(
        "main.generate_with_ollama",
        AsyncMock(return_value='["A", "B", "C", "D"]'),
    )
    result = asyncio.run(_suggest_tags_via_llm("ERP", "PLM", "sync products"))
    assert len(result) <= 2


def test_suggest_tags_via_llm_passes_tag_settings(monkeypatch):
    """_suggest_tags_via_llm must forward tag-specific settings as kwargs."""
    from main import _suggest_tags_via_llm
    from config import settings

    captured_kwargs: dict = {}

    async def _mock(prompt, *, num_predict=None, timeout=None, temperature=None):
        captured_kwargs["num_predict"]  = num_predict
        captured_kwargs["timeout"]      = timeout
        captured_kwargs["temperature"]  = temperature
        return '["Data Sync"]'

    monkeypatch.setattr("main.generate_with_ollama", _mock)
    asyncio.run(_suggest_tags_via_llm("ERP", "PLM", "sync products"))

    assert captured_kwargs["num_predict"] == settings.tag_num_predict
    assert captured_kwargs["timeout"]     == settings.tag_timeout_seconds
    assert captured_kwargs["temperature"] == settings.tag_temperature
