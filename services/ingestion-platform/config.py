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


settings = Settings()
