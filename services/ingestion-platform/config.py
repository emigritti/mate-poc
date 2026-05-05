"""
Ingestion Platform — Configuration
Follows the same pydantic-settings pattern as integration-agent/config.py.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Persistence ───────────────────────────────────────────────────────────
    mongo_uri: str                              # required
    mongo_db: str = "integration_mate"          # shared DB with integration-agent
    chroma_host: str = "mate-chromadb"
    chroma_port: int = 8000

    # ── AI Services ───────────────────────────────────────────────────────────
    # Optional in Phase 1; required in Phase 4 (HTML collector)
    anthropic_api_key: str | None = None
    # Claude models for semantic extraction and diff summaries
    claude_extraction_model: str = "claude-sonnet-4-6"
    claude_filter_model: str = "claude-haiku-4-5-20251001"

    # ── Integration with integration-agent ───────────────────────────────────
    # Used to trigger BM25 index rebuild after ingestion
    integration_agent_url: str = "http://mate-integration-agent:3003"

    # ── Ingestion defaults ────────────────────────────────────────────────────
    max_html_pages_per_crawl: int = 20          # Playwright crawl depth limit
    html_relevance_min_score: float = 0.5       # Haiku relevance threshold
    capability_confidence_threshold: float = 0.7

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:8080,http://localhost:3000,http://localhost:5173"

    # ── Auth (optional) ───────────────────────────────────────────────────────
    api_key: str | None = None

    # ── Embedder (ADR-X2) ─────────────────────────────────────────────────────
    # Provider: "ollama" (default) or "default" (ChromaDB native MiniLM).
    # MUST match integration-agent/config.py — both services write to the same
    # kb_collection in ChromaDB, and dimensions must be consistent.
    ollama_host: str = "http://mate-ollama:11434"
    ollama_timeout_seconds: float = 120.0
    embedder_provider: str = "ollama"
    embedder_model_name: str = "nomic-embed-text:v1.5"
    embedder_doc_prefix: str = "search_document: "
    embedder_query_prefix: str = "search_query: "

    # ── Contextual Retrieval (ADR-X4) ─────────────────────────────────────────
    # Mirrors integration-agent/config.py — same env vars, same defaults.
    # Set CONTEXTUAL_RETRIEVAL_ENABLED=false in tests (conftest.py).
    contextual_retrieval_enabled: bool = True
    contextual_provider: str = "claude"
    contextual_model_claude: str = "claude-haiku-4-5-20251001"
    contextual_model_ollama: str = "llama3.1:8b"
    contextual_max_tokens: int = 120


settings = Settings()
