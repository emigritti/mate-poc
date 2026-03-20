"""Tests for tag suggestion logic (Task 2 + Task 3).

Updated for R15 refactoring: functions moved to services.tag_service.
"""
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
    from services.tag_service import extract_category_tags
    reqs = [_make_req("Sync"), _make_req("Sync"), _make_req("Enrichment")]
    tags = extract_category_tags(reqs)
    assert tags == ["Sync", "Enrichment"]  # unique, order-preserving


def test_extract_category_tags_empty():
    from services.tag_service import extract_category_tags
    assert extract_category_tags([]) == []


def test_extract_category_tags_strips_whitespace():
    from services.tag_service import extract_category_tags
    reqs = [_make_req("  Sync  "), _make_req("Sync")]
    tags = extract_category_tags(reqs)
    assert tags == ["Sync"]


def test_extract_category_tags_max_5():
    from services.tag_service import extract_category_tags
    reqs = [_make_req(f"Cat{i}") for i in range(10)]
    tags = extract_category_tags(reqs)
    assert len(tags) <= 5


# ── Task 3: LLM tag suggestion ────────────────────────────────────────────────
import asyncio
from unittest.mock import AsyncMock, patch


def test_suggest_tags_via_llm_valid_json(monkeypatch):
    from services.tag_service import suggest_tags_via_llm
    monkeypatch.setattr(
        "services.tag_service.generate_with_ollama",
        AsyncMock(return_value='["Data Sync", "Real-time"]'),
    )
    result = asyncio.run(suggest_tags_via_llm("ERP", "PLM", "sync products daily"))
    assert result == ["Data Sync", "Real-time"]


def test_suggest_tags_via_llm_malformed_json(monkeypatch):
    from services.tag_service import suggest_tags_via_llm
    monkeypatch.setattr(
        "services.tag_service.generate_with_ollama",
        AsyncMock(return_value="Sure! Tags are: Sync, Export"),
    )
    result = asyncio.run(suggest_tags_via_llm("ERP", "PLM", "sync products"))
    assert result == []   # graceful fallback on parse failure


def test_suggest_tags_via_llm_exception(monkeypatch):
    from services.tag_service import suggest_tags_via_llm
    monkeypatch.setattr(
        "services.tag_service.generate_with_ollama",
        AsyncMock(side_effect=Exception("Ollama timeout")),
    )
    result = asyncio.run(suggest_tags_via_llm("ERP", "PLM", "sync products"))
    assert result == []   # never raises


def test_suggest_tags_via_llm_max_2(monkeypatch):
    from services.tag_service import suggest_tags_via_llm
    monkeypatch.setattr(
        "services.tag_service.generate_with_ollama",
        AsyncMock(return_value='["A", "B", "C", "D"]'),
    )
    result = asyncio.run(suggest_tags_via_llm("ERP", "PLM", "sync products"))
    assert len(result) <= 2


def test_suggest_tags_via_llm_passes_tag_settings(monkeypatch):
    """suggest_tags_via_llm must forward tag-specific settings as kwargs."""
    from services.tag_service import suggest_tags_via_llm
    from config import settings

    captured_kwargs: dict = {}

    async def _mock(prompt, *, num_predict=None, timeout=None, temperature=None, log_fn=None):
        captured_kwargs["num_predict"]  = num_predict
        captured_kwargs["timeout"]      = timeout
        captured_kwargs["temperature"]  = temperature
        return '["Data Sync"]'

    monkeypatch.setattr("services.tag_service.generate_with_ollama", _mock)
    asyncio.run(suggest_tags_via_llm("ERP", "PLM", "sync products"))

    assert captured_kwargs["num_predict"] == settings.tag_num_predict
    assert captured_kwargs["timeout"]     == settings.tag_timeout_seconds
    assert captured_kwargs["temperature"] == settings.tag_temperature


# ── suggest_kb_tags_via_llm ───────────────────────────────────────────────────

def test_suggest_kb_tags_valid_json(monkeypatch):
    """suggest_kb_tags_via_llm returns parsed tags from valid JSON array."""
    from services.tag_service import suggest_kb_tags_via_llm
    monkeypatch.setattr(
        "services.tag_service.generate_with_ollama",
        AsyncMock(return_value='["Data Mapping", "Integration Pattern", "Error Handling"]'),
    )
    result = asyncio.run(suggest_kb_tags_via_llm("Best practice content", "guide.md"))
    assert result == ["Data Mapping", "Integration Pattern", "Error Handling"]


def test_suggest_kb_tags_max_3(monkeypatch):
    """suggest_kb_tags_via_llm enforces a maximum of 3 tags."""
    from services.tag_service import suggest_kb_tags_via_llm
    monkeypatch.setattr(
        "services.tag_service.generate_with_ollama",
        AsyncMock(return_value='["A", "B", "C", "D", "E"]'),
    )
    result = asyncio.run(suggest_kb_tags_via_llm("content", "file.md"))
    assert len(result) <= 3


def test_suggest_kb_tags_truncates_at_50_chars(monkeypatch):
    """Each tag is truncated to 50 characters."""
    from services.tag_service import suggest_kb_tags_via_llm
    long_tag = "A" * 100
    monkeypatch.setattr(
        "services.tag_service.generate_with_ollama",
        AsyncMock(return_value=f'["{long_tag}"]'),
    )
    result = asyncio.run(suggest_kb_tags_via_llm("content", "file.md"))
    assert len(result) == 1
    assert len(result[0]) == 50


def test_suggest_kb_tags_malformed_json_returns_empty(monkeypatch):
    """suggest_kb_tags_via_llm returns [] when LLM response is not a JSON array."""
    from services.tag_service import suggest_kb_tags_via_llm
    monkeypatch.setattr(
        "services.tag_service.generate_with_ollama",
        AsyncMock(return_value="Here are some tags: Best Practice, REST"),
    )
    result = asyncio.run(suggest_kb_tags_via_llm("content", "file.md"))
    assert result == []


def test_suggest_kb_tags_exception_returns_empty(monkeypatch):
    """suggest_kb_tags_via_llm returns [] on any exception — never raises."""
    from services.tag_service import suggest_kb_tags_via_llm
    monkeypatch.setattr(
        "services.tag_service.generate_with_ollama",
        AsyncMock(side_effect=Exception("LLM unavailable")),
    )
    result = asyncio.run(suggest_kb_tags_via_llm("content", "file.md"))
    assert result == []
