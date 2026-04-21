# ADR-049 — Google Gemini API as Alternative LLM Provider

| Metadata | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-04-21 |
| **Deciders** | Emiliano Gritti |
| **Tags** | LLM, Gemini, Provider, Config |

---

## Context

The system uses Ollama (local inference) as its sole LLM backend. Ollama requires a GPU or high-RAM CPU to run large models at acceptable speed (~4–7 tok/s on t3.2xlarge without GPU). The user has a Google Gemini API key and wants to offload generation to Gemini for:

- Faster generation (~1–5s vs. 4–9 min for `qwen2.5:14b`)
- Access to `gemini-2.0-flash` and `gemini-2.5-pro` without local hardware
- Independent provider per profile: e.g. Standard → Gemini for speed, Fast-Utility → Ollama for tagging

## Decision

Add **Google Gemini API** as a second LLM provider alongside Ollama. Provider selection is **per-profile** (`doc_llm`, `premium_llm`, `tag_llm`), configurable at runtime via the LLM Settings UI without container restart.

### Key design choices

1. **`provider` field per profile** — stored in `llm_overrides` dict (existing MongoDB persistence). Default is `"ollama"` (backward-compatible; no behavior change unless user switches).
2. **Dispatch in `generate_with_retry()`** — single entry point for all callers; routes to `generate_with_ollama()` or `_generate_with_gemini()` based on `provider` kwarg.
3. **Gemini SDK** — `google-generativeai>=0.8.0` with async `generate_content_async()`. Only `model`, `temperature`, and `max_output_tokens` (≈ `num_predict`) are forwarded; Ollama-specific params (`num_ctx`, `top_k`, `top_p`, `repeat_penalty`) are silently ignored.
4. **API key via env var** — `GEMINI_API_KEY` in `.env`; read via `settings.gemini_api_key`. If absent, calling a Gemini-configured profile raises `ValueError` immediately (non-retryable).
5. **Retry behavior** — Gemini retries on any generic exception (rate limits, transient errors); `ValueError` (missing key) is not retried. Ollama retry logic is unchanged.
6. **UI hint** — `LlmSettingsPage.jsx` shows a Provider dropdown at the top of each card; Gemini-specific hint explains which params are ignored.

## Consequences

**Positive:**
- Dramatically faster generation for users with Gemini API access
- No Ollama/GPU dependency for document generation if all profiles use Gemini
- Per-profile granularity: e.g. FactPack extraction (doc_llm) via Gemini, tagging (tag_llm) stays Ollama
- Zero breaking change — default provider remains `"ollama"` for all profiles

**Negative / Trade-offs:**
- Adds external API dependency (Google AI Studio / Vertex AI) — network required
- `num_ctx`, `top_k`, `top_p`, `repeat_penalty` are silently ignored for Gemini profiles (shown as hint in UI)
- `GEMINI_API_KEY` must be in `.env` and propagated into the container (`docker compose rm -f` on first use)
- `google-generativeai` SDK may lag behind latest Gemini model releases — may need update for Gemini 3.x

## Alternatives Considered

| Alternative | Reason Not Chosen |
|---|---|
| Single global provider switch | Less flexible — can't use Ollama for tagging (cheap, local) and Gemini for generation |
| LiteLLM proxy | Additional infrastructure; overkill for two providers |
| Direct httpx calls to Gemini REST API | Avoids SDK but requires manual auth, retry, and response parsing |
| Only support Gemini | Breaks offline/EC2 use case; Ollama is still valuable for air-gapped deployments |

## Validation Plan

- `tests/test_llm_service.py` — 6 new Gemini tests: dispatch, success, generic retry, exhausted retry, ValueError non-retry, missing key
- `tests/test_llm_settings.py` — 5 new tests: default provider, PATCH to Gemini, profile isolation, reset restores Ollama
- Manual: switch Standard profile to `gemini-2.0-flash` in UI, trigger generation, verify document quality

## Rollback

Set all profiles back to `provider = "ollama"` via LLM Settings UI → Reset to Defaults. No code change required.
