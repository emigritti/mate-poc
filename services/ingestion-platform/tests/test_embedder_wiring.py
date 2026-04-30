"""ADR-X2 ingestion-platform wiring smoke tests."""
from embedding_function import OllamaEmbeddingFunction


def test_make_doc_embedder_returns_ollama_function_when_provider_is_ollama(monkeypatch):
    monkeypatch.setattr("config.settings.embedder_provider", "ollama")
    monkeypatch.setattr("config.settings.embedder_model_name", "nomic-embed-text:v1.5")
    monkeypatch.setattr("config.settings.ollama_host", "http://o:11434")

    from routers.ingest import _make_doc_embedder
    fn = _make_doc_embedder()
    assert isinstance(fn, OllamaEmbeddingFunction)
    assert fn._mode == "document"
    assert fn._model == "nomic-embed-text:v1.5"


def test_make_doc_embedder_returns_none_when_provider_is_default(monkeypatch):
    monkeypatch.setattr("config.settings.embedder_provider", "default")

    from routers.ingest import _make_doc_embedder
    assert _make_doc_embedder() is None
