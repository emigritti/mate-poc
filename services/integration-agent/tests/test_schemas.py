"""Tests for new schema fields and models (Task 1)."""
from schemas import CatalogEntry, ConfirmTagsRequest, SuggestTagsResponse


def test_catalog_entry_has_tags_field():
    entry = CatalogEntry(
        id="INT-001", name="A", type="Auto", source={"system": "ERP"},
        target={"system": "PLM"}, requirements=[], status="PENDING_TAG_REVIEW",
        created_at="2026-01-01T00:00:00Z",
    )
    assert entry.tags == []


def test_catalog_entry_tags_populated():
    entry = CatalogEntry(
        id="INT-001", name="A", type="Auto", source={"system": "ERP"},
        target={"system": "PLM"}, requirements=[], status="TAG_CONFIRMED",
        tags=["Sync", "PLM"], created_at="2026-01-01T00:00:00Z",
    )
    assert entry.tags == ["Sync", "PLM"]


def test_confirm_tags_request_valid():
    body = ConfirmTagsRequest(tags=["Sync", "PLM", "Custom"])
    assert body.tags == ["Sync", "PLM", "Custom"]


def test_confirm_tags_request_too_many():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ConfirmTagsRequest(tags=[f"Tag{i}" for i in range(16)])


def test_confirm_tags_request_empty_list():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ConfirmTagsRequest(tags=[])


def test_suggest_tags_response():
    r = SuggestTagsResponse(
        integration_id="INT-001",
        suggested_tags=["Sync", "PLM"],
        source={"from_categories": ["Sync"], "from_llm": ["PLM"]},
    )
    assert r.integration_id == "INT-001"
    assert len(r.suggested_tags) == 2
