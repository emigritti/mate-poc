"""Unit tests for GET /api/v1/admin/docs and GET /api/v1/admin/docs/{path}."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def test_list_docs_returns_manifest(client):
    """GET /api/v1/admin/docs returns status success and a non-empty list."""
    res = client.get("/api/v1/admin/docs")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    entries = data["data"]
    assert len(entries) == 19
    # Every entry has required keys
    for entry in entries:
        assert {"path", "name", "category", "description"} <= entry.keys()


def test_list_docs_all_categories_present(client):
    """Manifest covers all five expected categories."""
    res = client.get("/api/v1/admin/docs")
    categories = {e["category"] for e in res.json()["data"]}
    assert categories == {"Guide", "ADR", "Checklist", "Test Plan", "Mapping"}


def test_get_doc_returns_content(client, tmp_path, monkeypatch):
    """GET /api/v1/admin/docs/{path} returns file content when file exists."""
    import main
    fake_docs = tmp_path
    fake_file = fake_docs / "README.md"
    fake_file.write_text("# Hello", encoding="utf-8")
    monkeypatch.setattr(main, "DOCS_ROOT", fake_docs)

    res = client.get("/api/v1/admin/docs/README.md")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["data"]["content"] == "# Hello"
    assert body["data"]["path"] == "README.md"


def test_get_doc_404_when_missing(client, tmp_path, monkeypatch):
    """GET /api/v1/admin/docs/{path} returns 404 when file does not exist."""
    import main
    monkeypatch.setattr(main, "DOCS_ROOT", tmp_path)
    res = client.get("/api/v1/admin/docs/README.md")
    assert res.status_code == 404


def test_get_doc_rejects_non_md(client):
    """GET /api/v1/admin/docs/{path} rejects non-.md file extensions."""
    res = client.get("/api/v1/admin/docs/adr/something.txt")
    assert res.status_code == 400
    assert "Only .md" in res.json()["detail"]


def test_get_doc_path_traversal_blocked(client, tmp_path, monkeypatch):
    """Path traversal attempt (percent-encoded ../) is rejected with 400.

    Starlette normalizes bare '../' segments before they reach the handler, so
    the guard is exercised via a percent-encoded traversal sequence which
    Starlette passes through without normalisation.
    """
    import main
    monkeypatch.setattr(main, "DOCS_ROOT", tmp_path)
    res = client.get("/api/v1/admin/docs/%2e%2e%2fetc%2fpasswd.md")
    assert res.status_code == 400
    assert "Invalid document path" in res.json()["detail"]
