"""Ollama-backed ChromaDB embedding function with task-aware prefixing (ADR-X2).

nomic-embed-text-v1.5 uses task prefixes ("search_document: " / "search_query: ")
to disambiguate ingestion vs retrieval calls.  This wrapper enforces them per
mode at the function-call site.
"""
from __future__ import annotations
import logging
from typing import Literal

import httpx
from chromadb import Documents, EmbeddingFunction, Embeddings

from config import settings

logger = logging.getLogger(__name__)

_MODE = Literal["document", "query"]


class OllamaEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model: str, ollama_host: str, mode: _MODE):
        self._model = model
        self._url = f"{ollama_host.rstrip('/')}/api/embeddings"
        self._mode = mode

    def __call__(self, input: Documents) -> Embeddings:
        prefix = (settings.embedder_doc_prefix
                  if self._mode == "document"
                  else settings.embedder_query_prefix)
        out: Embeddings = []
        with httpx.Client(timeout=60.0) as client:
            for text in input:
                resp = client.post(self._url, json={
                    "model": self._model,
                    "prompt": f"{prefix}{text}",
                })
                resp.raise_for_status()
                out.append(resp.json()["embedding"])
        return out
