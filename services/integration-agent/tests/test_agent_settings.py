"""Unit tests for GET/PATCH/POST /api/v1/admin/agent-settings."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_overrides():
    """Clean agent_settings_overrides and restore defaults before/after each test."""
    from routers.admin import agent_settings_overrides, _apply_agent_overrides, _AGENT_SETTINGS_DEFAULTS
    agent_settings_overrides.clear()
    _apply_agent_overrides(_AGENT_SETTINGS_DEFAULTS)
    yield
    agent_settings_overrides.clear()
    _apply_agent_overrides(_AGENT_SETTINGS_DEFAULTS)


# ── GET ───────────────────────────────────────────────────────────────────────

def test_get_returns_200(client):
    res = client.get("/api/v1/admin/agent-settings")
    assert res.status_code == 200
    assert res.json()["status"] == "success"


def test_get_returns_effective_defaults_overrides_keys(client):
    data = client.get("/api/v1/admin/agent-settings").json()["data"]
    assert "effective" in data
    assert "defaults" in data
    assert "overrides_active" in data


def test_get_no_overrides_active_initially(client):
    data = client.get("/api/v1/admin/agent-settings").json()["data"]
    assert data["overrides_active"] is False


def test_get_effective_equals_defaults_initially(client):
    data = client.get("/api/v1/admin/agent-settings").json()["data"]
    assert data["effective"] == data["defaults"]


def test_get_contains_all_expected_keys(client):
    data = client.get("/api/v1/admin/agent-settings").json()["data"]
    expected_keys = {
        "quality_gate_mode", "quality_gate_min_score",
        "rag_distance_threshold", "rag_bm25_weight",
        "rag_n_results_per_query", "rag_top_k_chunks", "kb_max_rag_chars",
        "fact_pack_enabled", "fact_pack_max_tokens", "llm_max_output_chars",
        "vision_captioning_enabled", "raptor_summarization_enabled",
        "kb_max_summarize_sections", "kb_chunk_size", "kb_chunk_overlap",
    }
    assert set(data["effective"].keys()) == expected_keys
    assert set(data["defaults"].keys()) == expected_keys


# ── PATCH ─────────────────────────────────────────────────────────────────────

def test_patch_quality_gate_mode_warn_to_block(client):
    res = client.patch("/api/v1/admin/agent-settings", json={"quality_gate_mode": "block"})
    assert res.status_code == 200
    assert res.json()["data"]["effective"]["quality_gate_mode"] == "block"
    assert res.json()["data"]["overrides_active"] is True


def test_patch_quality_gate_min_score(client):
    res = client.patch("/api/v1/admin/agent-settings", json={"quality_gate_min_score": 0.75})
    assert res.status_code == 200
    assert res.json()["data"]["effective"]["quality_gate_min_score"] == 0.75


def test_patch_invalid_quality_gate_mode_returns_422(client):
    res = client.patch("/api/v1/admin/agent-settings", json={"quality_gate_mode": "invalid"})
    assert res.status_code == 422


def test_patch_rag_top_k_chunks(client):
    res = client.patch("/api/v1/admin/agent-settings", json={"rag_top_k_chunks": 10})
    assert res.status_code == 200
    assert res.json()["data"]["effective"]["rag_top_k_chunks"] == 10


def test_patch_fact_pack_enabled_false(client):
    res = client.patch("/api/v1/admin/agent-settings", json={"fact_pack_enabled": False})
    assert res.status_code == 200
    assert res.json()["data"]["effective"]["fact_pack_enabled"] is False


def test_patch_multiple_fields_at_once(client):
    res = client.patch("/api/v1/admin/agent-settings", json={
        "quality_gate_mode": "block",
        "quality_gate_min_score": 0.80,
        "rag_top_k_chunks": 8,
        "fact_pack_enabled": False,
    })
    assert res.status_code == 200
    eff = res.json()["data"]["effective"]
    assert eff["quality_gate_mode"] == "block"
    assert eff["quality_gate_min_score"] == 0.80
    assert eff["rag_top_k_chunks"] == 8
    assert eff["fact_pack_enabled"] is False


def test_patch_applies_to_settings_object(client):
    """Overrides must be reflected on the live `settings` singleton (picked up by next agent run)."""
    from config import settings
    client.patch("/api/v1/admin/agent-settings", json={"quality_gate_min_score": 0.99})
    assert settings.quality_gate_min_score == 0.99


def test_patch_bool_vision_captioning(client):
    res = client.patch("/api/v1/admin/agent-settings", json={"vision_captioning_enabled": False})
    assert res.status_code == 200
    assert res.json()["data"]["effective"]["vision_captioning_enabled"] is False


def test_patch_overrides_do_not_affect_defaults(client):
    """After PATCH, defaults section must remain unchanged."""
    original_defaults = client.get("/api/v1/admin/agent-settings").json()["data"]["defaults"]
    client.patch("/api/v1/admin/agent-settings", json={"quality_gate_min_score": 0.99})
    new_data = client.get("/api/v1/admin/agent-settings").json()["data"]
    assert new_data["defaults"] == original_defaults


def test_patch_kb_chunking_params(client):
    res = client.patch("/api/v1/admin/agent-settings", json={"kb_chunk_size": 500, "kb_chunk_overlap": 100})
    assert res.status_code == 200
    eff = res.json()["data"]["effective"]
    assert eff["kb_chunk_size"] == 500
    assert eff["kb_chunk_overlap"] == 100


# ── POST /reset ───────────────────────────────────────────────────────────────

def test_reset_clears_overrides(client):
    client.patch("/api/v1/admin/agent-settings", json={"quality_gate_mode": "block"})
    assert client.get("/api/v1/admin/agent-settings").json()["data"]["overrides_active"] is True
    res = client.post("/api/v1/admin/agent-settings/reset")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["overrides_active"] is False
    assert data["effective"] == data["defaults"]


def test_reset_restores_settings_object(client):
    """After reset, `settings` object values must match original defaults."""
    from config import settings
    from routers.admin import _AGENT_SETTINGS_DEFAULTS
    client.patch("/api/v1/admin/agent-settings", json={"quality_gate_min_score": 0.99})
    client.post("/api/v1/admin/agent-settings/reset")
    assert settings.quality_gate_min_score == _AGENT_SETTINGS_DEFAULTS["quality_gate_min_score"]


def test_reset_idempotent_when_no_overrides(client):
    """Calling reset when no overrides are active must succeed without error."""
    res = client.post("/api/v1/admin/agent-settings/reset")
    assert res.status_code == 200
    assert res.json()["data"]["overrides_active"] is False
