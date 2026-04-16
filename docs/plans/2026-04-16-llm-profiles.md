# LLM Multi-Profile Routing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Introduce three named LLM profiles (default / premium / fast-utility), extend the Ollama options payload with `num_ctx / top_p / top_k / repeat_penalty`, route tag/expansion calls to the fast model, and expose a per-document profile selector in the UI.

**Architecture:** A new `llm_profile` field flows from `POST /agent/trigger` → `run_agentic_rag_flow()` → `generate_integration_doc()`. When `llm_profile="premium"` the agent reads premium-prefixed config values and passes them to `generate_with_ollama()`. Tag/expansion calls always use `settings.tag_model` (fast-utility). All parameters are resolved via the existing `_get_llm_param()` helper so runtime overrides continue to work.

**Tech Stack:** FastAPI, Pydantic-Settings, httpx, React 18, TanStack Query, Tailwind CSS.

---

### Task 1: Extend `config.py` with new LLM parameters

**Files:**
- Modify: `services/integration-agent/config.py:20-52`

**Step 1: Write failing test**

```python
# tests/test_config.py — add to existing file
def test_new_llm_params_have_defaults():
    from config import Settings
    s = Settings()
    assert s.ollama_num_ctx == 8192
    assert s.ollama_top_p == 0.9
    assert s.ollama_top_k == 40
    assert s.ollama_repeat_penalty == 1.08
    assert s.tag_model == "qwen3:8b"
    assert s.premium_model == "gemma4:26b"
    assert s.premium_num_ctx == 6144
    assert s.premium_num_predict == 1800
    assert s.premium_temperature == 0.0
    assert s.premium_top_p == 0.85
    assert s.premium_top_k == 30
    assert s.premium_repeat_penalty == 1.1
    assert s.premium_timeout_seconds == 900
```

**Step 2: Run test to verify it fails**

```bash
cd services/integration-agent && python -m pytest tests/test_config.py::test_new_llm_params_have_defaults -v
```
Expected: FAIL — `Settings` has no attribute `ollama_num_ctx`.

**Step 3: Implement — add fields to `Settings` class**

Add after `ollama_rag_max_chars` (line 42):
```python
# Ollama generation quality parameters (ADR-046)
# num_ctx: explicit context window. Ollama default is 2048 (undocumented); 8192 is safe
# for qwen2.5:14b on CPU — covers template + requirements + retrieved chunks.
ollama_num_ctx: int = 8192
ollama_top_p: float = 0.9
ollama_top_k: int = 40
ollama_repeat_penalty: float = 1.08
```

Add after the tag settings block (after `tag_temperature` line):
```python
# ── Fast-utility model (tags, query expansion) ───────────────────────────
# qwen3:8b — lightweight, strong multilingual. Used for short/frequent calls.
# Override via TAG_MODEL.
tag_model: str = "qwen3:8b"

# ── Premium model profile (ADR-046) ──────────────────────────────────────
# gemma4:26b — used for complex integration documents when requested.
# Override via PREMIUM_MODEL (and PREMIUM_* siblings).
premium_model: str = "gemma4:26b"
premium_num_ctx: int = 6144
premium_num_predict: int = 1800
premium_temperature: float = 0.0
premium_top_p: float = 0.85
premium_top_k: int = 30
premium_repeat_penalty: float = 1.1
premium_timeout_seconds: int = 900
```

**Step 4: Run test to verify it passes**

```bash
cd services/integration-agent && python -m pytest tests/test_config.py::test_new_llm_params_have_defaults -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add services/integration-agent/config.py services/integration-agent/tests/test_config.py
git commit -m "feat(config): add num_ctx/top_p/top_k/repeat_penalty + tag_model + premium profile (ADR-046)"
```

---

### Task 2: Extend `generate_with_ollama()` with full Ollama options

**Files:**
- Modify: `services/integration-agent/services/llm_service.py`
- Test: `services/integration-agent/tests/test_llm_service.py`

**Step 1: Write failing tests**

```python
# Add to tests/test_llm_service.py

@pytest.mark.asyncio
async def test_generate_with_ollama_sends_full_options(respx_mock):
    """Verify num_ctx / top_p / top_k / repeat_penalty / model appear in payload."""
    import json as _json
    captured = {}

    async def handler(request):
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"response": "ok", "eval_count": 5,
                                          "prompt_eval_count": 3, "eval_duration": 1_000_000_000,
                                          "total_duration": 1_000_000_000, "load_duration": 0})

    respx_mock.post("http://test-ollama/api/generate").mock(side_effect=handler)

    with patch("services.llm_service.settings") as ms:
        ms.ollama_host = "http://test-ollama"
        ms.ollama_model = "test-model"
        ms.ollama_num_predict = 100
        ms.ollama_timeout_seconds = 10
        ms.ollama_temperature = 0.1
        ms.ollama_num_ctx = 8192
        ms.ollama_top_p = 0.9
        ms.ollama_top_k = 40
        ms.ollama_repeat_penalty = 1.08
        from services.llm_service import generate_with_ollama, llm_overrides
        llm_overrides.clear()
        await generate_with_ollama("hello", model="my-model")

    opts = captured["body"]["options"]
    assert captured["body"]["model"] == "my-model"
    assert opts["num_ctx"] == 8192
    assert opts["top_p"] == 0.9
    assert opts["top_k"] == 40
    assert opts["repeat_penalty"] == 1.08


@pytest.mark.asyncio
async def test_generate_with_ollama_model_param_overrides_overrides(respx_mock):
    """Explicit model= kwarg takes priority over llm_overrides['model']."""
    captured = {}

    async def handler(request):
        import json as _json
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"response": "ok", "eval_count": 0,
                                          "prompt_eval_count": 0, "eval_duration": 1,
                                          "total_duration": 1, "load_duration": 0})

    respx_mock.post("http://test-ollama/api/generate").mock(side_effect=handler)

    with patch("services.llm_service.settings") as ms:
        ms.ollama_host = "http://test-ollama"
        ms.ollama_model = "default-model"
        ms.ollama_num_predict = 100
        ms.ollama_timeout_seconds = 10
        ms.ollama_temperature = 0.1
        ms.ollama_num_ctx = 8192
        ms.ollama_top_p = 0.9
        ms.ollama_top_k = 40
        ms.ollama_repeat_penalty = 1.08
        from services.llm_service import generate_with_ollama, llm_overrides
        llm_overrides.clear()
        llm_overrides["model"] = "override-model"
        await generate_with_ollama("hello", model="explicit-model")

    assert captured["body"]["model"] == "explicit-model"
```

**Step 2: Run tests to verify they fail**

```bash
cd services/integration-agent && python -m pytest tests/test_llm_service.py::test_generate_with_ollama_sends_full_options tests/test_llm_service.py::test_generate_with_ollama_model_param_overrides_overrides -v
```

**Step 3: Implement**

Update `generate_with_ollama()` signature and body:
```python
async def generate_with_ollama(
    prompt: str,
    *,
    model: str | None = None,         # NEW: explicit model override
    num_predict: int | None = None,
    timeout: int | None = None,
    temperature: float | None = None,
    num_ctx: int | None = None,        # NEW
    top_p: float | None = None,        # NEW
    top_k: int | None = None,          # NEW
    repeat_penalty: float | None = None,  # NEW
    log_fn: Callable[[str], None] | None = None,
) -> str:
    _num_predict    = _get_llm_param("num_predict",     settings.ollama_num_predict,     override=num_predict)
    _timeout        = _get_llm_param("timeout_seconds", settings.ollama_timeout_seconds, override=timeout)
    _temperature    = _get_llm_param("temperature",     settings.ollama_temperature,     override=temperature)
    _num_ctx        = _get_llm_param("num_ctx",         settings.ollama_num_ctx,         override=num_ctx)
    _top_p          = _get_llm_param("top_p",           settings.ollama_top_p,           override=top_p)
    _top_k          = _get_llm_param("top_k",           settings.ollama_top_k,           override=top_k)
    _repeat_penalty = _get_llm_param("repeat_penalty",  settings.ollama_repeat_penalty,  override=repeat_penalty)
    # Model: explicit kwarg > llm_overrides > settings default
    _model = model if model is not None else llm_overrides.get("model", settings.ollama_model)
    ...
    "options": {
        "num_predict":    _num_predict,
        "temperature":    _temperature,
        "num_ctx":        _num_ctx,
        "top_p":          _top_p,
        "top_k":          _top_k,
        "repeat_penalty": _repeat_penalty,
    },
```

Update `generate_with_retry()` signature to forward new params:
```python
async def generate_with_retry(
    prompt: str,
    *,
    max_retries: int = 3,
    model: str | None = None,
    num_predict: int | None = None,
    timeout: int | None = None,
    temperature: float | None = None,
    num_ctx: int | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    repeat_penalty: float | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> str:
    ...
    return await generate_with_ollama(
        prompt,
        model=model, num_predict=num_predict, timeout=timeout,
        temperature=temperature, num_ctx=num_ctx, top_p=top_p,
        top_k=top_k, repeat_penalty=repeat_penalty, log_fn=log_fn,
    )
```

**Step 4: Run tests to verify they pass**

```bash
cd services/integration-agent && python -m pytest tests/test_llm_service.py -v
```

**Step 5: Commit**

```bash
git add services/integration-agent/services/llm_service.py services/integration-agent/tests/test_llm_service.py
git commit -m "feat(llm): extend Ollama options with num_ctx/top_p/top_k/repeat_penalty/model (ADR-046)"
```

---

### Task 3: Update `admin.py` — extend LLM settings patch schema

**Files:**
- Modify: `services/integration-agent/routers/admin.py:27-43`

**Step 1: Write failing test**

```python
# tests/test_admin.py — add to existing file
def test_doc_llm_patch_accepts_new_fields():
    from routers.admin import _DocLLMPatch
    p = _DocLLMPatch(num_ctx=4096, top_p=0.8, top_k=20, repeat_penalty=1.05)
    d = p.model_dump(exclude_none=True)
    assert d["num_ctx"] == 4096
    assert d["top_p"] == 0.8
    assert d["top_k"] == 20
    assert d["repeat_penalty"] == 1.05
```

**Step 2: Run to verify it fails**

```bash
cd services/integration-agent && python -m pytest tests/test_admin.py::test_doc_llm_patch_accepts_new_fields -v
```

**Step 3: Add fields to `_DocLLMPatch`**

```python
class _DocLLMPatch(BaseModel):
    model: str | None = None
    num_predict: int | None = None
    timeout_seconds: int | None = None
    temperature: float | None = None
    rag_max_chars: int | None = None
    num_ctx: int | None = None         # NEW
    top_p: float | None = None         # NEW
    top_k: int | None = None           # NEW
    repeat_penalty: float | None = None  # NEW
```

Update `_llm_settings_response()` `defaults` and `effective` dicts to include the new fields for `doc_llm`.

**Step 4: Run test**

```bash
cd services/integration-agent && python -m pytest tests/test_admin.py -v
```

**Step 5: Commit**

```bash
git add services/integration-agent/routers/admin.py services/integration-agent/tests/test_admin.py
git commit -m "feat(admin): expose num_ctx/top_p/top_k/repeat_penalty in LLM settings patch"
```

---

### Task 4: Route tags and query expansion to `tag_model`

**Files:**
- Modify: `services/integration-agent/services/tag_service.py:51-57`
- Modify: `services/integration-agent/services/retriever.py:194-200`

**Step 1: Write failing tests**

```python
# tests/test_tag_service.py — add
@pytest.mark.asyncio
async def test_suggest_tags_uses_tag_model(mock_generate):
    """Tag suggestion must call generate_with_ollama with model=settings.tag_model."""
    with patch("services.tag_service.settings") as ms:
        ms.tag_model = "qwen3:8b"
        ms.tag_num_predict = 50
        ms.tag_timeout_seconds = 60
        ms.tag_temperature = 0.0
        with patch("services.tag_service.generate_with_ollama", return_value='["tag1"]') as gen:
            from services.tag_service import suggest_tags_via_llm
            from services.llm_service import llm_overrides
            llm_overrides.clear()
            await suggest_tags_via_llm("SRC", "TGT", "req text")
            call_kwargs = gen.call_args.kwargs
            assert call_kwargs.get("model") == "qwen3:8b"
```

**Step 2: Run to verify it fails**

```bash
cd services/integration-agent && python -m pytest tests/test_tag_service.py::test_suggest_tags_uses_tag_model -v
```

**Step 3: Implement**

In `tag_service.py` `suggest_tags_via_llm()`, add `model=llm_overrides.get("tag_model", settings.tag_model)` to the `generate_with_ollama` call. Do the same in `suggest_kb_tags_via_llm()`.

In `retriever.py` `_expand_queries()`, add `model=llm_overrides.get("tag_model", settings.tag_model)` to the `generate_with_ollama` call.

**Step 4: Run tests**

```bash
cd services/integration-agent && python -m pytest tests/test_tag_service.py -v
```

**Step 5: Commit**

```bash
git add services/integration-agent/services/tag_service.py services/integration-agent/services/retriever.py services/integration-agent/tests/test_tag_service.py
git commit -m "feat(tags): route tag/expansion calls to tag_model (qwen3:8b) (ADR-046)"
```

---

### Task 5: Add `llm_profile` to agent trigger flow

**Files:**
- Modify: `services/integration-agent/routers/agent.py:31-34, 38, 85-91`
- Modify: `services/integration-agent/services/agent_service.py:237-243, 280, 363-366`

**Step 1: Write failing tests**

```python
# tests/test_agent_service.py — add
@pytest.mark.asyncio
async def test_generate_integration_doc_premium_uses_premium_settings():
    """When llm_profile='premium', generate_with_retry is called with premium model/params."""
    ...
    with patch("services.agent_service.generate_with_retry", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "# Integration Design\nsome content"
        with patch("services.agent_service.settings") as ms:
            ms.fact_pack_enabled = False
            ms.ollama_model = "qwen2.5:14b"
            ms.premium_model = "gemma4:26b"
            ms.premium_num_ctx = 6144
            ms.premium_num_predict = 1800
            ms.premium_temperature = 0.0
            ms.premium_top_p = 0.85
            ms.premium_top_k = 30
            ms.premium_repeat_penalty = 1.1
            ms.premium_timeout_seconds = 900
            ms.ollama_rag_max_chars = 1000
            # ... minimal setup
            await generate_integration_doc(entry, reqs, llm_profile="premium")
            call_kwargs = mock_gen.call_args.kwargs
            assert call_kwargs["model"] == "gemma4:26b"
            assert call_kwargs["num_ctx"] == 6144
            assert call_kwargs["temperature"] == 0.0
```

**Step 2: Run to verify it fails**

```bash
cd services/integration-agent && python -m pytest tests/test_agent_service.py::test_generate_integration_doc_premium_uses_premium_settings -v
```

**Step 3: Implement**

In `routers/agent.py`:
```python
class TriggerRequest(BaseModel):
    pinned_doc_ids: list[str] = []
    llm_profile: str = "default"    # NEW: "default" | "premium"
```

Pass `llm_profile` through `run_agentic_rag_flow(pinned_chunks, llm_profile)` and `generate_integration_doc(..., llm_profile=llm_profile)`.

In `agent_service.py` `generate_integration_doc()`:
```python
async def generate_integration_doc(
    entry,
    requirements: list,
    reviewer_feedback: str = "",
    log_fn: Callable[[str], None] | None = None,
    pinned_chunks: list | None = None,
    llm_profile: str = "default",   # NEW: "default" | "premium"
) -> tuple[str, GenerationReport]:
```

Resolve model/params based on profile:
```python
# After _log assignment
if llm_profile == "premium":
    _llm_model   = settings.premium_model
    _llm_kw      = dict(
        model=_llm_model,
        num_predict=settings.premium_num_predict,
        timeout=settings.premium_timeout_seconds,
        temperature=settings.premium_temperature,
        num_ctx=settings.premium_num_ctx,
        top_p=settings.premium_top_p,
        top_k=settings.premium_top_k,
        repeat_penalty=settings.premium_repeat_penalty,
    )
else:
    _llm_model = llm_overrides.get("model", settings.ollama_model)
    _llm_kw    = {}   # generate_with_retry reads defaults from llm_overrides / settings
```

Then replace `generate_with_retry(prompt, log_fn=_log)` with:
```python
raw = await generate_with_retry(prompt, log_fn=_log, **_llm_kw)
```

And log the profile:
```python
_log(f"[LLM] profile={llm_profile!r} model={_llm_model} — calling generate_with_retry...")
```

Also update `model_used` in GenerationReport:
```python
model_used = _llm_model
```

**Step 4: Run tests**

```bash
cd services/integration-agent && python -m pytest tests/test_agent_service.py -v
```

**Step 5: Commit**

```bash
git add services/integration-agent/routers/agent.py services/integration-agent/services/agent_service.py services/integration-agent/tests/test_agent_service.py
git commit -m "feat(agent): add llm_profile routing — default/premium model selection per trigger (ADR-046)"
```

---

### Task 6: Frontend — LLM profile selector in AgentWorkspacePage

**Files:**
- Modify: `services/web-dashboard/src/api.js:58-62`
- Modify: `services/web-dashboard/src/hooks/useAgentLogs.js:31-33`
- Modify: `services/web-dashboard/src/components/pages/AgentWorkspacePage.jsx`

**Step 1: Update `api.js` trigger function**

```js
trigger: (pinnedDocIds = [], llmProfile = 'default') =>
  fetch(`${AGENT}/api/v1/agent/trigger`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      pinned_doc_ids: pinnedDocIds,
      llm_profile: llmProfile,
    }),
  }),
```

**Step 2: Update `useAgentLogs.js` mutationFn**

```js
const triggerMutation = useMutation({
  mutationFn: ({ pinnedDocIds = [], llmProfile = 'default' } = {}) =>
    API.agent.trigger(pinnedDocIds, llmProfile),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: LOGS_KEY }),
});
```

Update the returned `trigger` to propagate the shape:
```js
trigger: triggerMutation.mutate,
```
(callers must now pass `{ pinnedDocIds, llmProfile }`)

**Step 3: Update `AgentWorkspacePage.jsx`**

Add state:
```jsx
const [llmProfile, setLlmProfile] = useState('default');
```

Add a profile selector card above the control panel (shown when not running):
```jsx
{!isRunning && (
  <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-4">
    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
      Generation Profile
    </p>
    <div className="flex gap-2">
      {['default', 'premium'].map(p => (
        <button
          key={p}
          onClick={() => setLlmProfile(p)}
          className={`px-4 py-2 rounded-lg text-sm font-semibold transition-colors border ${
            llmProfile === p
              ? 'bg-indigo-600 text-white border-indigo-600'
              : 'bg-white text-slate-600 border-slate-200 hover:border-indigo-400'
          }`}
        >
          {p === 'default' ? 'Default (qwen2.5:14b)' : 'Premium (gemma4:26b)'}
        </button>
      ))}
    </div>
    <p className="text-xs text-slate-400 mt-1.5">
      {llmProfile === 'premium'
        ? 'Higher quality — slower. Use for complex integrations.'
        : 'Balanced — good quality at stable latency.'}
    </p>
  </div>
)}
```

Update `handleStart`:
```jsx
const handleStart = () => {
  setLocalError(null);
  trigger(
    { pinnedDocIds, llmProfile },
    { onError: (e) => { setLocalError(e.message || 'Failed to start agent'); setStatus('error'); } }
  );
};
```

**Step 4: Manual smoke test**

Start the UI dev server (if available) and verify:
- Default/Premium buttons appear when idle
- Selected profile is highlighted
- Buttons disappear during run
- API call body contains correct `llm_profile` value

**Step 5: Commit**

```bash
git add services/web-dashboard/src/api.js \
        services/web-dashboard/src/hooks/useAgentLogs.js \
        services/web-dashboard/src/components/pages/AgentWorkspacePage.jsx
git commit -m "feat(ui): add LLM profile selector (Default/Premium) to AgentWorkspacePage (ADR-046)"
```

---

### Task 7: Write ADR-046

**File:** `docs/adr/ADR-046-llm-profile-routing.md`

Document:
- Context: new EC2 m7i.4xlarge, CPU-only, three use-case profiles
- Decision: three named profiles with explicit Ollama option sets
- Alternatives considered: single configurable model, runtime admin-only switch
- Consequences: slight API surface growth, UI toggle
- Validation plan
- Rollback: set `llm_profile="default"` in trigger; env var overrides always win

**Commit:**

```bash
git add docs/adr/ADR-046-llm-profile-routing.md
git commit -m "docs(adr): ADR-046 LLM multi-profile routing"
```

---

### Task 8: Update documentation

**Files:**
- `docs/architecture_specification.md`
- `docs/functional-guide.md`

Add ADR-046 to the ADR table. Update LLM settings section to document the three profiles and new Ollama options.

**Commit:**

```bash
git add docs/architecture_specification.md docs/functional-guide.md
git commit -m "docs: document LLM multi-profile routing (ADR-046)"
```

---

### Task 9: Run full test suite

```bash
cd services/integration-agent && python -m pytest tests/ -v
```
Expected: all tests pass (329+ collected, ≤2 pre-existing failures in test_config.py for model name).

---
