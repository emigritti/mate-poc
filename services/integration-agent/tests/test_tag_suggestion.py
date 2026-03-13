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
