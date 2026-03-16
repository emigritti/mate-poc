# LLM Settings, KB Nav, Docs Update — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a persistent LLM Settings admin page (MongoDB-backed, in-memory-effective), move Knowledge Base to its own nav section with no top bar, and update architecture + functional docs.

**Architecture:**
A module-level `_llm_overrides: dict` in `main.py` acts as the active-settings layer consulted by `generate_with_ollama()` and `_suggest_tags_via_llm()` before falling back to `settings.*`. Three new endpoints read/write/reset this dict + a MongoDB `llm_settings` collection. The frontend `LlmSettingsPage` PATCHes the endpoint and shows live defaults vs. overrides. KB nav move is a pure Sidebar/App.jsx change.

**Tech Stack:** FastAPI, Motor (MongoDB async), Pydantic v2, React 18, Tailwind CSS, Lucide icons.

---

## Task 1: Backend — `db.py` + `_llm_overrides` in `main.py`

**Files:**
- Modify: `services/integration-agent/db.py`
- Modify: `services/integration-agent/main.py`

### Context
`db.py` exposes module-level collection vars (e.g. `catalog_col`). We add `llm_settings_col` the same way.
`main.py` already has a module-level `_llm_overrides: dict = {}` pattern implied by the design — we introduce it explicitly.

### Step 1: Add `llm_settings_col` to `db.py`

Open `services/integration-agent/db.py`.

After line 34 (`kb_documents_col: motor... | None = None`), add:
```python
llm_settings_col: motor.motor_asyncio.AsyncIOMotorCollection | None = None
```

In `init_db`, after line 60 (`kb_documents_col = _db["kb_documents"]`), add:
```python
            llm_settings_col = _db["llm_settings"]
```

In the `global` declaration inside `init_db` (line 44), append `, llm_settings_col`.

### Step 2: Add `_llm_overrides` dict + startup loader to `main.py`

Find the block of module-level globals (look for `catalog: dict = {}` — around line 320). After all the `= {}` / `= []` globals, add:

```python
# ── LLM runtime overrides (ADR-022) ──────────────────────────────────────────
# Populated at startup from MongoDB llm_settings collection.
# Consulted by generate_with_ollama() and _suggest_tags_via_llm()
# before falling back to settings.* pydantic defaults.
_llm_overrides: dict = {}
```

### Step 3: Load overrides at startup

Find the `lifespan` async function (look for `@asynccontextmanager` + `async def lifespan`). After `await db.init_db()` completes, add:

```python
    # Load persisted LLM overrides from MongoDB
    if db.llm_settings_col is not None:
        doc = await db.llm_settings_col.find_one({"_id": "current"})
        if doc:
            doc.pop("_id", None)
            _llm_overrides.update(doc)
            logger.info("[LLM-SETTINGS] Loaded %d overrides from MongoDB.", len(_llm_overrides))
```

### Step 4: Apply `_llm_overrides` in `generate_with_ollama()`

Find `generate_with_ollama()` (line ~390). Change the three resolution lines:

**Before:**
```python
    _num_predict = num_predict if num_predict is not None else settings.ollama_num_predict
    _timeout     = timeout     if timeout     is not None else settings.ollama_timeout_seconds
    _temperature = temperature if temperature is not None else settings.ollama_temperature
```

**After:**
```python
    _num_predict = num_predict if num_predict is not None else _llm_overrides.get("num_predict",      settings.ollama_num_predict)
    _timeout     = timeout     if timeout     is not None else _llm_overrides.get("timeout_seconds",  settings.ollama_timeout_seconds)
    _temperature = temperature if temperature is not None else _llm_overrides.get("temperature",      settings.ollama_temperature)
    _model       = _llm_overrides.get("model", settings.ollama_model)
```

Then replace every reference to `settings.ollama_model` inside that function body with `_model`:
- In the `log_agent` call: `f"[LLM] → model={_model} ..."`
- In the `client.post` json body: `"model": _model`

### Step 5: Apply `_llm_overrides` in `_suggest_tags_via_llm()`

Find `_suggest_tags_via_llm()` (line ~467). Change the call to `generate_with_ollama`:

**Before:**
```python
    raw = await generate_with_ollama(
        prompt,
        num_predict=settings.tag_num_predict,
        timeout=settings.tag_timeout_seconds,
        temperature=settings.tag_temperature,
    )
```

**After:**
```python
    raw = await generate_with_ollama(
        prompt,
        num_predict=_llm_overrides.get("tag_num_predict",    settings.tag_num_predict),
        timeout=_llm_overrides.get("tag_timeout_seconds", settings.tag_timeout_seconds),
        temperature=_llm_overrides.get("tag_temperature",    settings.tag_temperature),
    )
```

### Step 6: Apply `_llm_overrides` for `rag_max_chars`

Search for `settings.ollama_rag_max_chars` in main.py — it's used when truncating the RAG context injected into the prompt (look in the agent flow, around line 650–680). Replace every occurrence with:
```python
_llm_overrides.get("rag_max_chars", settings.ollama_rag_max_chars)
```

### Step 7: Commit
```bash
git add services/integration-agent/db.py services/integration-agent/main.py
git commit -m "feat(backend): add _llm_overrides dict wired into generate_with_ollama and tag helper"
```

---

## Task 2: Backend — 3 LLM settings endpoints + reset_all update

**Files:**
- Modify: `services/integration-agent/main.py`

### Context
Three endpoints:
1. `GET /api/v1/admin/llm-settings` — returns current effective values + design defaults
2. `PATCH /api/v1/admin/llm-settings` — updates `_llm_overrides` + persists to MongoDB
3. `POST /api/v1/admin/llm-settings/reset` — clears `_llm_overrides` + deletes MongoDB doc

All require `_require_token`. `reset_all` must also clear LLM overrides.

### Step 1: Add helper to build the settings response

Find the Project Docs section (line ~1188). Add a new section before it:

```python
# ── LLM Settings (admin) ──────────────────────────────────────────────────────

def _llm_settings_response() -> dict:
    """Build the current LLM settings response (effective values + design defaults)."""
    defaults = {
        "doc_llm": {
            "model":           settings.ollama_model,
            "num_predict":     settings.ollama_num_predict,
            "timeout_seconds": settings.ollama_timeout_seconds,
            "temperature":     settings.ollama_temperature,
            "rag_max_chars":   settings.ollama_rag_max_chars,
        },
        "tag_llm": {
            "num_predict":     settings.tag_num_predict,
            "timeout_seconds": settings.tag_timeout_seconds,
            "temperature":     settings.tag_temperature,
        },
    }
    effective = {
        "doc_llm": {
            "model":           _llm_overrides.get("model",           settings.ollama_model),
            "num_predict":     _llm_overrides.get("num_predict",      settings.ollama_num_predict),
            "timeout_seconds": _llm_overrides.get("timeout_seconds",  settings.ollama_timeout_seconds),
            "temperature":     _llm_overrides.get("temperature",      settings.ollama_temperature),
            "rag_max_chars":   _llm_overrides.get("rag_max_chars",    settings.ollama_rag_max_chars),
        },
        "tag_llm": {
            "num_predict":     _llm_overrides.get("tag_num_predict",    settings.tag_num_predict),
            "timeout_seconds": _llm_overrides.get("tag_timeout_seconds", settings.tag_timeout_seconds),
            "temperature":     _llm_overrides.get("tag_temperature",    settings.tag_temperature),
        },
    }
    return {
        "status": "success",
        "data": {
            "effective": effective,
            "defaults":  defaults,
            "overrides_active": bool(_llm_overrides),
        },
    }
```

### Step 2: Add the three endpoints

```python
@app.get("/api/v1/admin/llm-settings", tags=["admin"])
async def get_llm_settings(
    _token: str = Depends(_require_token),
) -> dict:
    """Return current effective LLM parameters and design defaults."""
    return _llm_settings_response()


@app.patch("/api/v1/admin/llm-settings", tags=["admin"])
async def patch_llm_settings(
    body: dict,
    _token: str = Depends(_require_token),
) -> dict:
    """
    Partially update LLM runtime parameters.

    Accepted body shape:
      { "doc_llm": { "temperature": 0.5, "num_predict": 800 },
        "tag_llm": { "timeout_seconds": 20 } }

    Changes are applied immediately to _llm_overrides (no restart needed)
    and persisted to MongoDB for survival across restarts.
    """
    global _llm_overrides

    # Flatten the two-group body into the flat _llm_overrides key space
    DOC_FIELDS = {"model", "num_predict", "timeout_seconds", "temperature", "rag_max_chars"}
    TAG_FIELDS = {"tag_num_predict", "tag_timeout_seconds", "tag_temperature"}

    if "doc_llm" in body:
        for k, v in body["doc_llm"].items():
            if k in DOC_FIELDS:
                _llm_overrides[k] = v

    if "tag_llm" in body:
        for k, v in body["tag_llm"].items():
            flat_key = f"tag_{k}"  # e.g. "num_predict" → "tag_num_predict"
            if flat_key in TAG_FIELDS:
                _llm_overrides[flat_key] = v

    # Persist to MongoDB
    if db.llm_settings_col is not None:
        await db.llm_settings_col.replace_one(
            {"_id": "current"},
            {"_id": "current", **_llm_overrides},
            upsert=True,
        )

    logger.info("[LLM-SETTINGS] Overrides updated: %s", _llm_overrides)
    return _llm_settings_response()


@app.post("/api/v1/admin/llm-settings/reset", tags=["admin"])
async def reset_llm_settings(
    _token: str = Depends(_require_token),
) -> dict:
    """Reset all LLM parameters to design defaults (clears MongoDB doc + in-memory overrides)."""
    global _llm_overrides
    _llm_overrides.clear()
    if db.llm_settings_col is not None:
        await db.llm_settings_col.delete_one({"_id": "current"})
    logger.info("[LLM-SETTINGS] Reset to design defaults.")
    return _llm_settings_response()
```

### Step 3: Update `reset_all` to also clear LLM overrides

Find `reset_all` (line ~1139). Add inside the function body, after `kb_docs.clear()`:

```python
    # 4. LLM overrides
    _llm_overrides.clear()
    if db.llm_settings_col is not None:
        await db.llm_settings_col.delete_one({"_id": "current"})
```

Also add `_llm_overrides` to the `global` declaration at the top of `reset_all`.

### Step 4: Commit
```bash
git add services/integration-agent/main.py
git commit -m "feat(backend): add GET/PATCH/POST llm-settings endpoints with MongoDB persistence and in-memory apply"
```

---

## Task 3: Backend — unit tests for LLM settings

**Files:**
- Create: `services/integration-agent/tests/test_llm_settings.py`

### Step 1: Create the test file

```python
"""Unit tests for GET/PATCH/POST /api/v1/admin/llm-settings."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_overrides():
    """Ensure _llm_overrides is clean before and after each test."""
    import main
    main._llm_overrides.clear()
    yield
    main._llm_overrides.clear()


def test_get_llm_settings_returns_defaults(client):
    """GET returns effective == defaults when no overrides are set."""
    res = client.get("/api/v1/admin/llm-settings")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["data"]["overrides_active"] is False
    assert data["data"]["effective"]["doc_llm"] == data["data"]["defaults"]["doc_llm"]
    assert data["data"]["effective"]["tag_llm"] == data["data"]["defaults"]["tag_llm"]


def test_get_llm_settings_structure(client):
    """Response contains expected keys in both doc_llm and tag_llm groups."""
    data = client.get("/api/v1/admin/llm-settings").json()["data"]
    assert set(data["effective"]["doc_llm"].keys()) == {
        "model", "num_predict", "timeout_seconds", "temperature", "rag_max_chars"
    }
    assert set(data["effective"]["tag_llm"].keys()) == {
        "num_predict", "timeout_seconds", "temperature"
    }


def test_patch_doc_llm_updates_effective(client):
    """PATCH doc_llm.temperature is reflected immediately in effective values."""
    res = client.patch(
        "/api/v1/admin/llm-settings",
        json={"doc_llm": {"temperature": 0.9}},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["effective"]["doc_llm"]["temperature"] == 0.9
    assert data["overrides_active"] is True


def test_patch_tag_llm_updates_effective(client):
    """PATCH tag_llm.timeout_seconds is reflected immediately."""
    res = client.patch(
        "/api/v1/admin/llm-settings",
        json={"tag_llm": {"timeout_seconds": 30}},
    )
    assert res.status_code == 200
    assert res.json()["data"]["effective"]["tag_llm"]["timeout_seconds"] == 30


def test_patch_unknown_field_ignored(client):
    """PATCH with an unknown field is silently ignored (no crash, no effect)."""
    res = client.patch(
        "/api/v1/admin/llm-settings",
        json={"doc_llm": {"unknown_field": 999}},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["overrides_active"] is False  # no valid field was set


def test_reset_clears_overrides(client):
    """POST /reset clears all overrides and restores defaults."""
    # First set an override
    client.patch("/api/v1/admin/llm-settings", json={"doc_llm": {"temperature": 0.9}})
    # Now reset
    res = client.post("/api/v1/admin/llm-settings/reset")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["overrides_active"] is False
    assert data["effective"]["doc_llm"] == data["defaults"]["doc_llm"]


def test_overrides_applied_to_generate_with_ollama(monkeypatch):
    """_llm_overrides values are used by generate_with_ollama over settings defaults."""
    import main
    from config import settings
    captured = {}

    async def _mock_post(self, url, *, json=None, **kwargs):
        captured["num_predict"] = json["options"]["num_predict"]
        captured["temperature"] = json["options"]["temperature"]
        captured["model"]       = json["model"]
        class _R:
            def raise_for_status(self): pass
            def json(self): return {"response": "ok", "eval_count": 1,
                                    "eval_duration": 1e9, "total_duration": 1e9,
                                    "load_duration": 0, "prompt_eval_count": 10}
        return _R()

    monkeypatch.setattr("httpx.AsyncClient.post", _mock_post)
    main._llm_overrides["num_predict"]    = 42
    main._llm_overrides["temperature"]    = 0.99
    main._llm_overrides["timeout_seconds"] = 5

    import asyncio
    asyncio.run(main.generate_with_ollama("hello"))

    assert captured["num_predict"] == 42
    assert captured["temperature"] == 0.99
```

### Step 2: Run the new tests
```bash
cd services/integration-agent && python -m pytest tests/test_llm_settings.py -v
```
Expected: 8/8 PASS.

### Step 3: Run full test suite
```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```
Expected: all previously passing + 8 new = all green.

### Step 4: Commit
```bash
git add services/integration-agent/tests/test_llm_settings.py
git commit -m "test(backend): unit tests for LLM settings endpoints and override application"
```

---

## Task 4: Frontend — `api.js` + `LlmSettingsPage.jsx`

**Files:**
- Modify: `services/web-dashboard/src/api.js`
- Create: `services/web-dashboard/src/components/pages/LlmSettingsPage.jsx`

### Step 1: Add `llmSettings` group to `api.js`

Open `services/web-dashboard/src/api.js`. After the `projectDocs:` block, add:

```js
  llmSettings: {
    get:   ()     => fetch(`${getBase()}/api/v1/admin/llm-settings`),
    patch: (body) => fetch(`${getBase()}/api/v1/admin/llm-settings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    reset: ()     => fetch(`${getBase()}/api/v1/admin/llm-settings/reset`, { method: 'POST' }),
  },
```

### Step 2: Create `LlmSettingsPage.jsx`

```jsx
import { useState, useEffect } from 'react';
import { SlidersHorizontal, RotateCcw, Save, AlertCircle, CheckCircle2, Loader2, Info } from 'lucide-react';
import { API } from '../../api.js';

// ── Field metadata ─────────────────────────────────────────────────────────────
const DOC_FIELDS = [
  { key: 'model',           label: 'Model',              type: 'text',   unit: '',    hint: 'Ollama model name (e.g. llama3.1:8b)' },
  { key: 'num_predict',     label: 'Max Tokens',         type: 'number', unit: 'tok', hint: 'Token cap for document generation (~3 tok/s on CPU)' },
  { key: 'timeout_seconds', label: 'Timeout',            type: 'number', unit: 's',   hint: 'HTTP timeout for document generation calls' },
  { key: 'temperature',     label: 'Temperature',        type: 'number', unit: '',    step: 0.01, hint: '0 = deterministic, 1 = creative' },
  { key: 'rag_max_chars',   label: 'RAG Context Limit',  type: 'number', unit: 'ch',  hint: 'Max characters of past-approved context injected into prompt' },
];

const TAG_FIELDS = [
  { key: 'num_predict',     label: 'Max Tokens',  type: 'number', unit: 'tok', hint: 'Token cap for tag suggestion (~15 tokens needed)' },
  { key: 'timeout_seconds', label: 'Timeout',     type: 'number', unit: 's',   hint: 'HTTP timeout for tag suggestion calls' },
  { key: 'temperature',     label: 'Temperature', type: 'number', unit: '',    step: 0.01, hint: '0 = fully deterministic' },
];

function FieldRow({ fieldMeta, effectiveVal, defaultVal, groupKey, onUpdate }) {
  const isOverridden = effectiveVal !== defaultVal;
  const { key, label, type, unit, step, hint } = fieldMeta;

  return (
    <div className="flex items-start gap-4 py-3 border-b border-slate-100 last:border-0">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-700">{label}</span>
          {unit && <span className="text-[10px] text-slate-400 font-mono bg-slate-100 px-1.5 py-0.5 rounded">{unit}</span>}
          {isOverridden && (
            <span className="text-[10px] font-bold text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-200">
              MODIFIED
            </span>
          )}
        </div>
        <p className="text-xs text-slate-400 mt-0.5">{hint}</p>
        {isOverridden && (
          <p className="text-[10px] text-slate-400 mt-0.5 font-mono">default: {String(defaultVal)}</p>
        )}
      </div>
      <input
        type={type}
        step={step ?? (type === 'number' ? 1 : undefined)}
        value={effectiveVal}
        onChange={e => {
          const raw = e.target.value;
          const val = type === 'number' ? (raw.includes('.') ? parseFloat(raw) : parseInt(raw, 10)) : raw;
          onUpdate(groupKey, key, val);
        }}
        className={`w-36 text-sm px-3 py-1.5 rounded-lg border transition-colors font-mono ${
          isOverridden
            ? 'border-amber-300 bg-amber-50 focus:border-amber-400'
            : 'border-slate-200 bg-white focus:border-indigo-400'
        } focus:outline-none focus:ring-2 focus:ring-indigo-100`}
      />
    </div>
  );
}

function SettingsCard({ title, icon: Icon, fields, effective, defaults, groupKey, onUpdate }) {
  const hasOverrides = fields.some(f => effective[f.key] !== defaults[f.key]);
  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
      <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50 flex items-center gap-2">
        <Icon size={14} className="text-slate-400" />
        <span className="text-sm font-semibold text-slate-700" style={{ fontFamily: 'Outfit, sans-serif' }}>{title}</span>
        {hasOverrides && (
          <span className="ml-auto text-[10px] font-bold text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-200">
            {fields.filter(f => effective[f.key] !== defaults[f.key]).length} override(s) active
          </span>
        )}
      </div>
      <div className="px-5">
        {fields.map(f => (
          <FieldRow
            key={f.key}
            fieldMeta={f}
            effectiveVal={effective[f.key]}
            defaultVal={defaults[f.key]}
            groupKey={groupKey}
            onUpdate={onUpdate}
          />
        ))}
      </div>
    </div>
  );
}

export default function LlmSettingsPage() {
  const [data,       setData]       = useState(null);   // { effective, defaults, overrides_active }
  const [draft,      setDraft]      = useState(null);   // local edits not yet saved
  const [loading,    setLoading]    = useState(true);
  const [saving,     setSaving]     = useState(false);
  const [resetting,  setResetting]  = useState(false);
  const [feedback,   setFeedback]   = useState(null);   // { type: 'success'|'error', msg }

  const load = async () => {
    setLoading(true);
    try {
      const res = await API.llmSettings.get();
      const d   = await res.json();
      if (!res.ok) throw new Error(d.detail || `Error ${res.status}`);
      setData(d.data);
      setDraft(structuredClone(d.data.effective));
    } catch (e) {
      setFeedback({ type: 'error', msg: e.message || 'Failed to load settings' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const updateDraft = (group, key, val) => {
    setDraft(prev => ({ ...prev, [group]: { ...prev[group], [key]: val } }));
  };

  const save = async () => {
    setSaving(true);
    setFeedback(null);
    try {
      const body = {};
      // Only send groups that have changes
      const docChanges = {};
      DOC_FIELDS.forEach(({ key }) => {
        if (draft.doc_llm[key] !== data.defaults.doc_llm[key]) docChanges[key] = draft.doc_llm[key];
      });
      const tagChanges = {};
      TAG_FIELDS.forEach(({ key }) => {
        if (draft.tag_llm[key] !== data.defaults.tag_llm[key]) tagChanges[key] = draft.tag_llm[key];
      });
      if (Object.keys(docChanges).length) body.doc_llm = docChanges;
      if (Object.keys(tagChanges).length) body.tag_llm = tagChanges;

      const res = await API.llmSettings.patch(body);
      const d   = await res.json();
      if (!res.ok) throw new Error(d.detail || `Error ${res.status}`);
      setData(d.data);
      setDraft(structuredClone(d.data.effective));
      setFeedback({ type: 'success', msg: 'Settings saved and applied immediately.' });
    } catch (e) {
      setFeedback({ type: 'error', msg: e.message || 'Save failed' });
    } finally {
      setSaving(false);
    }
  };

  const resetAll = async () => {
    setResetting(true);
    setFeedback(null);
    try {
      const res = await API.llmSettings.reset();
      const d   = await res.json();
      if (!res.ok) throw new Error(d.detail || `Error ${res.status}`);
      setData(d.data);
      setDraft(structuredClone(d.data.effective));
      setFeedback({ type: 'success', msg: 'Reset to design defaults.' });
    } catch (e) {
      setFeedback({ type: 'error', msg: e.message || 'Reset failed' });
    } finally {
      setResetting(false);
    }
  };

  const isDirty = draft && data && (
    DOC_FIELDS.some(({ key }) => draft.doc_llm[key] !== data.effective.doc_llm[key]) ||
    TAG_FIELDS.some(({ key }) => draft.tag_llm[key] !== data.effective.tag_llm[key])
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={24} className="animate-spin text-indigo-400" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-5">

      {/* Info banner */}
      <div className="flex items-start gap-3 px-4 py-3 bg-indigo-50 border border-indigo-200 rounded-xl text-sm text-indigo-700">
        <Info size={15} className="flex-shrink-0 mt-0.5" />
        <span>
          Changes apply <strong>immediately</strong> without restart and are persisted in MongoDB.
          Full Reset restores the values configured at design time (env vars / pydantic defaults).
        </span>
      </div>

      {/* Feedback */}
      {feedback && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-xl text-sm border ${
          feedback.type === 'success'
            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
            : 'bg-rose-50 border-rose-200 text-rose-700'
        }`}>
          {feedback.type === 'success'
            ? <CheckCircle2 size={15} />
            : <AlertCircle size={15} />
          }
          {feedback.msg}
        </div>
      )}

      {/* Settings cards */}
      {draft && data && (
        <>
          <SettingsCard
            title="Document Generation LLM"
            icon={SlidersHorizontal}
            fields={DOC_FIELDS}
            effective={draft.doc_llm}
            defaults={data.defaults.doc_llm}
            groupKey="doc_llm"
            onUpdate={updateDraft}
          />
          <SettingsCard
            title="Tag Suggestion LLM"
            icon={SlidersHorizontal}
            fields={TAG_FIELDS}
            effective={draft.tag_llm}
            defaults={data.defaults.tag_llm}
            groupKey="tag_llm"
            onUpdate={updateDraft}
          />
        </>
      )}

      {/* Action buttons */}
      <div className="flex items-center justify-between pt-2">
        <button
          onClick={resetAll}
          disabled={resetting || (!data?.overrides_active && !isDirty)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-slate-600 border border-slate-200 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {resetting ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
          Reset to Defaults
        </button>

        <button
          onClick={save}
          disabled={saving || !isDirty}
          className="flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm shadow-indigo-200"
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          Save Changes
        </button>
      </div>

    </div>
  );
}
```

### Step 3: Commit
```bash
git add services/web-dashboard/src/api.js services/web-dashboard/src/components/pages/LlmSettingsPage.jsx
git commit -m "feat(frontend): add LlmSettingsPage with two-group card layout and PATCH/reset wiring"
```

---

## Task 5: Frontend — Nav restructure + hide TopBar on KB + wire LlmSettingsPage

**Files:**
- Modify: `services/web-dashboard/src/App.jsx`
- Modify: `services/web-dashboard/src/components/layout/Sidebar.jsx`

### Context
Current `Sidebar.jsx` NAV_GROUPS:
```
Workflow: [requirements, kb, apis, agent]
Results:  [catalog, documents, approvals]
Admin:    [reset, project-docs]
```

Target:
```
Workflow:       [requirements, apis, agent]
Knowledge Base: [kb]
Results:        [catalog, documents, approvals]
Admin:          [reset, project-docs, llm-settings]
```

`App.jsx` `PAGE_META` needs `hideTopBar: true` for `kb` and a new entry for `llm-settings`.

### Step 1: Update `Sidebar.jsx`

Read the current file. Then update `NAV_GROUPS`:

```js
import { Upload, Plug, Bot, BookOpen, FileText, CheckSquare, Trash2, Zap, Library, BookMarked, SlidersHorizontal } from 'lucide-react';

const NAV_GROUPS = [
  {
    label: 'Workflow',
    items: [
      { id: 'requirements', label: 'Requirements',    icon: Upload },
      { id: 'apis',         label: 'API Systems',      icon: Plug   },
      { id: 'agent',        label: 'Agent Workspace',  icon: Bot    },
    ],
  },
  {
    label: 'Knowledge Base',
    items: [
      { id: 'kb', label: 'Knowledge Base', icon: Library },
    ],
  },
  {
    label: 'Results',
    items: [
      { id: 'catalog',   label: 'Integration Catalog', icon: BookOpen    },
      { id: 'documents', label: 'Generated Docs',       icon: FileText    },
      { id: 'approvals', label: 'HITL Approvals',       icon: CheckSquare },
    ],
  },
  {
    label: 'Admin',
    items: [
      { id: 'reset',        label: 'Reset Tools',   icon: Trash2           },
      { id: 'project-docs', label: 'Project Docs',  icon: BookMarked       },
      { id: 'llm-settings', label: 'LLM Settings',  icon: SlidersHorizontal },
    ],
  },
];
```

### Step 2: Update `App.jsx`

Add import:
```jsx
import LlmSettingsPage from './components/pages/LlmSettingsPage.jsx';
```

Update `PAGE_META` — add `hideTopBar` flag to `kb` and add new `llm-settings` entry:
```js
  kb:             { title: 'Knowledge Base',  subtitle: 'Best practices document library',              step: null, hideTopBar: true },
  // ... existing entries unchanged ...
  'llm-settings': { title: 'LLM Settings',   subtitle: 'Tune model parameters and test response times', step: null },
```

(Keep all other entries exactly as they are — only add `hideTopBar: true` to `kb` and add the `llm-settings` entry.)

Update the `renderPage` switch — add the new case:
```jsx
    case 'llm-settings': return <LlmSettingsPage />;
```

Update the JSX where `TopBar` and `WorkflowStepper` are rendered. Find:
```jsx
        <TopBar title={meta.title} subtitle={meta.subtitle} />
        {meta.step !== null && <WorkflowStepper activeStep={meta.step} />}
```
Replace with:
```jsx
        {!meta.hideTopBar && <TopBar title={meta.title} subtitle={meta.subtitle} />}
        {meta.step !== null && !meta.hideTopBar && <WorkflowStepper activeStep={meta.step} />}
```

### Step 3: Build check
```bash
cd services/web-dashboard && npm run build 2>&1 | tail -6
```
Expected: `✓ built in Xs` — no errors.

### Step 4: Commit
```bash
git add services/web-dashboard/src/App.jsx services/web-dashboard/src/components/layout/Sidebar.jsx
git commit -m "feat(nav): move KB to dedicated section, hide TopBar on KB page, add LLM Settings to Admin"
```

---

## Task 6: Docs — Update `architecture_specification.md`

**Files:**
- Modify: `docs/architecture_specification.md`

### Context
The doc is 1648 lines, version 2.1.0, dated 2026-03-11. It must be updated to v2.2.0 with a new date and sections covering the features added since then: Knowledge Base, LLM Settings, Project Docs admin page, ADR-019 through ADR-022.

### What to update (minimal diffs — do NOT rewrite the whole file):

1. **Header table** — version → `2.2.0`, date → `2026-03-16`

2. **Section 1.1 Executive Summary** — add to the numbered list:
   - `5. **Knowledge Base** — Multi-format document library (PDF/DOCX/XLSX/PPTX/MD) enabling best-practice injection into the RAG prompt`
   - `6. **LLM Settings** — Admin-configurable runtime overrides for model parameters, persisted in MongoDB`

3. **Section 6 Component Specification** — add two new subsections for `KnowledgeBasePage` and `LlmSettingsPage` following the existing component table pattern.

4. **Section 10 API Surface** — add the new endpoints:
   - `GET/PATCH/POST /api/v1/admin/llm-settings`
   - `GET /api/v1/admin/docs` and `GET /api/v1/admin/docs/{path}`
   - `GET/POST/DELETE /api/v1/kb/*`

5. **Section 18 ADR Index** — add ADR-019 through ADR-022 entries.

6. **Section 19 Known Limitations** — remove the item about "LLM parameters not configurable at runtime" if present; add note about LLM settings now being configurable.

### Step 1: Read the file section by section (use offset/limit to avoid loading 1648 lines at once)
Read lines 1–100 (header + ToC), then targeted sections as needed.

### Step 2: Apply the minimal updates listed above using the Edit tool.

### Step 3: Commit
```bash
git add docs/architecture_specification.md
git commit -m "docs: update architecture_specification.md to v2.2.0 — KB, LLM Settings, Project Docs, ADR-019–022"
```

---

## Task 7: Docs — Update `functional-guide.md`

**Files:**
- Modify: `docs/functional-guide.md`

### Context
The guide is 563 lines. It describes the end-to-end workflow up to v2.1. New features to document: Knowledge Base step in the workflow, LLM runtime tuning, admin tools (Reset, Project Docs, LLM Settings).

### What to update (minimal diffs):

1. **Section 3 — "How It Works End to End"** — add step `1b. Upload Best-Practice Documents to Knowledge Base`: explain that architects can pre-load approved integration patterns as PDF/DOCX/etc., which are chunked, embedded, and retrieved alongside approved examples.

2. **Section 7 — "How Each Tool Is Used in Practice"** — add subsections:
   - `7.x ChromaDB — Knowledge Base collection`: describe the `knowledge_base` collection vs `approved_integrations`.
   - `7.x MongoDB — llm_settings collection`: describe runtime override persistence.

3. **Section 10 — "Security Model"** or add a new **Section 11 — "Admin Tools"** describing:
   - Reset Tools (full reset behaviour, including LLM settings reset)
   - Project Docs (read-only markdown browser)
   - LLM Settings (runtime parameter override with MongoDB persistence, reset to design defaults on full reset)

4. **Table of Contents** — update section numbers if new sections are added.

### Step 1: Read the file (it's 563 lines — read in 2 chunks).
### Step 2: Apply the minimal updates using the Edit tool.
### Step 3: Commit
```bash
git add docs/functional-guide.md
git commit -m "docs: update functional-guide.md — KB workflow step, LLM settings, admin tools section"
```

---

## Task 8: Final verification + push

### Step 1: Run full backend test suite
```bash
cd services/integration-agent && python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```
Expected: all tests pass (160+ green).

### Step 2: Frontend build
```bash
cd services/web-dashboard && npm run build 2>&1 | tail -6
```
Expected: `✓ built` — no errors.

### Step 3: Push
```bash
git push origin main
```
