"""ADR-X2 wiring smoke tests.

These verify _make_embedder() behavior from main.py without spinning up the
full ChromaDB lifespan.  The actual collection.add()/query() round-trip is
exercised by the live eval harness (Task X2.4) and by existing kb_endpoints
integration tests after the wire-in.
"""
import importlib
from unittest.mock import patch


def test_make_embedder_returns_ollama_function_when_provider_is_ollama(monkeypatch):
    monkeypatch.setattr("config.settings.embedder_provider", "ollama")
    monkeypatch.setattr("config.settings.embedder_model_name", "nomic-embed-text:v1.5")
    monkeypatch.setattr("config.settings.ollama_host", "http://o:11434")

    import main
    fn = main._make_embedder("document")

    from embedding_function import OllamaEmbeddingFunction
    assert isinstance(fn, OllamaEmbeddingFunction)
    assert fn._mode == "document"
    assert fn._model == "nomic-embed-text:v1.5"


def test_make_embedder_returns_none_when_provider_is_default(monkeypatch):
    monkeypatch.setattr("config.settings.embedder_provider", "default")

    import main
    fn = main._make_embedder("document")
    assert fn is None
