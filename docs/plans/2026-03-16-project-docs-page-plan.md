# Project Docs Page — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a "Project Docs" admin page that lets users browse and read significant project documentation (ADRs, guides, checklists, test plans) directly in the dashboard.

**Architecture:** Two new FastAPI endpoints serve a hardcoded manifest + file content from a Docker-mounted read-only `./docs` volume. The React frontend adds a `ProjectDocsPage` with a two-panel layout (grouped list left, ReactMarkdown viewer right) wired into the existing Sidebar/App router.

**Tech Stack:** FastAPI (pathlib path-traversal guard), React 18, ReactMarkdown + remark-gfm (already installed), Tailwind CSS, `docker-compose.yml` volume mount.

---

## Task 1: Backend — Docker volume mount for `./docs`

**Files:**
- Modify: `docker-compose.yml` (integration-agent service section)

**Step 1: Open `docker-compose.yml` and locate the `integration-agent` service**

Find the `volumes:` key under `integration-agent`. It currently mounts the service source. Add a second read-only mount for the project `docs/` folder.

**Step 2: Add volume mount and env var**

Add under `integration-agent` → `volumes:`:
```yaml
      - ./docs:/app/docs:ro
```

Add under `integration-agent` → `environment:`:
```yaml
      - DOCS_ROOT=/app/docs
```

**Step 3: Verify docker-compose syntax**

```bash
docker-compose config --quiet
```
Expected: no errors printed.

**Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "chore(docker): mount docs/ read-only into integration-agent for docs API"
```

---

## Task 2: Backend — `DOCS_MANIFEST` + two API endpoints in `main.py`

**Files:**
- Modify: `services/integration-agent/main.py`

**Step 1: Add `DOCS_ROOT` import and manifest constant**

After the existing imports (around line 30, after `from pathlib import Path` — add `Path` import if not present), add a new section at the end of the constants block (after `_SAFE_FILENAME_RE`):

```python
# ── Project Docs ──────────────────────────────────────────────────────────────
import os as _os  # noqa: E402 — placed here to keep diff minimal

DOCS_ROOT = Path(_os.getenv("DOCS_ROOT", Path(__file__).parent / "docs"))

# Significant project docs — excludes templates, obsolete, and plans/
DOCS_MANIFEST: list[dict] = [
    # ── Guides ────────────────────────────────────────────────────────────────
    {
        "path": "README.md",
        "name": "README",
        "category": "Guide",
        "description": "Overview of the project, quick-start instructions, and service map.",
    },
    {
        "path": "AWS-DEPLOYMENT-GUIDE.md",
        "name": "AWS Deployment Guide",
        "category": "Guide",
        "description": "Step-by-step instructions to deploy the full stack on AWS (ECS, RDS, managed services).",
    },
    {
        "path": "architecture_specification.md",
        "name": "Architecture Specification",
        "category": "Guide",
        "description": "Full technical architecture: service topology, data flows, and component responsibilities.",
    },
    {
        "path": "functional-guide.md",
        "name": "Functional Guide",
        "category": "Guide",
        "description": "End-to-end functional walkthrough of the integration generation workflow.",
    },
    # ── ADRs ──────────────────────────────────────────────────────────────────
    {
        "path": "adr/ADR-001-011-decisions.md",
        "name": "ADR-001…011",
        "category": "ADR",
        "description": "Batch record of foundational decisions: tech stack, RAG design, HITL flow, initial security posture.",
    },
    {
        "path": "adr/ADR-012-async-llm-client.md",
        "name": "ADR-012 Async LLM Client",
        "category": "ADR",
        "description": "Decision to replace synchronous requests with httpx.AsyncClient for non-blocking Ollama calls.",
    },
    {
        "path": "adr/ADR-013-mongodb-persistence.md",
        "name": "ADR-013 MongoDB Persistence",
        "category": "ADR",
        "description": "Decision to add MongoDB as write-through cache for catalog, approvals, and documents.",
    },
    {
        "path": "adr/ADR-014-prompt-builder.md",
        "name": "ADR-014 Prompt Builder",
        "category": "ADR",
        "description": "Decision to extract prompt assembly into a dedicated module with a reusable meta-prompt template.",
    },
    {
        "path": "adr/ADR-015-llm-output-guard.md",
        "name": "ADR-015 LLM Output Guard",
        "category": "ADR",
        "description": "Decision to add an output sanitization layer validating and bleach-cleaning LLM responses.",
    },
    {
        "path": "adr/ADR-016-secret-management.md",
        "name": "ADR-016 Secret Management",
        "category": "ADR",
        "description": "Decision to move all config to pydantic-settings with env-var overrides, eliminating hardcoded secrets.",
    },
    {
        "path": "adr/ADR-017-frontend-xss-mitigation.md",
        "name": "ADR-017 Frontend XSS Mitigation",
        "category": "ADR",
        "description": "Decision to introduce escapeHtml() in the frontend to neutralize XSS from server-sourced innerHTML.",
    },
    {
        "path": "adr/ADR-018-cors-standardization.md",
        "name": "ADR-018 CORS Standardization",
        "category": "ADR",
        "description": "Decision to replace wildcard CORS with an env-var-driven allowlist.",
    },
    {
        "path": "adr/ADR-019-rag-tag-filtering.md",
        "name": "ADR-019 RAG Tag Filtering",
        "category": "ADR",
        "description": "Decision to filter ChromaDB queries by confirmed integration tags to improve context relevance.",
    },
    {
        "path": "adr/ADR-020-tag-llm-tuning.md",
        "name": "ADR-020 Tag LLM Tuning",
        "category": "ADR",
        "description": "Decision to introduce dedicated lightweight LLM settings for tag suggestion (20-token cap, 15s timeout).",
    },
    # ── Checklists ────────────────────────────────────────────────────────────
    {
        "path": "code-review/CODE-REVIEW-CHECKLIST.md",
        "name": "Code Review Checklist",
        "category": "Checklist",
        "description": "Structured checklist covering architecture, correctness, security, and testability gates.",
    },
    {
        "path": "security-review/SECURITY-REVIEW-CHECKLIST.md",
        "name": "Security Review Checklist",
        "category": "Checklist",
        "description": "OWASP-aligned checklist applied at every PR to catch injection, auth, logging, and dependency risks.",
    },
    {
        "path": "unit-test-review/UNIT-TEST-REVIEW-CHECKLIST.md",
        "name": "Unit Test Review Checklist",
        "category": "Checklist",
        "description": "Quality gate checklist: determinism, isolation, readability, edge-case coverage.",
    },
    # ── Test Plans ────────────────────────────────────────────────────────────
    {
        "path": "test-plan/TEST-PLAN-001-remediation.md",
        "name": "TEST-PLAN-001 Remediation",
        "category": "Test Plan",
        "description": "v2.0 plan covering 50 unit tests, 10 integration tests, and 16 security tests from Phase 4.",
    },
    # ── Mappings ──────────────────────────────────────────────────────────────
    {
        "path": "mappings/UNIT-SECURITY-OWASP-MAPPING.md",
        "name": "OWASP Unit-Test Mapping",
        "category": "Mapping",
        "description": "Traceability matrix linking each unit test to its OWASP Top 10 / ASVS control.",
    },
]
```

**Step 2: Add the two endpoints**

Add after the existing `GET /api/v1/admin/reset/{target}` endpoint (look for `@app.delete("/api/v1/admin/reset`), append below it:

```python
# ── Project Docs (read-only) ──────────────────────────────────────────────────

@app.get("/api/v1/admin/docs", tags=["admin"])
async def list_project_docs() -> dict:
    """Return the curated manifest of significant project documentation."""
    return {"status": "success", "data": DOCS_MANIFEST}


@app.get("/api/v1/admin/docs/{path:path}", tags=["admin"])
async def get_project_doc(path: str) -> dict:
    """Return the markdown content of a single project doc.

    Path traversal protection: resolves the absolute path and rejects any
    request that escapes DOCS_ROOT.
    """
    # Only .md files are served
    if not path.endswith(".md"):
        raise HTTPException(status_code=400, detail="Only .md files are served.")

    resolved = (DOCS_ROOT / path).resolve()
    docs_root_resolved = DOCS_ROOT.resolve()

    # Path traversal guard
    try:
        resolved.relative_to(docs_root_resolved)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document path.")

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Document not found.")

    content = resolved.read_text(encoding="utf-8")
    name = next((d["name"] for d in DOCS_MANIFEST if d["path"] == path), path)
    return {"status": "success", "data": {"path": path, "name": name, "content": content}}
```

**Step 3: Smoke-test the manifest endpoint manually (optional)**

With the backend running:
```bash
curl http://localhost:4003/api/v1/admin/docs | python -m json.tool | head -40
```
Expected: JSON with `status: "success"` and `data` array of 18 entries.

**Step 4: Write unit tests**

Add to `services/integration-agent/tests/test_project_docs.py`:

```python
"""Unit tests for GET /api/v1/admin/docs and GET /api/v1/admin/docs/{path}."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from pathlib import Path


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def test_list_docs_returns_manifest(client):
    """GET /api/v1/admin/docs returns status success and a non-empty list."""
    res = client.get("/api/v1/admin/docs")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    entries = data["data"]
    assert len(entries) == 18
    # Every entry has required keys
    for entry in entries:
        assert {"path", "name", "category", "description"} <= entry.keys()


def test_list_docs_all_categories_present(client):
    """Manifest covers all five expected categories."""
    res = client.get("/api/v1/admin/docs")
    categories = {e["category"] for e in res.json()["data"]}
    assert categories == {"Guide", "ADR", "Checklist", "Test Plan", "Mapping"}


def test_get_doc_returns_content(client, tmp_path, monkeypatch):
    """GET /api/v1/admin/docs/{path} returns file content when file exists."""
    import main
    fake_docs = tmp_path
    fake_file = fake_docs / "README.md"
    fake_file.write_text("# Hello", encoding="utf-8")
    monkeypatch.setattr(main, "DOCS_ROOT", fake_docs)

    res = client.get("/api/v1/admin/docs/README.md")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["data"]["content"] == "# Hello"
    assert body["data"]["path"] == "README.md"


def test_get_doc_404_when_missing(client, tmp_path, monkeypatch):
    """GET /api/v1/admin/docs/{path} returns 404 when file does not exist."""
    import main
    monkeypatch.setattr(main, "DOCS_ROOT", tmp_path)
    res = client.get("/api/v1/admin/docs/README.md")
    assert res.status_code == 404


def test_get_doc_rejects_non_md(client):
    """GET /api/v1/admin/docs/{path} rejects non-.md file extensions."""
    res = client.get("/api/v1/admin/docs/adr/something.txt")
    assert res.status_code == 400
    assert "Only .md" in res.json()["detail"]


def test_get_doc_path_traversal_blocked(client, tmp_path, monkeypatch):
    """Path traversal attempt (../../etc/passwd) is rejected with 400."""
    import main
    monkeypatch.setattr(main, "DOCS_ROOT", tmp_path)
    res = client.get("/api/v1/admin/docs/../../etc/passwd.md")
    assert res.status_code == 400
    assert "Invalid document path" in res.json()["detail"]
```

**Step 5: Run tests**

```bash
cd services/integration-agent && python -m pytest tests/test_project_docs.py -v
```
Expected: 6/6 PASS.

**Step 6: Run full test suite to confirm no regressions**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: all previously passing tests still pass.

**Step 7: Commit**

```bash
git add services/integration-agent/main.py services/integration-agent/tests/test_project_docs.py
git commit -m "feat(backend): add GET /api/v1/admin/docs manifest + content endpoints with path-traversal guard"
```

---

## Task 3: Frontend — `api.js` extension

**Files:**
- Modify: `services/web-dashboard/src/api.js`

**Step 1: Add `projectDocs` group to the API object**

Add after the `admin:` block (before the closing `};`):

```js
  projectDocs: {
    list:    ()     => fetch(`${getBase()}/api/v1/admin/docs`),
    content: (path) => fetch(`${getBase()}/api/v1/admin/docs/${path}`),
  },
```

**Step 2: Commit**

```bash
git add services/web-dashboard/src/api.js
git commit -m "feat(api): add projectDocs.list and projectDocs.content calls"
```

---

## Task 4: Frontend — `ProjectDocsPage.jsx`

**Files:**
- Create: `services/web-dashboard/src/components/pages/ProjectDocsPage.jsx`

**Step 1: Create the component**

```jsx
import { useState, useEffect } from 'react';
import { BookMarked, FileText, Loader2, AlertCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { API } from '../../api.js';

// Category badge colours
const CATEGORY_STYLE = {
  'Guide':     'bg-emerald-100 text-emerald-700',
  'ADR':       'bg-blue-100   text-blue-700',
  'Checklist': 'bg-amber-100  text-amber-700',
  'Test Plan': 'bg-violet-100 text-violet-700',
  'Mapping':   'bg-slate-100  text-slate-600',
};

// Category display order
const CATEGORY_ORDER = ['Guide', 'ADR', 'Checklist', 'Test Plan', 'Mapping'];

function CategoryBadge({ category }) {
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide ${CATEGORY_STYLE[category] ?? 'bg-slate-100 text-slate-600'}`}>
      {category}
    </span>
  );
}

export default function ProjectDocsPage() {
  const [docs,        setDocs]        = useState([]);
  const [selectedDoc, setSelectedDoc] = useState(null); // full manifest entry
  const [content,     setContent]     = useState('');
  const [listLoading, setListLoading] = useState(true);
  const [docLoading,  setDocLoading]  = useState(false);
  const [error,       setError]       = useState(null);

  useEffect(() => {
    API.projectDocs.list()
      .then(r => r.json())
      .then(d => setDocs(d.data || []))
      .catch(() => setError('Failed to load document list'))
      .finally(() => setListLoading(false));
  }, []);

  const loadDoc = async (doc) => {
    setSelectedDoc(doc);
    setDocLoading(true);
    setError(null);
    setContent('');
    try {
      const res = await API.projectDocs.content(doc.path);
      const d   = await res.json();
      if (!res.ok) throw new Error(d.detail || `Error ${res.status}`);
      setContent(d.data?.content || '');
    } catch (e) {
      setError(e.message || 'Failed to load document');
    } finally {
      setDocLoading(false);
    }
  };

  // Group docs by category in display order
  const grouped = CATEGORY_ORDER.reduce((acc, cat) => {
    const items = docs.filter(d => d.category === cat);
    if (items.length > 0) acc[cat] = items;
    return acc;
  }, {});

  return (
    <div className="flex gap-5" style={{ height: 'calc(100vh - 200px)' }}>
      {/* Left panel — document list */}
      <div className="w-72 flex-shrink-0 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
        <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-2">
          <BookMarked size={14} className="text-slate-400" />
          <span
            className="font-semibold text-slate-900 text-sm"
            style={{ fontFamily: 'Outfit, sans-serif' }}
          >
            Project Docs
          </span>
          <span className="ml-auto text-xs text-slate-400 font-mono">{docs.length}</span>
        </div>

        <div className="overflow-y-auto flex-1">
          {listLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 size={20} className="animate-spin text-slate-300" />
            </div>
          ) : Object.keys(grouped).length === 0 ? (
            <div className="px-4 py-8 text-center">
              <p className="text-sm text-slate-400">No documents found</p>
            </div>
          ) : (
            Object.entries(grouped).map(([category, items]) => (
              <div key={category}>
                {/* Category header */}
                <div className="px-4 pt-3 pb-1.5">
                  <CategoryBadge category={category} />
                </div>
                {items.map(doc => (
                  <button
                    key={doc.path}
                    onClick={() => loadDoc(doc)}
                    className={`w-full text-left px-4 py-2.5 border-b border-slate-50 last:border-0 transition-colors ${
                      selectedDoc?.path === doc.path
                        ? 'bg-indigo-50/70 border-l-2 border-l-indigo-500'
                        : 'hover:bg-slate-50'
                    }`}
                  >
                    <p className={`text-sm font-medium truncate ${selectedDoc?.path === doc.path ? 'text-indigo-700' : 'text-slate-800'}`}>
                      {doc.name}
                    </p>
                    <p className="text-xs text-slate-400 mt-0.5 leading-relaxed line-clamp-2">
                      {doc.description}
                    </p>
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Right panel — markdown viewer */}
      <div className="flex-1 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
        {!selectedDoc ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
            <BookMarked size={40} className="text-slate-200 mb-3" />
            <p
              className="font-semibold text-slate-500"
              style={{ fontFamily: 'Outfit, sans-serif' }}
            >
              Select a document
            </p>
            <p className="text-slate-400 text-sm mt-1">
              Choose any document from the list to read it here
            </p>
          </div>
        ) : docLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 size={24} className="animate-spin text-indigo-400" />
          </div>
        ) : error ? (
          <div className="flex-1 flex items-center justify-center px-8">
            <div className="flex items-center gap-2 text-rose-600 text-sm">
              <AlertCircle size={16} /> {error}
            </div>
          </div>
        ) : (
          <>
            {/* Viewer header */}
            <div className="px-5 py-3 border-b border-slate-100 bg-slate-50 flex items-center gap-3">
              <FileText size={13} className="text-slate-400" />
              <span
                className="text-sm font-semibold text-slate-700"
                style={{ fontFamily: 'Outfit, sans-serif' }}
              >
                {selectedDoc.name}
              </span>
              <CategoryBadge category={selectedDoc.category} />
              <span className="ml-auto text-xs font-mono text-slate-400">{selectedDoc.path}</span>
            </div>
            <div className="flex-1 overflow-y-auto p-6 prose prose-slate prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add services/web-dashboard/src/components/pages/ProjectDocsPage.jsx
git commit -m "feat(frontend): add ProjectDocsPage with two-panel layout and ReactMarkdown viewer"
```

---

## Task 5: Frontend — Wire into `App.jsx` and `Sidebar.jsx`

**Files:**
- Modify: `services/web-dashboard/src/App.jsx`
- Modify: `services/web-dashboard/src/components/layout/Sidebar.jsx`

### App.jsx changes

**Step 1: Add import**

After `import ResetPage from './components/pages/ResetPage.jsx';`, add:
```jsx
import ProjectDocsPage from './components/pages/ProjectDocsPage.jsx';
```

**Step 2: Add to `PAGE_META`**

After the `reset:` entry:
```js
  'project-docs': { title: 'Project Docs', subtitle: 'Browse governance documents, ADRs, and checklists', step: null },
```

**Step 3: Add to `renderPage` switch**

After `case 'reset': return <ResetPage />;`:
```jsx
    case 'project-docs': return <ProjectDocsPage />;
```

### Sidebar.jsx changes

**Step 4: Add `BookMarked` to lucide import**

Change:
```js
import { Upload, Plug, Bot, BookOpen, FileText, CheckSquare, Trash2, Zap } from 'lucide-react';
```
to:
```js
import { Upload, Plug, Bot, BookOpen, FileText, CheckSquare, Trash2, Zap, BookMarked } from 'lucide-react';
```

**Step 5: Add nav item to Admin group**

In `NAV_GROUPS`, find the `Admin` group items array and add:
```js
      { id: 'project-docs', label: 'Project Docs', icon: BookMarked },
```
after the `reset` entry.

**Step 6: Commit**

```bash
git add services/web-dashboard/src/App.jsx services/web-dashboard/src/components/layout/Sidebar.jsx
git commit -m "feat(nav): add Project Docs page to Admin section in sidebar and router"
```

---

## Task 6: Final verification

**Step 1: Run full backend test suite**

```bash
cd services/integration-agent && python -m pytest tests/ -v --tb=short 2>&1 | tail -5
```
Expected: all tests pass (previously 113 + 6 new = 119).

**Step 2: Verify the page in browser**

- Open dashboard → Admin → "Project Docs"
- List shows 18 entries grouped into 5 categories
- Click any ADR → right panel renders markdown with headers and tables
- Click "Code Review Checklist" → checklist renders correctly

**Step 3: Commit design docs**

```bash
git add docs/plans/2026-03-16-project-docs-page-design.md docs/plans/2026-03-16-project-docs-page-plan.md
git commit -m "docs: add design and implementation plan for Project Docs page"
```
