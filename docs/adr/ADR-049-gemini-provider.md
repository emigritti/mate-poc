# ADR-049 — Cloud LLM Providers: Google Gemini and Anthropic Claude

| Metadata | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-04-21 |
| **Updated** | 2026-04-21 |
| **Deciders** | Emiliano Gritti |
| **Tags** | LLM, Gemini, Anthropic, Provider, Config |

---

## Context

The system uses Ollama (local inference) as its sole LLM backend. Ollama requires a GPU or high-RAM CPU to run large models at acceptable speed (~4–7 tok/s on t3.2xlarge without GPU). The user has both a Google Gemini API key and an Anthropic API key and wants to offload generation to cloud providers for:

- Faster generation (~1–5s vs. 4–9 min for `qwen2.5:14b`)
- Access to `gemini-2.0-flash`, `gemini-2.5-pro`, `claude-sonnet-4-6`, `claude-opus-4-7` without local hardware
- Independent provider per profile: e.g. Standard → Anthropic for quality, Fast-Utility → Ollama for tagging

## Decision

Add **Google Gemini API** and **Anthropic Claude API** as alternative LLM providers alongside Ollama. Provider selection is **per-profile** (`doc_llm`, `premium_llm`, `tag_llm`), configurable at runtime via the LLM Settings UI without container restart.

### Key design choices

1. **`provider` field per profile** — stored in `llm_overrides` dict (existing MongoDB persistence). Default is `"ollama"` (backward-compatible; no behavior change unless user switches).
2. **Dispatch in `generate_with_retry()`** — single entry point for all callers; routes to `generate_with_ollama()`, `_generate_with_gemini()`, or `_generate_with_anthropic()` based on `provider` kwarg.
3. **Gemini SDK** — `google-generativeai>=0.8.0` with async `generate_content_async()`. Only `model`, `temperature`, and `max_output_tokens` are forwarded; Ollama-specific params silently ignored.
4. **Anthropic SDK** — `anthropic>=0.25.0` (already in requirements.txt) with async `messages.create()`. Default model: `claude-sonnet-4-6`. Only `model`, `temperature`, and `max_tokens` forwarded; Ollama-specific params silently ignored.
5. **API keys via env vars** — `GEMINI_API_KEY` and `ANTHROPIC_API_KEY` in `.env`; read via `settings.gemini_api_key` / `settings.anthropic_api_key`. If absent, calling a cloud-configured profile raises `ValueError` immediately (non-retryable). Both vars are injected into the `integration-agent` container via `docker-compose.yml`.
6. **Retry behavior** — both cloud providers retry on any generic exception (rate limits, transient errors); `ValueError` (missing key) is not retried. Ollama retry logic unchanged.
7. **UI** — Provider dropdown in each card; cloud providers show a shared hint that Ollama-specific params are ignored.

## Consequences

**Positive:**
- Dramatically faster generation for users with API keys
- No Ollama/GPU dependency if all profiles use cloud providers
- Per-profile granularity: e.g. FactPack via Anthropic, tagging stays Ollama
- Zero breaking change — default provider remains `"ollama"` for all profiles

**Negative / Trade-offs:**
- Adds external API dependency — network required; costs per token
- `num_ctx`, `top_k`, `top_p`, `repeat_penalty` silently ignored for cloud profiles (shown as UI hint)
- API keys must be in `.env` and propagated into the container (`docker compose rm -f` on first use)
- Anthropic `anthropic_api_key` field shares the same settings instance used by `ingestion-platform` for HTML extraction — intentional reuse, no duplication

## Alternatives Considered

| Alternative | Reason Not Chosen |
|---|---|
| Single global provider switch | Less flexible — can't mix providers per profile |
| LiteLLM proxy | Additional infrastructure; overkill for two providers |
| Direct httpx calls to REST APIs | Requires manual auth, retry, and response parsing per provider |
| Only support Gemini | User already has Anthropic key; Claude quality suits integration docs |

## Validation Plan

- `tests/test_llm_service.py` — 6 Gemini tests + 7 Anthropic tests: dispatch, success, generic retry, exhausted retry, ValueError non-retry, missing key
- `tests/test_llm_settings.py` — PATCH to Gemini, PATCH to Anthropic, profile isolation, reset restores Ollama
- Manual: switch Standard profile to `claude-sonnet-4-6` in UI, trigger generation, verify document quality

## Rollback

Set all profiles back to `provider = "ollama"` via LLM Settings UI → Reset to Defaults. No code change required.
