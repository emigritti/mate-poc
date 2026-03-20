"""Unit tests for GET /api/v1/admin/docs and GET /api/v1/admin/docs/{path}."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from main import DOCS_MANIFEST


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
    assert len(entries) == len(DOCS_MANIFEST)
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
    import routers.admin as admin_mod
    fake_docs = tmp_path
    fake_file = fake_docs / "README.md"
    fake_file.write_text("# Hello", encoding="utf-8")
    monkeypatch.setattr(admin_mod, "DOCS_ROOT", fake_docs)

    res = client.get("/api/v1/admin/docs/README.md")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["data"]["content"] == "# Hello"
    assert body["data"]["path"] == "README.md"


def test_get_doc_404_when_missing(client, tmp_path, monkeypatch):
    """GET /api/v1/admin/docs/{path} returns 404 when file does not exist."""
    import routers.admin as admin_mod
    monkeypatch.setattr(admin_mod, "DOCS_ROOT", tmp_path)
    res = client.get("/api/v1/admin/docs/README.md")
    assert res.status_code == 404


def test_get_doc_rejects_non_md(client):
    """GET /api/v1/admin/docs/{path} rejects non-.md file extensions."""
    res = client.get("/api/v1/admin/docs/adr/something.txt")
    assert res.status_code == 400
    assert "Only .md" in res.json()["detail"]


def test_get_doc_path_traversal_blocked(client, tmp_path, monkeypatch):
    """Path traversal attempt (percent-encoded ../) is rejected.

    The manifest allow-list rejects any path not explicitly listed, so traversal
    paths (e.g. ../../etc/passwd.md) are blocked with 404 before any filesystem
    access occurs.
    """
    import routers.admin as admin_mod
    monkeypatch.setattr(admin_mod, "DOCS_ROOT", tmp_path)
    res = client.get("/api/v1/admin/docs/%2e%2e%2fetc%2fpasswd.md")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_list_docs_no_auth_required_when_api_key_unset(client):
    """When API_KEY env var is unset, _require_token is a no-op and docs are accessible.

    conftest.py pops API_KEY so settings.api_key is None → _require_token bypasses
    auth enforcement in tests (PoC dev mode).
    """
    # conftest.py pops API_KEY so settings.api_key is None → auth bypassed in tests
    res = client.get("/api/v1/admin/docs")
    assert res.status_code == 200
