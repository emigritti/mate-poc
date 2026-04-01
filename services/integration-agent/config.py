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
    # llama3.2:3b on CPU (~10 tok/s): 2000 tokens ≈ 200s, within 600s timeout.
    # llama3.1:8b on CPU (~3 tok/s): 2000 tokens ≈ 667s — raise OLLAMA_TIMEOUT_SECONDS
    # to 900 if using 8b on CPU-only. For GPU instances set OLLAMA_NUM_PREDICT=-1.
    # The 16-section template needs ~2000-3000 tokens for a full document.
    # Sections beyond the limit are completed by _enrich_with_claude() if API key is set.
    ollama_num_predict: int = 2000
    # temperature controls randomness; lower = more deterministic and slightly faster.
    ollama_temperature: float = 0.3
    # RAG context injected into the prompt is truncated to this many chars.
    # Full approved documents (~4800 chars) double the prompt and slow CPU inference.
    # 3000 chars (raised from 1500) to accommodate summaries + chunks + figures (ADR-031/032).
    ollama_rag_max_chars: int = 3000

    # ── Tag Suggestion LLM (lightweight — overrides for tag-only calls) ───────
    # Tag output is a JSON array of ≤2 items (~15 tokens).
    # num_predict=20 caps well above that to avoid truncation.
    # timeout=15s is generous even on slow CPU. temperature=0 = deterministic.
    # Override via TAG_NUM_PREDICT / TAG_TIMEOUT_SECONDS / TAG_TEMPERATURE.
    tag_num_predict: int = 20
    tag_timeout_seconds: int = 15
    tag_temperature: float = 0.0

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

    # ── Knowledge Base ─────────────────────────────────────────────────
    kb_max_file_bytes: int = 10_485_760    # 10 MB — override via KB_MAX_FILE_BYTES
    kb_chunk_size: int = 1000              # chars per chunk — override via KB_CHUNK_SIZE
    kb_chunk_overlap: int = 200            # overlap chars — override via KB_CHUNK_OVERLAP
    kb_max_rag_chars: int = 2000           # max KB context in prompt — override via KB_MAX_RAG_CHARS
    # URL KB entries — content fetched live at generation time
    kb_url_fetch_timeout_seconds: int = 10     # per-URL HTTP timeout — override via KB_URL_FETCH_TIMEOUT_SECONDS
    kb_url_max_chars_per_source: int = 1000    # max chars per fetched URL — override via KB_URL_MAX_CHARS_PER_SOURCE

    # ── RAG Phase 2 (R8, R9) ─────────────────────────────────────────────────
    # Max ChromaDB distance to keep a chunk (0 = perfect, 2 = worst).
    # Chunks with distance >= threshold are discarded before re-ranking.
    rag_distance_threshold: float = 0.8    # override: RAG_DISTANCE_THRESHOLD

    # BM25 weight in ensemble (ChromaDB weight = 1 - this).
    rag_bm25_weight: float = 0.4           # override: RAG_BM25_WEIGHT

    # ChromaDB n_results per query variant (4 variants × n_results = candidates).
    rag_n_results_per_query: int = 3       # override: RAG_N_RESULTS_PER_QUERY

    # Final top-K chunks passed to ContextAssembler after re-ranking.
    rag_top_k_chunks: int = 5              # override: RAG_TOP_K_CHUNKS

    # ── Advanced RAG — Vision + RAPTOR-lite (ADR-031, ADR-032) ──────────────────
    # Docling parsing timeout (seconds). If Docling exceeds this, falls back to the
    # fast legacy text parser so the upload never hangs or returns 504.
    # Large books (100+ pages on CPU) can take minutes — default 180s is generous
    # for typical docs (< 30 pages). Override via DOCLING_TIMEOUT_SECONDS.
    docling_timeout_seconds: int = 180

    # Vision captioning: set to False to skip LLaVA calls (figures get placeholder caption).
    vision_captioning_enabled: bool = True
    # Ollama model used for image captioning (must support multimodal via /api/chat).
    vision_model_name: str = "llava:7b"
    # RAPTOR-lite: set to False to skip section summarization at KB upload time.
    raptor_summarization_enabled: bool = True
    # Max sections to summarize per KB document upload. Acts as a safety cap so
    # a very large PDF (50+ sections) cannot queue hours of sequential LLM calls.
    # Override via KB_MAX_SUMMARIZE_SECTIONS.
    kb_max_summarize_sections: int = 15
    # Char budget reserved for DOCUMENT SUMMARIES section in ContextAssembler.
    rag_summary_max_chars: int = 500

    # ── Security (optional for PoC — enforced on mutating endpoints) ──
    # Set API_KEY in .env to enable token-based auth on trigger/approve/reject.
    # If absent, endpoints log a warning and allow through (dev mode).
    api_key: str | None = None


# Module-level singleton — imported by main.py and other modules.
# If required vars are missing, this line raises ValidationError at startup.
settings = Settings()
