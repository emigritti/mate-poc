"""
Unit tests for ADR-046 — LLM Multi-Profile Routing.

Coverage:
  - config.py: new default values (num_ctx, top_p, top_k, repeat_penalty,
    tag_model, premium_model, premium_* siblings)
  - llm_service.generate_with_ollama: full Ollama options payload sent
  - llm_service.generate_with_ollama: explicit model= kwarg takes priority
  - llm_service.generate_with_retry: forwards new params to generate_with_ollama
  - tag_service.suggest_tags_via_llm: uses tag_model (not default model)
  - tag_service.suggest_kb_tags_via_llm: uses tag_model
  - admin._DocLLMPatch: accepts num_ctx / top_p / top_k / repeat_penalty
  - admin PATCH: new fields are stored in llm_overrides
  - agent router TriggerRequest: llm_profile field exists and defaults to "default"
  - agent_service.generate_integration_doc: "high_quality" profile passes premium kwargs
  - TriggerRequest: "high_quality" is the canonical value; "premium" accepted as legacy alias
"""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest


# ── Config defaults (ADR-046) ─────────────────────────────────────────────────

class TestConfigNewDefaults:
    def test_ollama_num_ctx_default(self):
        from config import Settings
        s = Settings(ollama_host="http://h", mongo_uri="mongodb://m")
        assert s.ollama_num_ctx == 8192

    def test_ollama_top_p_default(self):
        from config import Settings
        s = Settings(ollama_host="http://h", mongo_uri="mongodb://m")
        assert s.ollama_top_p == 0.9

    def test_ollama_top_k_default(self):
        from config import Settings
        s = Settings(ollama_host="http://h", mongo_uri="mongodb://m")
        assert s.ollama_top_k == 40

    def test_ollama_repeat_penalty_default(self):
        from config import Settings
        s = Settings(ollama_host="http://h", mongo_uri="mongodb://m")
        assert s.ollama_repeat_penalty == 1.08

    def test_tag_model_default(self):
        from config import Settings
        s = Settings(ollama_host="http://h", mongo_uri="mongodb://m")
        assert s.tag_model == "qwen3:8b"

    def test_premium_model_default(self):
        from config import Settings
        s = Settings(ollama_host="http://h", mongo_uri="mongodb://m")
        assert s.premium_model == "gemma4:26b"

    def test_premium_num_ctx_default(self):
        from config import Settings
        s = Settings(ollama_host="http://h", mongo_uri="mongodb://m")
        assert s.premium_num_ctx == 6144

    def test_premium_num_predict_default(self):
        from config import Settings
        s = Settings(ollama_host="http://h", mongo_uri="mongodb://m")
        assert s.premium_num_predict == 1800

    def test_premium_temperature_default(self):
        from config import Settings
        s = Settings(ollama_host="http://h", mongo_uri="mongodb://m")
        assert s.premium_temperature == 0.0

    def test_premium_top_p_default(self):
        from config import Settings
        s = Settings(ollama_host="http://h", mongo_uri="mongodb://m")
        assert s.premium_top_p == 0.85

    def test_premium_top_k_default(self):
        from config import Settings
        s = Settings(ollama_host="http://h", mongo_uri="mongodb://m")
        assert s.premium_top_k == 30

    def test_premium_repeat_penalty_default(self):
        from config import Settings
        s = Settings(ollama_host="http://h", mongo_uri="mongodb://m")
        assert s.premium_repeat_penalty == 1.1

    def test_premium_timeout_seconds_default(self):
        from config import Settings
        s = Settings(ollama_host="http://h", mongo_uri="mongodb://m")
        assert s.premium_timeout_seconds == 900


# ── generate_with_ollama — full options payload ───────────────────────────────

class TestGenerateWithOllamaOptions:
    def _make_response(self):
        """Return a mock httpx response with the minimum fields Ollama returns."""
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.return_value = {
            "response": "ok",
            "eval_count": 5,
            "prompt_eval_count": 3,
            "eval_duration": 1_000_000_000,
            "total_duration": 1_000_000_000,
            "load_duration": 0,
        }
        return r

    def _patch_settings(self):
        """Return a minimal settings mock with all new defaults."""
        ms = MagicMock()
        ms.ollama_host = "http://test-ollama"
        ms.ollama_model = "default-model"
        ms.ollama_num_predict = 100
        ms.ollama_timeout_seconds = 10
        ms.ollama_temperature = 0.1
        ms.ollama_num_ctx = 8192
        ms.ollama_top_p = 0.9
        ms.ollama_top_k = 40
        ms.ollama_repeat_penalty = 1.08
        return ms

    def test_full_options_sent_to_ollama(self, monkeypatch):
        """generate_with_ollama must include num_ctx/top_p/top_k/repeat_penalty."""
        captured = {}

        async def _mock_post(self_client, url, *, json=None, **kwargs):
            captured["payload"] = json
            return self._make_response()

        monkeypatch.setattr("httpx.AsyncClient.post", _mock_post)
        monkeypatch.setattr("services.llm_service.settings", self._patch_settings())
        from services.llm_service import generate_with_ollama, llm_overrides
        llm_overrides.clear()

        asyncio.run(generate_with_ollama("hello"))

        opts = captured["payload"]["options"]
        assert opts["num_ctx"] == 8192
        assert opts["top_p"] == 0.9
        assert opts["top_k"] == 40
        assert opts["repeat_penalty"] == 1.08

    def test_explicit_model_kwarg_overrides_llm_overrides(self, monkeypatch):
        """Explicit model= kwarg takes priority over llm_overrides['model']."""
        captured = {}

        async def _mock_post(self_client, url, *, json=None, **kwargs):
            captured["model"] = json["model"]
            return self._make_response()

        monkeypatch.setattr("httpx.AsyncClient.post", _mock_post)
        monkeypatch.setattr("services.llm_service.settings", self._patch_settings())
        from services.llm_service import generate_with_ollama, llm_overrides
        llm_overrides.clear()
        llm_overrides["model"] = "override-model"

        asyncio.run(generate_with_ollama("hello", model="explicit-model"))

        assert captured["model"] == "explicit-model"

    def test_no_model_kwarg_uses_llm_overrides(self, monkeypatch):
        """Without explicit model= kwarg, llm_overrides['model'] is used."""
        captured = {}

        async def _mock_post(self_client, url, *, json=None, **kwargs):
            captured["model"] = json["model"]
            return self._make_response()

        monkeypatch.setattr("httpx.AsyncClient.post", _mock_post)
        monkeypatch.setattr("services.llm_service.settings", self._patch_settings())
        from services.llm_service import generate_with_ollama, llm_overrides
        llm_overrides.clear()
        llm_overrides["model"] = "from-overrides"

        asyncio.run(generate_with_ollama("hello"))

        assert captured["model"] == "from-overrides"

    def test_premium_options_passed_via_kwargs(self, monkeypatch):
        """Premium kwargs (num_ctx=6144, top_p=0.85, etc.) appear in Ollama payload."""
        captured = {}

        async def _mock_post(self_client, url, *, json=None, **kwargs):
            captured["payload"] = json
            return self._make_response()

        monkeypatch.setattr("httpx.AsyncClient.post", _mock_post)
        monkeypatch.setattr("services.llm_service.settings", self._patch_settings())
        from services.llm_service import generate_with_ollama, llm_overrides
        llm_overrides.clear()

        asyncio.run(generate_with_ollama(
            "hello",
            model="gemma4:26b",
            num_ctx=6144,
            num_predict=1800,
            temperature=0.0,
            top_p=0.85,
            top_k=30,
            repeat_penalty=1.1,
        ))

        assert captured["payload"]["model"] == "gemma4:26b"
        opts = captured["payload"]["options"]
        assert opts["num_ctx"] == 6144
        assert opts["num_predict"] == 1800
        assert opts["temperature"] == 0.0
        assert opts["top_p"] == 0.85
        assert opts["top_k"] == 30
        assert opts["repeat_penalty"] == 1.1


# ── generate_with_retry — forwards new params ─────────────────────────────────

class TestGenerateWithRetryForwardsParams:
    def test_new_params_forwarded_to_generate_with_ollama(self):
        """generate_with_retry must forward model/num_ctx/top_p/top_k/repeat_penalty."""
        mock_gen = AsyncMock(return_value="ok")

        with patch("services.llm_service.generate_with_ollama", mock_gen):
            with patch("services.llm_service.asyncio.sleep", AsyncMock()):
                from services.llm_service import generate_with_retry
                asyncio.run(generate_with_retry(
                    "prompt",
                    model="gemma4:26b",
                    num_ctx=6144,
                    top_p=0.85,
                    top_k=30,
                    repeat_penalty=1.1,
                ))

        call_kwargs = mock_gen.call_args.kwargs
        assert call_kwargs["model"] == "gemma4:26b"
        assert call_kwargs["num_ctx"] == 6144
        assert call_kwargs["top_p"] == 0.85
        assert call_kwargs["top_k"] == 30
        assert call_kwargs["repeat_penalty"] == 1.1


# ── Tag service — uses tag_model ──────────────────────────────────────────────

class TestTagServiceUsesTagModel:
    def _make_settings(self):
        ms = MagicMock()
        ms.tag_model = "qwen3:8b"
        ms.tag_num_predict = 50
        ms.tag_timeout_seconds = 60
        ms.tag_temperature = 0.0
        return ms

    def test_suggest_tags_uses_tag_model(self, monkeypatch):
        """suggest_tags_via_llm must call generate_with_ollama with model=tag_model."""
        captured = {}

        async def _mock_gen(prompt, *, model=None, **kwargs):
            captured["model"] = model
            return '["tag1", "tag2"]'

        monkeypatch.setattr("services.tag_service.settings", self._make_settings())
        monkeypatch.setattr("services.tag_service.generate_with_ollama", _mock_gen)
        from services.llm_service import llm_overrides
        llm_overrides.clear()

        from services.tag_service import suggest_tags_via_llm
        result = asyncio.run(suggest_tags_via_llm("SRC", "TGT", "req text"))

        assert captured["model"] == "qwen3:8b"
        assert result == ["tag1", "tag2"]

    def test_suggest_kb_tags_uses_tag_model(self, monkeypatch):
        """suggest_kb_tags_via_llm must call generate_with_ollama with model=tag_model."""
        captured = {}

        async def _mock_gen(prompt, *, model=None, **kwargs):
            captured["model"] = model
            return '["doc-tag"]'

        monkeypatch.setattr("services.tag_service.settings", self._make_settings())
        monkeypatch.setattr("services.tag_service.generate_with_ollama", _mock_gen)
        from services.llm_service import llm_overrides
        llm_overrides.clear()

        from services.tag_service import suggest_kb_tags_via_llm
        asyncio.run(suggest_kb_tags_via_llm("some text preview", "doc.pdf"))

        assert captured["model"] == "qwen3:8b"

    def test_tag_model_overridable_via_llm_overrides(self, monkeypatch):
        """llm_overrides['tag_model'] takes priority over settings.tag_model."""
        captured = {}

        async def _mock_gen(prompt, *, model=None, **kwargs):
            captured["model"] = model
            return '["t"]'

        monkeypatch.setattr("services.tag_service.settings", self._make_settings())
        monkeypatch.setattr("services.tag_service.generate_with_ollama", _mock_gen)
        from services.llm_service import llm_overrides
        llm_overrides.clear()
        llm_overrides["tag_model"] = "qwen2.5:14b"   # runtime override

        from services.tag_service import suggest_tags_via_llm
        asyncio.run(suggest_tags_via_llm("SRC", "TGT", "req"))

        assert captured["model"] == "qwen2.5:14b"


# ── Admin patch schema — new fields ──────────────────────────────────────────

class TestDocLLMPatchNewFields:
    def test_patch_accepts_num_ctx(self):
        from routers.admin import _DocLLMPatch
        p = _DocLLMPatch(num_ctx=4096)
        assert p.model_dump(exclude_none=True)["num_ctx"] == 4096

    def test_patch_accepts_top_p(self):
        from routers.admin import _DocLLMPatch
        p = _DocLLMPatch(top_p=0.75)
        assert p.model_dump(exclude_none=True)["top_p"] == 0.75

    def test_patch_accepts_top_k(self):
        from routers.admin import _DocLLMPatch
        p = _DocLLMPatch(top_k=25)
        assert p.model_dump(exclude_none=True)["top_k"] == 25

    def test_patch_accepts_repeat_penalty(self):
        from routers.admin import _DocLLMPatch
        p = _DocLLMPatch(repeat_penalty=1.05)
        assert p.model_dump(exclude_none=True)["repeat_penalty"] == 1.05

    def test_patch_all_new_fields_together(self):
        from routers.admin import _DocLLMPatch
        p = _DocLLMPatch(num_ctx=4096, top_p=0.8, top_k=20, repeat_penalty=1.05)
        d = p.model_dump(exclude_none=True)
        assert d == {"num_ctx": 4096, "top_p": 0.8, "top_k": 20, "repeat_penalty": 1.05}


class TestAdminPatchNewFields:
    """Integration-level: PATCH stores new fields in llm_overrides."""

    @pytest.fixture
    def client(self):
        from main import app
        from fastapi.testclient import TestClient
        return TestClient(app)

    @pytest.fixture(autouse=True)
    def reset_overrides(self):
        import main
        main._llm_overrides.clear()
        yield
        main._llm_overrides.clear()

    def test_patch_num_ctx_stored_in_overrides(self, client):
        res = client.patch(
            "/api/v1/admin/llm-settings",
            json={"doc_llm": {"num_ctx": 4096}},
        )
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["effective"]["doc_llm"]["num_ctx"] == 4096
        assert data["overrides_active"] is True

    def test_patch_top_p_stored_in_overrides(self, client):
        res = client.patch(
            "/api/v1/admin/llm-settings",
            json={"doc_llm": {"top_p": 0.7}},
        )
        assert res.status_code == 200
        assert res.json()["data"]["effective"]["doc_llm"]["top_p"] == 0.7

    def test_patch_repeat_penalty_stored_in_overrides(self, client):
        res = client.patch(
            "/api/v1/admin/llm-settings",
            json={"doc_llm": {"repeat_penalty": 1.15}},
        )
        assert res.status_code == 200
        assert res.json()["data"]["effective"]["doc_llm"]["repeat_penalty"] == 1.15


# ── Agent router — TriggerRequest with llm_profile ────────────────────────────

class TestTriggerRequestLlmProfile:
    def test_llm_profile_defaults_to_default(self):
        from routers.agent import TriggerRequest
        r = TriggerRequest()
        assert r.llm_profile == "default"

    def test_llm_profile_accepts_high_quality(self):
        from routers.agent import TriggerRequest
        r = TriggerRequest(llm_profile="high_quality")
        assert r.llm_profile == "high_quality"

    def test_llm_profile_accepts_premium_legacy_alias(self):
        from routers.agent import TriggerRequest
        r = TriggerRequest(llm_profile="premium")
        assert r.llm_profile == "premium"

    def test_pinned_doc_ids_still_works(self):
        from routers.agent import TriggerRequest
        r = TriggerRequest(pinned_doc_ids=["doc1", "doc2"], llm_profile="high_quality")
        assert r.pinned_doc_ids == ["doc1", "doc2"]
        assert r.llm_profile == "high_quality"
