# KB Unified Document List — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the existing KB documents table with a unified list that shows both uploaded KB files and promoted integration specs, with a client-side text search box (name/tag) and the semantic search panel left unchanged.

**Architecture:** Two parallel API calls at mount (`API.kb.list()` + `API.documents.list()`); integration docs filtered to `kb_status === "promoted"`; merged into a `UnifiedDoc` array via a pure `normalizeKBDocs()` function; filtered in-memory via `filterDocs()` with 200ms debounce; new `UnifiedDocumentsPanel` component replaces the old table.

**Tech Stack:** React 18 (hooks), Lucide-react icons, Tailwind CSS, existing `API` client in `src/api.js`

---

## Context: Key Files

| File | Role |
|------|------|
| `services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx` | Only file that changes |
| `services/web-dashboard/src/api.js` | Already has `API.documents.list()` — no change |

Relevant existing API calls in `api.js`:
```js
API.kb.list()          // GET /api/v1/kb/documents → { data: KBDocument[] }
API.documents.list()   // GET /api/v1/documents   → { data: Document[] }
```

Relevant Document fields (from `schemas.py`):
```python
class Document:
    id: str                          # "{integration_id}-{doc_type}"
    integration_id: str
    doc_type: str                    # "functional" | "technical"
    content: str
    generated_at: str
    kb_status: Literal["staged", "promoted"]
```

---

## Task 1: Add pure helper functions + `Cpu` icon import

**Files:**
- Modify: `services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx:1-6` (imports)
- Modify: `services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx:44` (after `formatDate`)

### Step 1: Add `Cpu` to the lucide-react import

Replace the existing import block (lines 1-6) with:

```jsx
import { useState, useEffect, useRef } from 'react';
import {
    Upload, Trash2, Search, Tag, FileText, X, Loader2,
    AlertCircle, CheckCircle, Eye, BookOpen, BarChart3,
    FileSpreadsheet, FileType, Presentation, Cpu,
} from 'lucide-react';
import Badge from '../ui/Badge.jsx';
import { API } from '../../api.js';
```

### Step 2: Add pure helper functions after `formatDate` (after line 42)

Insert this block between `formatDate` and the `// ── Tag Edit Modal` comment:

```jsx
// ── Unified KB helpers ───────────────────────────────────────────────────────

/**
 * Merge KB-uploaded docs and promoted integration docs into a single array.
 * Only integration docs with kb_status === "promoted" are included.
 */
function normalizeKBDocs(kbList, intList) {
    const uploaded = kbList.map(d => ({
        id: d.id,
        name: d.filename,
        tags: d.tags || [],
        date: d.uploaded_at,
        source: 'uploaded',
        previewText: d.content_preview || '',
        chunkCount: d.chunk_count,
        _kbDoc: d,             // kept for delete / tag-edit actions
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
function filterDocs(docs, query) {
    if (!query.trim()) return docs;
    const q = query.toLowerCase();
    return docs.filter(d =>
        d.name.toLowerCase().includes(q) ||
        d.tags.some(t => t.toLowerCase().includes(q))
    );
}
```

### Step 3: Commit

```bash
git add services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx
git commit -m "feat: add normalizeKBDocs and filterDocs helpers for unified KB list"
```

---

## Task 2: Update `PreviewModal` to handle integration docs (no chunk count)

**Files:**
- Modify: `services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx:171` (subtitle line)

### Step 1: Find the subtitle line in PreviewModal (around line 171)

Current code:
```jsx
<p className="text-xs text-slate-400 mt-0.5">{doc.filename} · {doc.chunk_count} chunks</p>
```

Replace with:
```jsx
<p className="text-xs text-slate-400 mt-0.5">
    {doc.filename}{doc.chunk_count != null ? ` · ${doc.chunk_count} chunks` : ''}
</p>
```

### Step 2: Commit

```bash
git add services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx
git commit -m "fix: PreviewModal handles null chunk_count for integration docs"
```

---

## Task 3: Add `UnifiedDocumentsPanel` component

**Files:**
- Modify: `services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx` — insert before `// ── Main Page` comment

### Step 1: Insert `UnifiedDocumentsPanel` before the `// ── Main Page` comment

```jsx
// ── Unified Documents Panel ──────────────────────────────────────────────────

/**
 * Shows all KB documents (uploaded + promoted integration specs) in one table.
 * Includes a client-side text search box that filters by name or tag.
 * Delete action is available only for uploaded docs.
 */
function UnifiedDocumentsPanel({ docs, onDelete, deletingId, onPreview, onEditTags }) {
    const [query, setQuery] = useState('');
    const [displayed, setDisplayed] = useState(docs);
    const timerRef = useRef(null);

    useEffect(() => {
        clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => {
            setDisplayed(filterDocs(docs, query));
        }, 200);
        return () => clearTimeout(timerRef.current);
    }, [query, docs]);

    return (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
            {/* Header */}
            <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
                <BookOpen size={15} className="text-slate-400" />
                <h2 className="font-semibold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                    Tutti i Documenti KB
                </h2>
                <Badge variant="slate">{docs.length}</Badge>
            </div>

            {/* Search box */}
            <div className="px-5 py-3 border-b border-slate-100">
                <div className="relative">
                    <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
                    <input
                        type="text"
                        placeholder="Cerca per nome o tag…"
                        value={query}
                        onChange={e => setQuery(e.target.value)}
                        className="w-full pl-9 pr-4 py-2 text-sm border border-slate-200 rounded-lg outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100"
                    />
                </div>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
                <table className="w-full text-sm">
                    <thead className="bg-slate-50">
                        <tr>
                            {['Nome', 'Tipo', 'Tag', 'Data', 'Azioni'].map(h => (
                                <th key={h}
                                    className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                                    {h}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                        {displayed.length === 0 && (
                            <tr>
                                <td colSpan={5} className="px-4 py-8 text-center text-sm text-slate-400">
                                    {query.trim()
                                        ? 'Nessun documento corrisponde alla ricerca.'
                                        : 'Nessun documento presente in KB.'}
                                </td>
                            </tr>
                        )}
                        {displayed.map(doc => (
                            <tr key={doc.id} className="hover:bg-slate-50/70 transition-colors">
                                {/* Nome */}
                                <td className="px-4 py-3">
                                    <div className="flex items-center gap-2">
                                        {doc.source === 'uploaded'
                                            ? <FileText size={15} className="text-slate-400 flex-shrink-0" />
                                            : <Cpu size={15} className="text-blue-400 flex-shrink-0" />
                                        }
                                        <p className="font-medium text-slate-900 max-w-[220px] truncate" title={doc.name}>
                                            {doc.name}
                                        </p>
                                    </div>
                                </td>

                                {/* Tipo */}
                                <td className="px-4 py-3">
                                    {doc.source === 'uploaded'
                                        ? <Badge variant="slate">📤 Caricato</Badge>
                                        : <Badge variant="info">⚙️ Integrazione</Badge>
                                    }
                                </td>

                                {/* Tag */}
                                <td className="px-4 py-3">
                                    <div className="flex flex-wrap gap-1 max-w-[180px]">
                                        {doc.tags.length > 0
                                            ? doc.tags.map(tag => (
                                                <span key={tag}
                                                    className="inline-block px-2 py-0.5 bg-indigo-50 text-indigo-600 rounded-full text-xs">
                                                    {tag}
                                                </span>
                                            ))
                                            : <span className="text-xs text-slate-400">—</span>
                                        }
                                    </div>
                                </td>

                                {/* Data */}
                                <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">
                                    {formatDate(doc.date)}
                                </td>

                                {/* Azioni */}
                                <td className="px-4 py-3">
                                    <div className="flex items-center gap-1">
                                        {/* Preview — always visible */}
                                        <button
                                            onClick={() => onPreview(doc)}
                                            className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
                                            title="Anteprima contenuto"
                                        >
                                            <Eye size={14} />
                                        </button>

                                        {/* Edit tags — uploaded only */}
                                        {doc.source === 'uploaded' && (
                                            <button
                                                onClick={() => onEditTags(doc._kbDoc)}
                                                className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-indigo-600 transition-colors"
                                                title="Modifica tag"
                                            >
                                                <Tag size={14} />
                                            </button>
                                        )}

                                        {/* Delete — uploaded only */}
                                        {doc.source === 'uploaded' && (
                                            <button
                                                onClick={() => onDelete(doc.id)}
                                                disabled={deletingId === doc.id}
                                                className="p-1.5 rounded-lg hover:bg-rose-50 text-slate-400 hover:text-rose-600 disabled:opacity-50 transition-colors"
                                                title="Elimina"
                                            >
                                                {deletingId === doc.id
                                                    ? <Loader2 size={14} className="animate-spin" />
                                                    : <Trash2 size={14} />
                                                }
                                            </button>
                                        )}
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
```

### Step 2: Commit

```bash
git add services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx
git commit -m "feat: add UnifiedDocumentsPanel component with search box and source badge"
```

---

## Task 4: Update main `KnowledgeBasePage` state + `loadData` + render

**Files:**
- Modify: `services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx:274-524` (main component)

### Step 1: Update state declarations

Replace the existing state block (lines 275–283) with:

```jsx
const [docs, setDocs] = useState([]);          // raw KB uploaded docs (for tag-edit, delete)
const [unifiedDocs, setUnifiedDocs] = useState([]); // merged KB + promoted integration
const [stats, setStats] = useState(null);
const [uploading, setUploading] = useState(false);
const [dragOver, setDragOver] = useState(false);
const [error, setError] = useState(null);
const [editingDoc, setEditingDoc] = useState(null);
const [previewDoc, setPreviewDoc] = useState(null);
const [deletingId, setDeletingId] = useState(null);
const fileInputRef = useRef(null);
```

### Step 2: Update `loadData` to fetch integration docs in parallel

Replace the existing `loadData` function (lines 287-300) with:

```jsx
const loadData = async () => {
    try {
        const [docsRes, statsRes, intDocsRes] = await Promise.all([
            API.kb.list(),
            API.kb.stats(),
            API.documents.list(),
        ]);
        const docsData = await docsRes.json();
        const kbDocs = docsData.data || [];
        setDocs(kbDocs);

        const statsData = await statsRes.json();
        setStats(statsData);

        // Integration docs: graceful fallback if endpoint fails or returns error
        let intDocs = [];
        if (intDocsRes.ok) {
            const intData = await intDocsRes.json();
            intDocs = intData.data || [];
        }

        setUnifiedDocs(normalizeKBDocs(kbDocs, intDocs));
    } catch (e) {
        setError(`Could not load data: ${e.message}`);
    }
};
```

### Step 3: Add `handlePreviewUnified` helper inside the component (after `handleDelete`)

```jsx
const handlePreviewUnified = (unifiedDoc) => {
    setPreviewDoc({
        filename: unifiedDoc.name,
        chunk_count: unifiedDoc.chunkCount,
        content_preview: unifiedDoc.previewText,
    });
};
```

### Step 4: Replace the old documents table section with `UnifiedDocumentsPanel`

Find and remove the old `{/* Documents table */}` block (lines 410-503):

```jsx
{/* Documents table */}
{docs.length > 0 && (
    <div className="bg-white rounded-2xl ...">
      ...
    </div>
)}
```

Replace it with:

```jsx
{/* Unified KB documents list */}
<UnifiedDocumentsPanel
    docs={unifiedDocs}
    onDelete={handleDelete}
    deletingId={deletingId}
    onPreview={handlePreviewUnified}
    onEditTags={(kbDoc) => setEditingDoc(kbDoc)}
/>
```

### Step 5: Run the frontend dev server and verify visually

```bash
cd services/web-dashboard && npm run dev
```

Open `http://localhost:5173` → navigate to Knowledge Base page.

**Expected:**
- Unified table renders (empty state shows "Nessun documento presente in KB." if no docs)
- Search box appears under the section header
- If KB docs exist: rows with "📤 Caricato" badge, delete + tag-edit + preview buttons
- If promoted integration docs exist: rows with "⚙️ Integrazione" badge, preview button only (no delete)
- Typing in search filters by name or tag with ~200ms delay

### Step 6: Commit

```bash
git add services/web-dashboard/src/components/pages/KnowledgeBasePage.jsx
git commit -m "feat: replace KB docs table with unified list (uploaded + promoted integration)"
```

---

## Task 5: Final integration test + push

### Step 1: Confirm Python tests still pass (backend unchanged)

```bash
cd services/integration-agent && python -m pytest tests/ -v
```

Expected: `171 passed`

### Step 2: Confirm no console errors in browser

Open browser DevTools → Console tab → reload Knowledge Base page.
Expected: no errors, two network calls (`/api/v1/kb/documents` + `/api/v1/documents`) both complete.

### Step 3: Push

```bash
git push origin main
```

---

## Edge Cases to Verify Manually

| Scenario | Expected Behaviour |
|----------|--------------------|
| Zero documents in KB | Empty-state row: "Nessun documento presente in KB." |
| Search matches no docs | Row: "Nessun documento corrisponde alla ricerca." |
| Integration docs API returns 401/403 | `intDocsRes.ok` is false → `intDocs = []` → only uploaded docs shown, no crash |
| Integration doc preview | Modal shows `{integration_id} · {doc_type}` as title, content preview, no "chunks" subtitle |
| Upload new file | `loadData()` re-runs → unified list re-normalizes including new KB doc |
