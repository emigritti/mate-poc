# Phase 4 — Polish Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete Phase 4 consolidation (R4, R6, R7, R18, R19) from `architecture_analysis.md` — component decomposition, toast system, language consistency, real progress tracking, and audit event log.

**Architecture:**
- R6 (toast) comes first — extracted KB/Requirements components call `toast.error()` directly instead of propagating `onError` props.
- R4 extracts 6 inline sub-components from KnowledgeBasePage (818 lines) and 1 from RequirementsPage into dedicated files under `src/components/kb/` and `src/components/requirements/`.
- R18 adds `agent_progress` to `state.py`, updates it during `run_agentic_rag_flow`, and exposes it via the `/agent/logs` endpoint so the frontend can show a real progress bar instead of a fake timer.
- R19 MVP adds an append-only audit event log in MongoDB (`events` collection) at key mutation points; full event-replay state reconstruction is deferred.

**Tech Stack:** React 18 + Vite + Tailwind, sonner (new), FastAPI + MongoDB, pytest

---

## Task 1: R6 — Install sonner and add global Toaster

**Files:**
- Modify: `services/web-dashboard/package.json` (install)
- Modify: `services/web-dashboard/src/App.jsx`

**Step 1: Install sonner**

```bash
cd services/web-dashboard && npm install sonner
```

Expected: `sonner` appears in `package.json` dependencies.

**Step 2: Add Toaster to App.jsx**

In `src/App.jsx`, add the import at the top:

```jsx
import { Toaster } from 'sonner';
```

Inside the `<QueryClientProvider>` wrapper (first child, before the outer div):

```jsx
return (
  <QueryClientProvider client={queryClient}>
    <Toaster position="top-right" richColors closeButton />
    <div className="flex h-screen bg-slate-50 overflow-hidden">
      {/* ... rest unchanged ... */}
    </div>
  </QueryClientProvider>
);
```

**Step 3: Verify build**

```bash
cd services/web-dashboard && npm run build
```

Expected: Build completes with no errors.

**Step 4: Commit**

```bash
git add services/web-dashboard/package.json services/web-dashboard/package-lock.json services/web-dashboard/src/App.jsx
git commit -m "feat(fe): add sonner global toast system (R6)"
```

---

## Task 2: R4 — Create KB helpers module

**Files:**
- Create: `services/web-dashboard/src/components/kb/kbHelpers.js`

**Step 1: Create kbHelpers.js**

Extract the module-level utilities from `KnowledgeBasePage.jsx` (lines 10–89):

```js
// src/components/kb/kbHelpers.js
// Shared utilities for Knowledge Base components.

export const FILE_TYPE_ICONS_MAP = {
    pdf: 'FileText',
    docx: 'FileType',
    xlsx: 'FileSpreadsheet',
    pptx: 'Presentation',
    md: 'FileText',
};

export const FILE_TYPE_LABELS = {
    pdf: 'PDF',
    docx: 'Word',
    xlsx: 'Excel',
    pptx: 'PowerPoint',
    md: 'Markdown',
};

export const ACCEPTED_EXTENSIONS = '.pdf,.docx,.doc,.xlsx,.xls,.pptx,.ppt,.md,.txt';

export function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1_048_576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1_048_576).toFixed(1)} MB`;
}

export function formatDate(iso) {
    try {
        return new Date(iso).toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
        });
    } catch {
        return iso;
    }
}

/**
 * Merge KB-uploaded docs and promoted integration docs into a single array.
 * Only integration docs with kb_status === "promoted" are included.
 */
export function normalizeKBDocs(kbList = [], intList = []) {
    const uploaded = kbList.map(d => ({
        id: d.id,
        name: d.filename,
        tags: d.tags || [],
        date: d.uploaded_at,
        source: d.file_type === 'url' ? 'url' : 'uploaded',
        previewText: d.content_preview || '',
        chunkCount: d.chunk_count,
        url: d.url || null,
        _kbDoc: d,
    }));
    const integration = intList
        .filter(d => d.kb_status === 'promoted')
        .map(d => ({
            id: d.id,
            name: `${d.integration_id} · ${d.doc_type}`,
            tags: [],
            date: d.generated_at,
            source: 'integration',
            previewText: typeof d.content === 'string' ? d.content.slice(0, 500) : '',
            chunkCount: null,
            docType: d.doc_type,
        }));
    return [...uploaded, ...integration];
}

/**
 * Filter unified docs by name or tag (case-insensitive).
 * Empty query returns full list unchanged.
 */
export function filterDocs(docs = [], query = '') {
    if (!query.trim()) return docs;
    const q = query.toLowerCase();
    return docs.filter(d =>
        d.name.toLowerCase().includes(q) ||
        d.tags.some(t => t.toLowerCase().includes(q))
    );
}
```

**Step 2: Verify build**

```bash
cd services/web-dashboard && npm run build
```

Expected: Build passes (kbHelpers not yet imported by anything, but valid module).

**Step 3: Commit**

```bash
git add services/web-dashboard/src/components/kb/kbHelpers.js
git commit -m "feat(fe/kb): extract KB helper utilities to kbHelpers.js (R4)"
```

---

## Task 3: R4 — Extract TagEditModal

**Files:**
- Create: `services/web-dashboard/src/components/kb/TagEditModal.jsx`
- Modify: `services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx`

**Step 1: Create TagEditModal.jsx**

Copy lines 94–202 from `KnowledgeBasePage.jsx` into the new file. Adjust import paths (one level deeper in `kb/` subfolder):

```jsx
// src/components/kb/TagEditModal.jsx
import { useState } from 'react';
import { X, Tag, Loader2, CheckCircle } from 'lucide-react';
import { toast } from 'sonner';
import Badge from '../ui/Badge.jsx';
import { API } from '../../api.js';

const MAX_TAGS = 10;

export default function TagEditModal({ doc, onClose, onSaved }) {
    const [tags, setTags] = useState(doc.tags || []);
    const [custom, setCustom] = useState('');
    const [saving, setSaving] = useState(false);

    // ... (paste full TagEditModal body from KnowledgeBasePage.jsx lines 94-202,
    //      removing the local [error, setError] state and replacing:
    //        setError(msg) → toast.error(msg)
    //      in the catch block of handleSave)
}
```

Key change: remove `const [error, setError] = useState(null)` and all `{error && ...}` JSX. Replace `setError(e.message)` in the catch block with `toast.error(e.message)`.

**Step 2: Update KnowledgeBasePage.jsx imports**

Replace the inline `TagEditModal` function definition (lines 92–202) with an import:

```jsx
import TagEditModal from '../kb/TagEditModal.jsx';
```

Remove from the import list in KnowledgeBasePage.jsx the icons that are now only used by TagEditModal (if any are no longer used elsewhere in the file).

**Step 3: Verify build**

```bash
cd services/web-dashboard && npm run build
```

Expected: Build passes.

**Step 4: Commit**

```bash
git add services/web-dashboard/src/components/kb/TagEditModal.jsx \
        services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx
git commit -m "feat(fe/kb): extract TagEditModal to kb/TagEditModal.jsx (R4)"
```

---

## Task 4: R4 — Extract PreviewModal

**Files:**
- Create: `services/web-dashboard/src/components/kb/PreviewModal.jsx`
- Modify: `services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx`

**Step 1: Create PreviewModal.jsx**

```jsx
// src/components/kb/PreviewModal.jsx
import { X } from 'lucide-react';

export default function PreviewModal({ doc, onClose }) {
    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in"
            onClick={onClose}
        >
            <div
                className="bg-white rounded-2xl shadow-xl w-full max-w-2xl mx-4 max-h-[80vh] overflow-hidden flex flex-col"
                onClick={e => e.stopPropagation()}
            >
                <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between flex-shrink-0">
                    <div>
                        <h3 className="font-semibold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                            Content Preview
                        </h3>
                        <p className="text-xs text-slate-400 mt-0.5">
                            {doc.filename}{doc.chunk_count != null ? ` · ${doc.chunk_count} chunks` : ''}
                        </p>
                    </div>
                    <button onClick={onClose} className="p-1 hover:bg-slate-100 rounded-lg transition-colors">
                        <X size={18} className="text-slate-400" />
                    </button>
                </div>
                <div className="px-6 py-5 overflow-y-auto flex-1">
                    <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans leading-relaxed">
                        {doc.content_preview || 'No preview available.'}
                    </pre>
                </div>
            </div>
        </div>
    );
}
```

**Step 2: Update KnowledgeBasePage.jsx**

Replace the inline `PreviewModal` definition (lines 205–234) with:

```jsx
import PreviewModal from '../kb/PreviewModal.jsx';
```

**Step 3: Verify build + commit**

```bash
cd services/web-dashboard && npm run build
git add services/web-dashboard/src/components/kb/PreviewModal.jsx \
        services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx
git commit -m "feat(fe/kb): extract PreviewModal to kb/PreviewModal.jsx (R4)"
```

---

## Task 5: R4 — Extract SearchPanel

**Files:**
- Create: `services/web-dashboard/src/components/kb/SearchPanel.jsx`
- Modify: `services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx`

**Step 1: Create SearchPanel.jsx**

Copy lines 237–318 from `KnowledgeBasePage.jsx`. Replace local `[error, setError]` with `toast.error()`:

```jsx
// src/components/kb/SearchPanel.jsx
import { useState } from 'react';
import { Search, Loader2, AlertCircle } from 'lucide-react';
import { toast } from 'sonner';
import Badge from '../ui/Badge.jsx';
import { API } from '../../api.js';

export default function SearchPanel() {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState(null);
    const [searching, setSearching] = useState(false);

    const doSearch = async () => {
        if (!query.trim()) return;
        setSearching(true);
        try {
            const res = await API.kb.search(query.trim());
            if (!res.ok) throw new Error('Search failed');
            const data = await res.json();
            setResults(data);
        } catch (e) {
            toast.error(e.message);
        } finally {
            setSearching(false);
        }
    };

    return (
        // ... (paste JSX from KnowledgeBasePage.jsx lines 261-318,
        //      removing the {error && ...} block since errors go to toast)
    );
}
```

**Step 2: Update KnowledgeBasePage.jsx — replace inline SearchPanel with import**

```jsx
import SearchPanel from '../kb/SearchPanel.jsx';
```

**Step 3: Verify build + commit**

```bash
cd services/web-dashboard && npm run build
git add services/web-dashboard/src/components/kb/SearchPanel.jsx \
        services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx
git commit -m "feat(fe/kb): extract SearchPanel to kb/SearchPanel.jsx (R4)"
```

---

## Task 6: R4 + R7 — Extract UnifiedDocumentsPanel (fix IT strings)

**Files:**
- Create: `services/web-dashboard/src/components/kb/UnifiedDocumentsPanel.jsx`
- Modify: `services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx`

**Step 1: Create UnifiedDocumentsPanel.jsx**

Copy lines 322–494 from `KnowledgeBasePage.jsx`. Apply R7 language fixes inline:

| Old (IT) | New (EN) |
|---|---|
| `"Tutti i Documenti KB"` | `"All KB Documents"` |
| `placeholder="Cerca per nome o tag…"` | `placeholder="Search by name or tag…"` |
| `'Nessun documento corrisponde alla ricerca.'` | `'No documents match your search.'` |
| `'Nessun documento presente in KB.'` | `'No documents in the KB yet.'` |

```jsx
// src/components/kb/UnifiedDocumentsPanel.jsx
import { useState, useEffect, useRef } from 'react';
import {
    Trash2, Eye, Tag, Loader2, Cpu, Link, BookOpen,
    FileText, FileType, FileSpreadsheet, Presentation,
} from 'lucide-react';
import Badge from '../ui/Badge.jsx';
import { FILE_TYPE_ICONS_MAP, FILE_TYPE_LABELS, formatDate, formatBytes, filterDocs } from './kbHelpers.js';

// Reconstruct the icon map using lucide imports (kbHelpers stores string keys)
const FILE_TYPE_ICONS = {
    pdf: FileText,
    docx: FileType,
    xlsx: FileSpreadsheet,
    pptx: Presentation,
    md: FileText,
};

export default function UnifiedDocumentsPanel({ docs, onDelete, deletingId, onPreview, onEditTags }) {
    const [query, setQuery] = useState('');
    const [displayed, setDisplayed] = useState(docs);
    const timerRef = useRef(null);

    useEffect(() => {
        clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => setDisplayed(filterDocs(docs, query)), 200);
        return () => clearTimeout(timerRef.current);
    }, [query, docs]);

    return (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
                <BookOpen size={15} className="text-slate-400" />
                <h2 className="font-semibold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                    All KB Documents        {/* R7: was "Tutti i Documenti KB" */}
                </h2>
                <Badge variant="slate">{docs.length}</Badge>
            </div>
            <div className="px-5 py-3 border-b border-slate-100">
                <input
                    type="text"
                    placeholder="Search by name or tag…"   // R7: was "Cerca per nome o tag…"
                    value={query}
                    onChange={e => setQuery(e.target.value)}
                    className="w-full text-sm px-3 py-2 border border-slate-200 rounded-lg outline-none focus:border-indigo-300 focus:ring-1 focus:ring-indigo-100"
                />
            </div>
            {/* table body — paste from KnowledgeBasePage.jsx lines 375-494,
                replacing IT empty-state strings with EN equivalents */}
        </div>
    );
}
```

**Step 2: Update KnowledgeBasePage.jsx**

Replace inline `UnifiedDocumentsPanel` (lines 320–494) with import. Also update internal references to `FILE_TYPE_ICONS` and helpers to come from `kbHelpers.js` or be removed (since they now live in the component files):

```jsx
import UnifiedDocumentsPanel from '../kb/UnifiedDocumentsPanel.jsx';
```

Remove from top of `KnowledgeBasePage.jsx` the now-unused constants: `FILE_TYPE_ICONS`, `FILE_TYPE_LABELS`, `ACCEPTED_EXTENSIONS`, `formatBytes`, `formatDate`, `normalizeKBDocs`, `filterDocs`. Import only what KnowledgeBasePage itself uses:

```jsx
import { ACCEPTED_EXTENSIONS, normalizeKBDocs } from '../kb/kbHelpers.js';
```

**Step 3: Verify build + commit**

```bash
cd services/web-dashboard && npm run build
git add services/web-dashboard/src/components/kb/UnifiedDocumentsPanel.jsx \
        services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx
git commit -m "feat(fe/kb): extract UnifiedDocumentsPanel + fix IT strings (R4/R7)"
```

---

## Task 7: R4 — Extract AddUrlForm

**Files:**
- Create: `services/web-dashboard/src/components/kb/AddUrlForm.jsx`
- Modify: `services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx`

**Step 1: Create AddUrlForm.jsx**

Copy lines 499–584. Remove `onError` prop — call `toast.error()` directly:

```jsx
// src/components/kb/AddUrlForm.jsx
import { useState } from 'react';
import { Link, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { API } from '../../api.js';

export default function AddUrlForm({ onAdded }) {   // removed onError prop
    const [url, setUrl] = useState('');
    const [title, setTitle] = useState('');
    const [tagsInput, setTagsInput] = useState('');
    const [adding, setAdding] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        const cleanUrl = url.trim();
        const tags = tagsInput.split(',').map(t => t.trim()).filter(Boolean);
        if (!cleanUrl) return;
        if (tags.length === 0) {
            toast.error('At least one tag is required.');
            return;
        }
        setAdding(true);
        try {
            const res = await API.kb.addUrl({ url: cleanUrl, title: title.trim() || null, tags });
            if (!res.ok) {
                const d = await res.json().catch(() => ({}));
                throw new Error(d.detail || `Failed (${res.status})`);
            }
            setUrl(''); setTitle(''); setTagsInput('');
            toast.success('URL added to Knowledge Base.');
            onAdded();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setAdding(false);
        }
    };

    return (
        // ... paste JSX from KnowledgeBasePage.jsx lines 531–583
    );
}
```

**Step 2: Update KnowledgeBasePage.jsx**

Replace inline `AddUrlForm` with import. Update usage — remove `onError` prop from the `<AddUrlForm>` call site (now calls toast internally):

```jsx
import AddUrlForm from '../kb/AddUrlForm.jsx';

// Usage in render (line 773):
<AddUrlForm onAdded={() => loadData()} />   // removed onError prop
```

**Step 3: Simplify KnowledgeBasePage.jsx error state**

Since all sub-components now use toasts, the top-level `[error, setError]` state in KnowledgeBasePage can be simplified: keep it only for the file-upload and delete error paths, or replace those with toasts too:

```jsx
// In handleFile catch:
toast.error(e.message);

// In handleDelete catch:
toast.error(e.message);
```

Then remove `const [error, setError] = useState(null)` and the `{error && ...}` JSX block from the render (lines 781–788).

**Step 4: Verify build + commit**

```bash
cd services/web-dashboard && npm run build
git add services/web-dashboard/src/components/kb/AddUrlForm.jsx \
        services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx
git commit -m "feat(fe/kb): extract AddUrlForm, replace prop-drilling error with toast (R4/R6)"
```

---

## Task 8: R4 — Extract TagConfirmPanel from RequirementsPage

**Files:**
- Create: `services/web-dashboard/src/components/requirements/TagConfirmPanel.jsx`
- Modify: `services/web-dashboard/src/components/pages/RequirementsPage.jsx`

**Step 1: Create TagConfirmPanel.jsx**

Copy lines 7–174 from `RequirementsPage.jsx` (includes `TagChip` helper and `TagConfirmPanel`). Replace `setError` with `toast.error()`:

```jsx
// src/components/requirements/TagConfirmPanel.jsx
import { useState, useEffect } from 'react';
import { CheckCircle, X, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { API } from '../../api.js';

const MAX_TAGS = 3;

function TagChip({ tag, selected, onToggle }) {
    // ... paste from RequirementsPage.jsx lines 17-30
}

export default function TagConfirmPanel({ integrationId, onConfirmed }) {
    const [suggested, setSuggested] = useState([]);
    const [selected, setSelected]   = useState([]);
    const [custom, setCustom]       = useState('');
    const [loading, setLoading]     = useState(true);
    const [confirming, setConfirming] = useState(false);

    useEffect(() => {
        (async () => {
            try {
                const res  = await API.catalog.suggestTags(integrationId);
                const data = await res.json();
                const tags = data.suggested_tags || [];
                setSuggested(tags);
                setSelected(tags.slice(0, MAX_TAGS));
            } catch {
                toast.error('Failed to load suggested tags');
            } finally {
                setLoading(false);
            }
        })();
    }, [integrationId]);

    // ... paste rest of TagConfirmPanel body (toggleTag, addCustom, confirm, return JSX)
    // replacing setError(...) calls with toast.error(...)
}
```

**Step 2: Update RequirementsPage.jsx**

Replace inline `TagChip` + `TagConfirmPanel` definitions (lines 7–174) with import:

```jsx
import TagConfirmPanel from '../requirements/TagConfirmPanel.jsx';
```

Remove unused imports that only the extracted components needed (`Tags`, `Plus` from lucide, etc.).

**Step 3: Verify build + commit**

```bash
cd services/web-dashboard && npm run build
git add services/web-dashboard/src/components/requirements/TagConfirmPanel.jsx \
        services/web-dashboard/src/components/pages/RequirementsPage.jsx
git commit -m "feat(fe/req): extract TagConfirmPanel to requirements/TagConfirmPanel.jsx (R4)"
```

---

## Task 9: R7 — Fix remaining Italian strings

**Files:**
- Modify: `services/web-dashboard/src/components/ui/ProjectModal.jsx`

**Step 1: Find and fix the remaining Italian string**

In `ProjectModal.jsx` line 309, fix:

```jsx
// Before:
<><CheckCircle size={14} /> Conferma e Crea Integrazioni</>

// After:
<><CheckCircle size={14} /> Confirm & Create Integrations</>
```

**Step 2: Verify build + commit**

```bash
cd services/web-dashboard && npm run build
git add services/web-dashboard/src/components/ui/ProjectModal.jsx
git commit -m "fix(fe): standardize UI language to English (R7)"
```

---

## Task 10: R18-a — Backend: real progress tracking in state and agent flow

**Files:**
- Modify: `services/integration-agent/state.py`
- Modify: `services/integration-agent/routers/agent.py`
- Test: `services/integration-agent/tests/test_agent_progress.py` (new)

**Step 1: Write the failing test**

```python
# tests/test_agent_progress.py
"""Tests for R18: real progress tracking in agent logs endpoint."""
import pytest
from fastapi.testclient import TestClient


def test_logs_endpoint_includes_empty_progress_when_idle():
    """Progress is an empty dict when agent is idle."""
    import state
    state.agent_progress = {}

    from main import app
    client = TestClient(app)
    res = client.get("/api/v1/agent/logs")
    assert res.status_code == 200
    data = res.json()
    assert "progress" in data
    assert data["progress"] == {}


def test_logs_endpoint_includes_progress_when_running():
    """Progress reflects current/total/phase when agent is active."""
    import state
    state.agent_progress = {"current": 2, "total": 5, "phase": "llm_generation"}

    from main import app
    client = TestClient(app)
    res = client.get("/api/v1/agent/logs")
    assert res.status_code == 200
    data = res.json()
    assert data["progress"]["current"] == 2
    assert data["progress"]["total"] == 5
    assert data["progress"]["phase"] == "llm_generation"
```

**Step 2: Run test to confirm it fails**

```bash
cd services/integration-agent && python -m pytest tests/test_agent_progress.py -v
```

Expected: FAIL — `"progress" not in data`

**Step 3: Add `agent_progress` to state.py**

In `state.py`, after `agent_logs`:

```python
# ── Agent progress (R18) — updated by run_agentic_rag_flow ─────────────────
# Shape: {"current": int, "total": int, "phase": str} while running, {} when idle.
agent_progress: dict = {}
```

**Step 4: Update `run_agentic_rag_flow` in `routers/agent.py`**

After `total = len(confirmed)`, add:

```python
state.agent_progress = {"current": 0, "total": total, "phase": "starting"}
```

At the start of the `for idx, entry in enumerate(confirmed, start=1):` loop body (before the `log_agent` call):

```python
state.agent_progress = {"current": idx - 1, "total": total, "phase": "llm_generation"}
```

After the loop completes (before the final `log_agent` call at the end of the function), add:

```python
state.agent_progress = {}   # clear on completion
```

**Step 5: Update `get_logs` endpoint in `routers/agent.py`**

```python
@router.get("/agent/logs")
async def get_logs(offset: int = 0) -> dict:
    """Return agent logs from *offset* onwards (max 100 per call)."""
    capped = state.agent_logs[offset:][:100]
    return {
        "status": "success",
        "logs": [e.model_dump(mode="json") for e in capped],
        "next_offset": offset + len(capped),
        "finished": not state.agent_lock.locked(),
        "progress": state.agent_progress,   # R18: real progress data
    }
```

**Step 6: Run tests**

```bash
cd services/integration-agent && python -m pytest tests/test_agent_progress.py -v
```

Expected: 2 tests PASS.

**Step 7: Run full suite to check for regressions**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: All pass.

**Step 8: Commit**

```bash
git add services/integration-agent/state.py \
        services/integration-agent/routers/agent.py \
        services/integration-agent/tests/test_agent_progress.py
git commit -m "feat(agent): add real progress tracking to /agent/logs endpoint (R18)"
```

---

## Task 11: R18-b — Frontend: replace fake timer progress bar with real data

**Files:**
- Modify: `services/web-dashboard/src/hooks/useAgentLogs.js`
- Modify: `services/web-dashboard/src/components/pages/AgentWorkspacePage.jsx`

**Step 1: Update useAgentLogs.js to expose progress**

In `fetchLogs()`, extract `progress` from the response:

```js
async function fetchLogs() {
  const res = await API.agent.logs(0);
  if (!res.ok) throw new Error(`Failed to fetch logs (${res.status})`);
  const data = await res.json();
  return {
    logs: data.logs || [],
    running: !data.finished,
    progress: data.progress || {},   // R18: real progress data
  };
}
```

In the `useAgentLogs` return object:

```js
return {
  logs: query.data?.logs ?? [],
  isRunning: query.data?.running ?? false,
  progress: query.data?.progress ?? {},  // R18: { current, total, phase } or {}
  isLoading: query.isLoading,
  // ... rest unchanged
};
```

**Step 2: Update AgentWorkspacePage.jsx ProgressBar and usage**

Update `ProgressBar` component to accept `progressData` and use it when available:

```jsx
function ProgressBar({ elapsed, progressData }) {
  // R18: use real progress if backend provides it; fall back to timer-based
  const hasReal  = progressData?.total > 0;
  const pct      = hasReal
    ? Math.round((progressData.current / progressData.total) * 100)
    : 0;
  const phase    = progressData?.phase ?? 'Processing';
  const label    = hasReal
    ? `${progressData.current} / ${progressData.total} integrations`
    : `${elapsed}s elapsed`;
  const barColor = pct >= 90 ? 'bg-emerald-500' : 'bg-indigo-500';

  return (
    <div className="mt-4 space-y-1.5">
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span className="font-medium text-indigo-600 capitalize">{phase.replace('_', ' ')}…</span>
        <span className="font-mono tabular-nums">{label}</span>
      </div>
      <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ease-out ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-right text-xs font-semibold text-indigo-600 tabular-nums">
        {pct}%
      </div>
    </div>
  );
}
```

Update `AgentWorkspacePage` to use the new API:

```jsx
const { logs, isRunning, progress, trigger, cancel, triggerError } = useAgentLogs();
```

Remove the fake timer logic (`progressRef`, `startProgress`, `stopProgress`, `setProgress`, `setElapsed`). The `elapsed` state and its `setInterval` can be removed since the real progress bar no longer needs them.

Update the render call:

```jsx
{isRunning && <ProgressBar elapsed={elapsed} progressData={progress} />}
```

(Keep `elapsed` only if you want to keep the elapsed time display; otherwise remove it entirely.)

**Step 3: Verify build + commit**

```bash
cd services/web-dashboard && npm run build
git add services/web-dashboard/src/hooks/useAgentLogs.js \
        services/web-dashboard/src/components/pages/AgentWorkspacePage.jsx
git commit -m "feat(fe): replace fake timer progress bar with real backend progress (R18)"
```

---

## Task 12: R19-MVP — Audit event log (append-only MongoDB events collection)

**Files:**
- Modify: `services/integration-agent/db.py`
- Create: `services/integration-agent/event_logger.py`
- Modify: `services/integration-agent/routers/catalog.py` (status change to TAG_CONFIRMED)
- Modify: `services/integration-agent/routers/approvals.py` (approve / reject decisions)
- Modify: `services/integration-agent/routers/documents.py` (promote to KB)
- Test: `services/integration-agent/tests/test_event_logger.py` (new)

**Step 1: Write the failing test**

```python
# tests/test_event_logger.py
"""Tests for R19-MVP: audit event log appending to MongoDB events collection."""
import asyncio
import pytest


@pytest.mark.asyncio
async def test_record_event_inserts_document(monkeypatch):
    """record_event() inserts a timestamped document into events_col."""
    inserted = []

    class MockCol:
        async def insert_one(self, doc):
            inserted.append(doc)

    import db
    monkeypatch.setattr(db, "events_col", MockCol())

    from event_logger import record_event
    await record_event("catalog.tag_confirmed", {"integration_id": "INT-001"})

    assert len(inserted) == 1
    doc = inserted[0]
    assert doc["event_type"] == "catalog.tag_confirmed"
    assert doc["payload"]["integration_id"] == "INT-001"
    assert "timestamp" in doc


@pytest.mark.asyncio
async def test_record_event_is_silent_when_col_is_none(monkeypatch):
    """record_event() does nothing (no raise) when events_col is None."""
    import db
    monkeypatch.setattr(db, "events_col", None)

    from event_logger import record_event
    # Must not raise
    await record_event("test.event", {"key": "value"})


@pytest.mark.asyncio
async def test_record_event_is_silent_on_db_error(monkeypatch):
    """record_event() swallows DB errors — never propagates to caller."""
    class BrokenCol:
        async def insert_one(self, doc):
            raise Exception("DB connection lost")

    import db
    monkeypatch.setattr(db, "events_col", BrokenCol())

    from event_logger import record_event
    # Must not raise
    await record_event("test.event", {})
```

**Step 2: Run test to confirm it fails**

```bash
cd services/integration-agent && python -m pytest tests/test_event_logger.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'event_logger'`

**Step 3: Add `events_col` to db.py**

Read `db.py` first, then add the events collection alongside the existing collections. In the lifespan function where collections are initialized:

```python
# In db.py — add the collection variable at module level:
events_col = None

# In the lifespan/init function where db collections are set up:
events_col = db["events"]
# No index required — pure append-only, queried by timestamp range only.
```

**Step 4: Create event_logger.py**

```python
# services/integration-agent/event_logger.py
"""
Audit Event Logger (R19-MVP).

Appends immutable event records to the MongoDB 'events' collection.
Provides a lightweight audit trail of state mutations without replacing
the existing write-through pattern (full event-sourcing deferred).

Event schema: { event_type: str, payload: dict, timestamp: ISO-8601 str }
"""

import logging

import db
from utils import _now_iso

logger = logging.getLogger(__name__)


async def record_event(event_type: str, payload: dict) -> None:
    """Append an audit event to MongoDB.  Errors are logged, never raised.

    Args:
        event_type: dot-namespaced string, e.g. "catalog.tag_confirmed"
        payload:    context dict (integration_id, approval_id, etc.)
    """
    if db.events_col is None:
        return
    try:
        await db.events_col.insert_one({
            "event_type": event_type,
            "payload": payload,
            "timestamp": _now_iso(),
        })
    except Exception as exc:
        logger.warning("[EVENT] Failed to record event '%s': %s", event_type, exc)
```

**Step 5: Run tests**

```bash
cd services/integration-agent && python -m pytest tests/test_event_logger.py -v
```

Expected: 3 tests PASS.

**Step 6: Integrate record_event in catalog.py**

Read `routers/catalog.py` to find where `status` is set to `"TAG_CONFIRMED"`. After the MongoDB write, add:

```python
from event_logger import record_event

# After entry.status = "TAG_CONFIRMED" and db write:
await record_event("catalog.tag_confirmed", {
    "integration_id": entry.id,
    "tags": entry.tags,
})
```

**Step 7: Integrate record_event in approvals.py**

Read `routers/approvals.py`. After approve and reject writes:

```python
from event_logger import record_event

# After approve write:
await record_event("approval.approved", {
    "approval_id": approval.id,
    "integration_id": approval.integration_id,
})

# After reject write:
await record_event("approval.rejected", {
    "approval_id": approval.id,
    "integration_id": approval.integration_id,
    "feedback": feedback,
})
```

**Step 8: Integrate record_event in documents.py**

After a document is promoted to KB:

```python
from event_logger import record_event

await record_event("document.promoted_to_kb", {
    "document_id": doc.id,
    "integration_id": doc.integration_id,
})
```

**Step 9: Run full test suite**

```bash
cd services/integration-agent && python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: All tests pass.

**Step 10: Commit**

```bash
git add services/integration-agent/db.py \
        services/integration-agent/event_logger.py \
        services/integration-agent/routers/catalog.py \
        services/integration-agent/routers/approvals.py \
        services/integration-agent/routers/documents.py \
        services/integration-agent/tests/test_event_logger.py
git commit -m "feat(agent): R19-MVP audit event log — append-only MongoDB events collection"
```

---

## Task 13: Final verification and documentation update

**Step 1: Run full backend test suite**

```bash
cd services/integration-agent && python -m pytest tests/ -v
```

Expected: All tests pass (271 existing + ~5 new = ~276 total).

**Step 2: Run frontend build**

```bash
cd services/web-dashboard && npm run build
```

Expected: Build completes with no errors or warnings.

**Step 3: Update architecture_specification.md and functional-guide.md**

Mark Phase 4 items as implemented:
- R4: Component decomposition ✅
- R6: Toast system (sonner) ✅
- R7: Language consistency (EN) ✅
- R18: Real progress tracking ✅
- R19-MVP: Audit event log ✅

**Step 4: Update MEMORY.md**

Record new test count, new files created, patterns learned.

**Step 5: Final commit**

```bash
git add docs/architecture_specification.md docs/functional-guide.md
git commit -m "docs: mark Phase 4 R4/R6/R7/R18/R19-MVP as implemented"
git push origin main
```

---

## Summary Table

| Task | Item | Type | Files Touched |
|------|------|------|---------------|
| 1 | R6 Toast | FE | `App.jsx`, `package.json` |
| 2 | R4 kbHelpers | FE | `src/components/kb/kbHelpers.js` (new) |
| 3 | R4 TagEditModal | FE | `kb/TagEditModal.jsx` (new), `KnowledgeBasePage.jsx` |
| 4 | R4 PreviewModal | FE | `kb/PreviewModal.jsx` (new), `KnowledgeBasePage.jsx` |
| 5 | R4 SearchPanel | FE | `kb/SearchPanel.jsx` (new), `KnowledgeBasePage.jsx` |
| 6 | R4+R7 UnifiedDocumentsPanel | FE | `kb/UnifiedDocumentsPanel.jsx` (new), `KnowledgeBasePage.jsx` |
| 7 | R4 AddUrlForm | FE | `kb/AddUrlForm.jsx` (new), `KnowledgeBasePage.jsx` |
| 8 | R4 TagConfirmPanel | FE | `requirements/TagConfirmPanel.jsx` (new), `RequirementsPage.jsx` |
| 9 | R7 ProjectModal | FE | `ProjectModal.jsx` |
| 10 | R18 Backend | BE | `state.py`, `routers/agent.py`, `tests/test_agent_progress.py` |
| 11 | R18 Frontend | FE | `useAgentLogs.js`, `AgentWorkspacePage.jsx` |
| 12 | R19-MVP Event Log | BE | `db.py`, `event_logger.py` (new), 3 routers, `tests/test_event_logger.py` |
| 13 | Docs | DOCS | `architecture_specification.md`, `functional-guide.md` |
