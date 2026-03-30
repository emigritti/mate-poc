"""
Unit tests for technical design document generation.
ADR-038: Two-phase doc generation — technical spec after functional approval.
"""
import pytest
from schemas import CatalogEntry


def test_catalog_entry_has_technical_status_field():
    entry = CatalogEntry(
        id="TEST-001",
        name="Test Integration",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        created_at="2026-03-30T00:00:00Z",
    )
    assert hasattr(entry, "technical_status")
    assert entry.technical_status is None


def test_catalog_entry_technical_status_can_be_set():
    entry = CatalogEntry(
        id="TEST-001",
        name="Test Integration",
        type="data_sync",
        source={"system": "PLM"},
        target={"system": "PIM"},
        requirements=["REQ-001"],
        status="DONE",
        technical_status="TECH_PENDING",
        created_at="2026-03-30T00:00:00Z",
    )
    assert entry.technical_status == "TECH_PENDING"
