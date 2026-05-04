from unittest.mock import patch
from embedding_function import OllamaEmbeddingFunction


def test_ollama_embedding_function_uses_doc_prefix_for_documents(monkeypatch):
    monkeypatch.setattr("config.settings.embedder_doc_prefix", "search_document: ")
    monkeypatch.setattr("config.settings.embedder_query_prefix", "search_query: ")
    captured = []

    def fake_post(self, url, json, **kw):
        captured.append(json)

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"embedding": [0.1, 0.2, 0.3]}

        return R()

    fn = OllamaEmbeddingFunction(
        model="nomic-embed-text:v1.5",
        ollama_host="http://o:11434",
        mode="document",
    )
    with patch("httpx.Client.post", new=fake_post):
        out = fn(["chunk text"])
    assert captured[0]["prompt"].startswith("search_document: ")
    assert out == [[0.1, 0.2, 0.3]]


def test_ollama_embedding_function_uses_query_prefix_in_query_mode(monkeypatch):
    monkeypatch.setattr("config.settings.embedder_doc_prefix", "search_document: ")
    monkeypatch.setattr("config.settings.embedder_query_prefix", "search_query: ")
    captured = []

    def fake_post(self, url, json, **kw):
        captured.append(json)

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"embedding": [0.0]}

        return R()

    fn = OllamaEmbeddingFunction(
        model="nomic-embed-text:v1.5",
        ollama_host="http://o:11434",
        mode="query",
    )
    with patch("httpx.Client.post", new=fake_post):
        fn(["my question"])
    assert captured[0]["prompt"].startswith("search_query: ")


def test_ollama_embedding_function_iterates_each_input(monkeypatch):
    posts = []

    def fake_post(self, url, json, **kw):
        posts.append(json["prompt"])

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"embedding": [0.0] * 768}

        return R()

    fn = OllamaEmbeddingFunction(
        model="nomic-embed-text:v1.5",
        ollama_host="http://o:11434",
        mode="document",
    )
    with patch("httpx.Client.post", new=fake_post):
        out = fn(["a", "b", "c"])
    assert len(posts) == 3
    assert all(p.endswith("a") or p.endswith("b") or p.endswith("c") for p in posts)
    assert len(out) == 3
    assert all(len(v) == 768 for v in out)
