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
    # num_predict caps generated tokens — prevents timeout on slow CPU instances.
    # llama3.1:8b on CPU (~3 tok/s): 1000 tokens ≈ 333s, well within 600s timeout.
    # Override via OLLAMA_NUM_PREDICT env var for faster hardware.
    ollama_num_predict: int = 1000
    # temperature controls randomness; lower = more deterministic and slightly faster.
    ollama_temperature: float = 0.3
    # RAG context injected into the prompt is truncated to this many chars.
    # Full approved documents (~4800 chars) double the prompt and slow CPU inference.
    # 1500 chars captures the key patterns without exploding the KV cache.
    ollama_rag_max_chars: int = 1500

    # ── Tag Suggestion LLM (lightweight — separate from main doc-generation) ──
    # Tag output is a JSON array of ≤2 items (~15 tokens).
    # num_predict=20 caps well above that to avoid truncation.
    # timeout=15s is generous even on slow CPU. temperature=0 = deterministic.
    # Override via TAG_NUM_PREDICT / TAG_TIMEOUT_SECONDS / TAG_TEMPERATURE.
    tag_num_predict:     int   = 20
    tag_timeout_seconds: int   = 15
    tag_temperature:     float = 0.0

    # ── Vector DB ─────────────────────────────────────────────────────
    chroma_host: str = "mate-chromadb"
    chroma_port: int = 8000

    # ── Catalog Store ─────────────────────────────────────────────────
    mongo_uri: str                               # required — no default
    mongo_db: str = "integration_mate"

    # ── LLM Output Guard ──────────────────────────────────────────────
    llm_max_output_chars: int = 50_000

    # ── CORS (comma-separated origin list) ────────────────────────────
    cors_origins: str = "http://localhost:8080,http://localhost:3000,http://localhost:5173"

    # ── Log TTL ──────────────────────────────────────────────────────
    log_ttl_hours: int = 4   # env: LOG_TTL_HOURS — prune entries older than N hours

    # ── Security (optional for PoC — enforced on mutating endpoints) ──
    # Set API_KEY in .env to enable token-based auth on trigger/approve/reject.
    # If absent, endpoints log a warning and allow through (dev mode).
    api_key: str | None = None


# Module-level singleton — imported by main.py and other modules.
# If required vars are missing, this line raises ValidationError at startup.
settings = Settings()
