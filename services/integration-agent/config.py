"""
Integration Agent — Configuration
ADR-016: Secret Management via Pydantic Settings.

All required fields have NO default — the app fails fast at startup if
any required environment variable is absent. This prevents silent
misconfiguration in production.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",       # fallback for local dev; Docker injects via environment:
        extra="ignore",        # ignore unrecognised env vars (Postgres, etc.)
        case_sensitive=False,  # OLLAMA_HOST → ollama_host
    )

    # ── LLM ──────────────────────────────────────────────────────────
    ollama_host: str                             # required — no default
    ollama_model: str = "llama3.1:8b"
    ollama_timeout_seconds: int = 120

    # ── Vector DB ─────────────────────────────────────────────────────
    chroma_host: str = "mate-chromadb"
    chroma_port: int = 8000

    # ── Catalog Store ─────────────────────────────────────────────────
    mongo_uri: str                               # required — no default
    mongo_db: str = "integration_mate"

    # ── LLM Output Guard ──────────────────────────────────────────────
    llm_max_output_chars: int = 50_000

    # ── CORS (comma-separated origin list) ────────────────────────────
    cors_origins: str = "http://localhost:8080,http://localhost:3000"

    # ── Log TTL ──────────────────────────────────────────────────────
    log_ttl_hours: int = 4   # env: LOG_TTL_HOURS — prune entries older than N hours

    # ── Security (optional for PoC — enforced on mutating endpoints) ──
    # Set API_KEY in .env to enable token-based auth on trigger/approve/reject.
    # If absent, endpoints log a warning and allow through (dev mode).
    api_key: str | None = None


# Module-level singleton — imported by main.py and other modules.
# If required vars are missing, this line raises ValidationError at startup.
settings = Settings()
