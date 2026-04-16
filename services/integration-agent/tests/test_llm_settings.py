"""Unit tests for GET/PATCH/POST /api/v1/admin/llm-settings."""
import asyncio

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_overrides():
    """Ensure _llm_overrides is clean before and after each test."""
    import main
    main._llm_overrides.clear()
    yield
    main._llm_overrides.clear()


def test_get_llm_settings_returns_defaults(client):
    """GET returns effective == defaults when no overrides are set."""
    res = client.get("/api/v1/admin/llm-settings")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["data"]["overrides_active"] is False
    assert data["data"]["effective"]["doc_llm"] == data["data"]["defaults"]["doc_llm"]
    assert data["data"]["effective"]["tag_llm"] == data["data"]["defaults"]["tag_llm"]


def test_get_llm_settings_structure(client):
    """Response contains expected keys in both doc_llm and tag_llm groups."""
    data = client.get("/api/v1/admin/llm-settings").json()["data"]
    # ADR-046: num_ctx / top_p / top_k / repeat_penalty added
    assert set(data["effective"]["doc_llm"].keys()) == {
        "model", "num_predict", "timeout_seconds", "temperature", "rag_max_chars",
        "num_ctx", "top_p", "top_k", "repeat_penalty",
    }
    assert set(data["effective"]["tag_llm"].keys()) == {
        "num_predict", "timeout_seconds", "temperature"
    }


def test_patch_doc_llm_updates_effective(client):
    """PATCH doc_llm.temperature is reflected immediately in effective values."""
    res = client.patch(
        "/api/v1/admin/llm-settings",
        json={"doc_llm": {"temperature": 0.9}},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["effective"]["doc_llm"]["temperature"] == 0.9
    assert data["overrides_active"] is True


def test_patch_tag_llm_updates_effective(client):
    """PATCH tag_llm.timeout_seconds is reflected immediately."""
    res = client.patch(
        "/api/v1/admin/llm-settings",
        json={"tag_llm": {"timeout_seconds": 30}},
    )
    assert res.status_code == 200
    assert res.json()["data"]["effective"]["tag_llm"]["timeout_seconds"] == 30


def test_patch_unknown_field_ignored(client):
    """PATCH with an unknown field is silently ignored — no effect, no crash."""
    res = client.patch(
        "/api/v1/admin/llm-settings",
        json={"doc_llm": {"unknown_field": 999}},
    )
    assert res.status_code == 200
    # No valid field was set, so overrides_active stays False
    assert res.json()["data"]["overrides_active"] is False


def test_reset_clears_overrides(client):
    """POST /reset clears all overrides and restores defaults."""
    # First set an override
    client.patch("/api/v1/admin/llm-settings", json={"doc_llm": {"temperature": 0.9}})
    # Verify the override is active
    assert client.get("/api/v1/admin/llm-settings").json()["data"]["overrides_active"] is True
    # Now reset
    res = client.post("/api/v1/admin/llm-settings/reset")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["overrides_active"] is False
    assert data["effective"]["doc_llm"] == data["defaults"]["doc_llm"]


def test_overrides_applied_to_generate_with_ollama(monkeypatch):
    """_llm_overrides values are used by generate_with_ollama over settings defaults."""
    import main
    captured = {}

    async def _mock_post(self, url, *, json=None, **kwargs):
        captured["num_predict"] = json["options"]["num_predict"]
        captured["temperature"] = json["options"]["temperature"]
        captured["model"] = json["model"]

        class _R:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "response": "ok",
                    "eval_count": 1,
                    "eval_duration": 1_000_000_000,
                    "total_duration": 1_000_000_000,
                    "load_duration": 0,
                    "prompt_eval_count": 10,
                }

        return _R()

    monkeypatch.setattr("httpx.AsyncClient.post", _mock_post)
    main._llm_overrides["num_predict"] = 42
    main._llm_overrides["temperature"] = 0.99
    main._llm_overrides["timeout_seconds"] = 5

    asyncio.run(main.generate_with_ollama("hello"))

    assert captured["num_predict"] == 42
    assert captured["temperature"] == 0.99
