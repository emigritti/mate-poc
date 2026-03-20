"""Tests for GET /api/v1/catalog/integrations/{id}/suggest-tags."""
import asyncio
import io
import pytest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture
def seeded_catalog(client):
    """Upload CSV + finalize to populate catalog with PENDING_TAG_REVIEW entries."""
    import main
    main.catalog.clear()
    main.parsed_requirements.clear()
    main.projects.clear()
    csv = (
        "ReqID,Source,Target,Category,Description\n"
        "REQ-101,ERP,PLM,Product Collection,Sync articles.\n"
        "REQ-102,ERP,PLM,Enrichment INIT,Init product in PLM.\n"
    )
    client.post(
        "/api/v1/requirements/upload",
        files={"file": ("reqs.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    client.post("/api/v1/projects", json={"prefix": "TST", "client_name": "Test Corp", "domain": "Testing"})
    client.post("/api/v1/requirements/finalize", json={"project_id": "TST"})
    return list(main.catalog.keys())[0]


def test_suggest_tags_returns_category_tags(client, seeded_catalog, monkeypatch):
    monkeypatch.setattr(
        "routers.catalog.suggest_tags_via_llm",
        AsyncMock(return_value=[]),
    )
    resp = client.get(f"/api/v1/catalog/integrations/{seeded_catalog}/suggest-tags")
    assert resp.status_code == 200
    data = resp.json()
    assert "Product Collection" in data["suggested_tags"]
    assert "Enrichment INIT" in data["suggested_tags"]


def test_suggest_tags_merges_llm_tags(client, seeded_catalog, monkeypatch):
    monkeypatch.setattr(
        "routers.catalog.suggest_tags_via_llm",
        AsyncMock(return_value=["Data Sync"]),
    )
    resp = client.get(f"/api/v1/catalog/integrations/{seeded_catalog}/suggest-tags")
    assert resp.status_code == 200
    data = resp.json()
    assert "Data Sync" in data["suggested_tags"]


def test_suggest_tags_no_duplicates(client, seeded_catalog, monkeypatch):
    monkeypatch.setattr(
        "routers.catalog.suggest_tags_via_llm",
        AsyncMock(return_value=["Product Collection"]),  # duplicate
    )
    resp = client.get(f"/api/v1/catalog/integrations/{seeded_catalog}/suggest-tags")
    tags = resp.json()["suggested_tags"]
    assert len(tags) == len(set(tags))


def test_suggest_tags_not_found(client):
    resp = client.get("/api/v1/catalog/integrations/NONEXISTENT/suggest-tags")
    assert resp.status_code == 404
