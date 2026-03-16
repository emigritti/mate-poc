# Design: Tag LLM Tuning — Dedicated Env-Var Parameters

**Date:** 2026-03-16
**Status:** Approved
**ADR:** ADR-019 (to be created)
**Branch:** new-ui

---

## Problem

`_suggest_tags_via_llm()` calls `generate_with_ollama()` using the **same parameters as the main document-generation LLM**:

| Parameter | Main LLM | Tag LLM (current) | Needed for tags |
|-----------|----------|-------------------|-----------------|
| `num_predict` | 1000 tokens | 1000 tokens | ~15–20 tokens |
| `timeout` | 120 s | 120 s | 15 s is generous |
| `temperature` | 0.3 | 0.3 | 0.0 (deterministic) |

On a CPU instance running llama3.1:8b at ~3 tok/s, generating 1000 tokens before the model self-stops can take **30–60 s** for a call that should return `["Data Sync", "Real-time"]` in under 5 s.

---

## Decision

**Option A2 — New env vars in `config.py` (ADR-016 pattern).**

Add three dedicated settings for the tag suggestion LLM call. All are overridable via environment variables; defaults are tuned for CPU-based Ollama.

### Rationale for choosing A2 over alternatives

| Alternative | Why rejected |
|-------------|-------------|
| A1 — hardcode override values inline | Violates ADR-016; values buried in code, not configurable without rebuild |
| B — Replace with Claude API | External dependency + API key; out of scope for self-hosted PoC |
| C — Remove LLM entirely | Loses semantic enrichment; category-only tags are already available via `_extract_category_tags()` as fallback |

---

## Architecture

### 1. `config.py` — Three new settings

```python
# ── Tag Suggestion LLM (lightweight — overrides main LLM settings) ─────────
# Tag output is a JSON array of 2 items (~15 tokens max).
# num_predict=20 caps generation well above that to prevent truncation.
# timeout=15 is generous even on slow CPU. temperature=0 = deterministic.
tag_num_predict:     int   = 20    # env: TAG_NUM_PREDICT
tag_timeout_seconds: int   = 15    # env: TAG_TIMEOUT_SECONDS
tag_temperature:     float = 0.0   # env: TAG_TEMPERATURE
```

### 2. `main.py` — `generate_with_ollama()` keyword overrides

Add three optional keyword-only arguments. When `None` (default), the global settings apply — existing callers are unaffected. `_suggest_tags_via_llm()` passes the tag-specific settings.

```python
async def generate_with_ollama(
    prompt: str,
    *,
    num_predict: int | None = None,
    timeout: int | None = None,
    temperature: float | None = None,
) -> str:
    effective_num_predict  = num_predict  if num_predict  is not None else settings.ollama_num_predict
    effective_timeout      = timeout      if timeout      is not None else settings.ollama_timeout_seconds
    effective_temperature  = temperature  if temperature  is not None else settings.ollama_temperature
    ...
```

`_suggest_tags_via_llm()` call site:

```python
raw = await generate_with_ollama(
    prompt,
    num_predict=settings.tag_num_predict,
    timeout=settings.tag_timeout_seconds,
    temperature=settings.tag_temperature,
)
```

The main flow (`run_agentic_rag_flow`) calls `generate_with_ollama(prompt)` with no extra args — **no change required**.

### 3. `docker-compose.yml` — Env var defaults

Add to the `integration-agent` service environment block:

```yaml
- TAG_NUM_PREDICT=${TAG_NUM_PREDICT:-20}
- TAG_TIMEOUT_SECONDS=${TAG_TIMEOUT_SECONDS:-15}
- TAG_TEMPERATURE=${TAG_TEMPERATURE:-0.0}
```

### 4. ADR-019

`docs/adr/ADR-019-tag-llm-tuning.md` — documents problem, decision, parameter values with rationale, and rollback strategy (set `TAG_NUM_PREDICT=1000`, `TAG_TIMEOUT_SECONDS=120` to revert to previous behaviour without code change).

### 5. Tests

- `test_tag_suggestion.py` and `test_suggest_tags_endpoint.py` — verify mock compatibility with the updated `generate_with_ollama` signature.
- No new test cases required if existing mocks patch `generate_with_ollama` by return value (keyword args are transparent to the mock).

---

## Data Flow

```
GET /suggest-tags/{id}
    └── suggest_tags()
            ├── _extract_category_tags()   [deterministic, ~0 ms]
            └── _suggest_tags_via_llm()
                    └── generate_with_ollama(prompt,
                            num_predict=20,      ← settings.tag_num_predict
                            timeout=15,          ← settings.tag_timeout_seconds
                            temperature=0.0)     ← settings.tag_temperature
                        → ["tag1", "tag2"]  in ~2–5 s on CPU
```

---

## Expected Performance Improvement

| Scenario | Before | After |
|----------|--------|-------|
| CPU (llama3.1:8b, ~3 tok/s), model warm | ~15–60 s | ~2–5 s |
| CPU, model cold (load time ~10 s) | ~25–70 s | ~12–15 s |
| Timeout | 120 s | 15 s (fails fast) |

---

## Rollback

No code change needed. Set env vars to restore old behaviour:
```
TAG_NUM_PREDICT=1000
TAG_TIMEOUT_SECONDS=120
TAG_TEMPERATURE=0.3
```

---

## Out of Scope

- Frontend `TagConfirmPanel` UI redesign (separate task)
- Switching to a non-Ollama LLM for tags (future option B)
