# Tag LLM Tuning — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the slow 1000-token/120s Ollama call in `_suggest_tags_via_llm()` with a dedicated fast call using new env-var-driven settings (`TAG_NUM_PREDICT=20`, `TAG_TIMEOUT_SECONDS=15`, `TAG_TEMPERATURE=0.0`).

**Architecture:** Add three new Pydantic settings (ADR-016 pattern) to `config.py`. Extend `generate_with_ollama()` with optional keyword-only overrides so `_suggest_tags_via_llm()` can pass tag-specific values without changing any other caller. Document the decision in ADR-020.

**Tech Stack:** Python 3.12, Pydantic-settings, FastAPI, httpx, pytest. No new dependencies.

---

## Key files to know

| File | Role |
|------|------|
| `services/integration-agent/config.py` | Pydantic settings — add 3 new fields |
| `services/integration-agent/main.py` | `generate_with_ollama()` + `_suggest_tags_via_llm()` — modify both |
| `docker-compose.yml` | Add 3 env vars to `integration-agent` service (~line 283) |
| `docs/adr/ADR-020-tag-llm-tuning.md` | New ADR to create |
| `services/integration-agent/tests/test_config.py` | Add 3 new settings tests |
| `services/integration-agent/tests/test_tag_suggestion.py` | Add test that correct kwargs are passed |

**Run tests from:** `services/integration-agent/`
**Test command:** `python -m pytest tests/ -v`

---

## Task 1: Add tag-specific settings to `config.py`

**Files:**
- Modify: `services/integration-agent/config.py`
- Test: `services/integration-agent/tests/test_config.py`

### Step 1: Write failing tests

Open `services/integration-agent/tests/test_config.py` and append these tests at the bottom:

```python
def test_tag_num_predict_default():
    from config import Settings
    s = Settings()
    assert s.tag_num_predict == 20

def test_tag_timeout_seconds_default():
    from config import Settings
    s = Settings()
    assert s.tag_timeout_seconds == 15

def test_tag_temperature_default():
    from config import Settings
    s = Settings()
    assert s.tag_temperature == 0.0
```

### Step 2: Run tests to verify they fail

```bash
cd services/integration-agent
python -m pytest tests/test_config.py::test_tag_num_predict_default tests/test_config.py::test_tag_timeout_seconds_default tests/test_config.py::test_tag_temperature_default -v
```

Expected: `FAILED` — `Settings` has no attribute `tag_num_predict`.

### Step 3: Add the three fields to `config.py`

In `services/integration-agent/config.py`, add this block **after** the `ollama_rag_max_chars` line (line ~33) and before the `# ── Vector DB` comment:

```python
    # ── Tag Suggestion LLM (lightweight — separate from main doc-generation) ──
    # Tag output is a JSON array of ≤2 items (~15 tokens).
    # num_predict=20 caps well above that to avoid truncation.
    # timeout=15s is generous even on slow CPU. temperature=0 = deterministic.
    # Override via TAG_NUM_PREDICT / TAG_TIMEOUT_SECONDS / TAG_TEMPERATURE.
    tag_num_predict:     int   = 20
    tag_timeout_seconds: int   = 15
    tag_temperature:     float = 0.0
```

### Step 4: Run tests to verify they pass

```bash
python -m pytest tests/test_config.py::test_tag_num_predict_default tests/test_config.py::test_tag_timeout_seconds_default tests/test_config.py::test_tag_temperature_default -v
```

Expected: `PASSED` for all three.

### Step 5: Run full test suite — must stay green

```bash
python -m pytest tests/ -v
```

Expected: all existing tests still pass (new fields have defaults, so `conftest.py` needs no changes).

### Step 6: Commit

```bash
cd services/integration-agent
git add config.py tests/test_config.py
git commit -m "feat(config): add TAG_NUM_PREDICT / TAG_TIMEOUT_SECONDS / TAG_TEMPERATURE settings (ADR-020)"
```

---

## Task 2: Extend `generate_with_ollama()` with optional overrides

**Files:**
- Modify: `services/integration-agent/main.py` (function `generate_with_ollama`, ~line 236)
- Test: `services/integration-agent/tests/test_tag_suggestion.py`

### Step 1: Write a failing test

The test verifies that when kwargs are passed, they override the settings values. Append to `tests/test_tag_suggestion.py`:

```python
def test_suggest_tags_via_llm_passes_tag_settings(monkeypatch):
    """_suggest_tags_via_llm must call generate_with_ollama with tag-specific overrides."""
    from main import _suggest_tags_via_llm
    from config import settings

    captured_kwargs: dict = {}

    async def _mock(prompt, *, num_predict=None, timeout=None, temperature=None):
        captured_kwargs["num_predict"]  = num_predict
        captured_kwargs["timeout"]      = timeout
        captured_kwargs["temperature"]  = temperature
        return '["Data Sync"]'

    monkeypatch.setattr("main.generate_with_ollama", _mock)
    asyncio.run(_suggest_tags_via_llm("ERP", "PLM", "sync products"))

    assert captured_kwargs["num_predict"] == settings.tag_num_predict
    assert captured_kwargs["timeout"]     == settings.tag_timeout_seconds
    assert captured_kwargs["temperature"] == settings.tag_temperature
```

### Step 2: Run test to verify it fails

```bash
python -m pytest tests/test_tag_suggestion.py::test_suggest_tags_via_llm_passes_tag_settings -v
```

Expected: `FAILED` — `generate_with_ollama` doesn't accept keyword args yet, so kwargs are never set / assertion fails.

### Step 3: Update `generate_with_ollama()` signature

In `services/integration-agent/main.py`, find the function definition (around line 236):

```python
async def generate_with_ollama(prompt: str) -> str:
```

Replace with:

```python
async def generate_with_ollama(
    prompt: str,
    *,
    num_predict: int | None = None,
    timeout: int | None = None,
    temperature: float | None = None,
) -> str:
```

Then, inside the function body, replace the three references to `settings.*` with effective variables. Find the block that creates the httpx client and the options dict (~lines 249-261) and update as follows:

**Before (three separate settings references):**
```python
    async with httpx.AsyncClient(
        timeout=settings.ollama_timeout_seconds
    ) as client:
        res = await client.post(
            f"{settings.ollama_host}/api/generate",
            json={
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": settings.ollama_num_predict,
                    "temperature": settings.ollama_temperature,
                },
            },
        )
```

**After (use effective variables, resolve overrides once):**
```python
    _num_predict  = num_predict  if num_predict  is not None else settings.ollama_num_predict
    _timeout      = timeout      if timeout      is not None else settings.ollama_timeout_seconds
    _temperature  = temperature  if temperature  is not None else settings.ollama_temperature

    async with httpx.AsyncClient(timeout=_timeout) as client:
        res = await client.post(
            f"{settings.ollama_host}/api/generate",
            json={
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": _num_predict,
                    "temperature": _temperature,
                },
            },
        )
```

Also update the log line (just above the `async with` block) to reflect the effective timeout:

**Before:**
```python
    log_agent(
        f"[LLM] → model={settings.ollama_model} "
        f"prompt_chars={len(prompt)} "
        f"timeout={settings.ollama_timeout_seconds}s"
    )
```

**After (move log AFTER the effective vars are resolved):**
```python
    _num_predict  = num_predict  if num_predict  is not None else settings.ollama_num_predict
    _timeout      = timeout      if timeout      is not None else settings.ollama_timeout_seconds
    _temperature  = temperature  if temperature  is not None else settings.ollama_temperature

    log_agent(
        f"[LLM] → model={settings.ollama_model} "
        f"prompt_chars={len(prompt)} "
        f"timeout={_timeout}s "
        f"num_predict={_num_predict}"
    )
```

### Step 4: Update `_suggest_tags_via_llm()` to pass tag settings

Find `_suggest_tags_via_llm()` (~line 318) — the line:

```python
        raw = await generate_with_ollama(prompt)
```

Replace with:

```python
        raw = await generate_with_ollama(
            prompt,
            num_predict=settings.tag_num_predict,
            timeout=settings.tag_timeout_seconds,
            temperature=settings.tag_temperature,
        )
```

### Step 5: Run the new test to verify it passes

```bash
python -m pytest tests/test_tag_suggestion.py::test_suggest_tags_via_llm_passes_tag_settings -v
```

Expected: `PASSED`.

### Step 6: Run full test suite — must stay green

```bash
python -m pytest tests/ -v
```

Expected: all 50+ tests pass. The existing mocks patch `generate_with_ollama` by return value (AsyncMock), so the new kwargs are transparent to them.

### Step 7: Commit

```bash
git add services/integration-agent/main.py services/integration-agent/tests/test_tag_suggestion.py
git commit -m "feat(llm): add optional param overrides to generate_with_ollama; use tag settings in _suggest_tags_via_llm"
```

---

## Task 3: Update `docker-compose.yml`

**Files:**
- Modify: `docker-compose.yml` (~line 283, inside `integration-agent` → `environment`)

### Step 1: Add the three new env vars

Open `docker-compose.yml`. In the `integration-agent` service, `environment:` block, after the `CORS_ORIGINS` line (~line 283), add:

```yaml
      - TAG_NUM_PREDICT=${TAG_NUM_PREDICT:-20}
      - TAG_TIMEOUT_SECONDS=${TAG_TIMEOUT_SECONDS:-15}
      - TAG_TEMPERATURE=${TAG_TEMPERATURE:-0.0}
```

No test needed — this is infra config. Verify visually that indentation matches surrounding env vars (6 spaces before `-`).

### Step 2: Commit

```bash
git add docker-compose.yml
git commit -m "chore(docker): expose TAG_NUM_PREDICT / TAG_TIMEOUT_SECONDS / TAG_TEMPERATURE for integration-agent"
```

---

## Task 4: Write ADR-020

**Files:**
- Create: `docs/adr/ADR-020-tag-llm-tuning.md`

> Note: ADR-019 is already taken by `ADR-019-rag-tag-filtering.md`. Use 020.

### Step 1: Create the ADR

Create `docs/adr/ADR-020-tag-llm-tuning.md` with the following content:

```markdown
# ADR-020 — Tag LLM Tuning: Dedicated Lightweight Parameters

| Field      | Value |
|------------|-------|
| **Status** | Accepted |
| **Date**   | 2026-03-16 |
| **Deciders** | Integration Mate PoC team |
| **Tags**   | performance, llm, configuration |

## Context

`_suggest_tags_via_llm()` in `main.py` calls `generate_with_ollama()` using the
same parameters as the main document-generation flow:

- `num_predict = 1000` tokens
- `timeout = 120 s` (default; docker uses 600 s)
- `temperature = 0.3`

Generating `["Data Sync", "Real-time"]` requires ≈15 tokens. On a CPU instance
running llama3.1:8b at ~3 tok/s, the model generates padding until it hits
`num_predict`, making the tag call take 30–60 s unnecessarily.

## Decision

Add three dedicated settings following the ADR-016 env-var pattern:

| Setting | Env var | Default | Rationale |
|---------|---------|---------|-----------|
| `tag_num_predict` | `TAG_NUM_PREDICT` | `20` | 2 tags × ~7 tokens each = 14; 20 gives headroom |
| `tag_timeout_seconds` | `TAG_TIMEOUT_SECONDS` | `15` | 20 tokens at 3 tok/s ≈ 7 s; 15 s catches cold-start |
| `tag_temperature` | `TAG_TEMPERATURE` | `0.0` | Tags should be deterministic/reproducible |

`generate_with_ollama()` gains three optional keyword-only arguments
(`num_predict`, `timeout`, `temperature`). When `None` (default), global settings
apply — all existing callers (main doc generation) are unaffected.

## Alternatives Considered

| Option | Rejected because |
|--------|-----------------|
| Hardcode values inline in `_suggest_tags_via_llm` | Violates ADR-016; not tunable without code change |
| Replace with Claude API | External dependency; out of scope for self-hosted PoC |
| Remove LLM for tags entirely | Loses semantic enrichment; category-only already available as fallback |

## Consequences

- Tag suggestion latency drops from ~30–60 s to ~2–5 s on CPU (warm model).
- Rollback: set `TAG_NUM_PREDICT=1000`, `TAG_TIMEOUT_SECONDS=120`, `TAG_TEMPERATURE=0.3` — no rebuild needed.
- `generate_with_ollama()` signature change is backwards-compatible (all new params have `None` defaults).

## Validation

- `test_config.py`: 3 new tests verify default values.
- `test_tag_suggestion.py`: 1 new test verifies that `_suggest_tags_via_llm()` passes the tag settings as kwargs.
- Full suite (50+ tests) must remain green.
```

### Step 2: Commit

```bash
git add docs/adr/ADR-020-tag-llm-tuning.md
git commit -m "docs(adr): add ADR-020 tag LLM tuning"
```

---

## Final Verification

Run the full test suite one last time from the integration-agent directory:

```bash
cd services/integration-agent
python -m pytest tests/ -v
```

Expected: all tests pass. No regressions.

---

## Summary of Changes

| File | Change |
|------|--------|
| `services/integration-agent/config.py` | +3 settings: `tag_num_predict`, `tag_timeout_seconds`, `tag_temperature` |
| `services/integration-agent/main.py` | `generate_with_ollama()` +3 optional kwargs; `_suggest_tags_via_llm()` passes tag settings |
| `docker-compose.yml` | +3 env vars with defaults |
| `docs/adr/ADR-020-tag-llm-tuning.md` | New ADR |
| `services/integration-agent/tests/test_config.py` | +3 default-value tests |
| `services/integration-agent/tests/test_tag_suggestion.py` | +1 kwargs-forwarding test |
