import { useState, useEffect } from 'react';
import { BookMarked, FileText, Loader2, AlertCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { API } from '../../api.js';

// ── Category badge colours ────────────────────────────────────────────────────
const CATEGORY_STYLE = {
  'How-To':    'bg-teal-100   text-teal-700',
  'Guide':     'bg-emerald-100 text-emerald-700',
  'ADR':       'bg-blue-100   text-blue-700',
  'Checklist': 'bg-amber-100  text-amber-700',
  'Test Plan': 'bg-violet-100 text-violet-700',
  'Mapping':   'bg-slate-100  text-slate-600',
};

const CATEGORY_ORDER = ['How-To', 'Guide', 'ADR', 'Checklist', 'Test Plan', 'Mapping'];

function CategoryBadge({ category }) {
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide ${
        CATEGORY_STYLE[category] ?? 'bg-slate-100 text-slate-600'
      }`}
    >
      {category}
    </span>
  );
}

export default function ProjectDocsPage() {
  const [docs,        setDocs]        = useState([]);
  const [selectedDoc, setSelectedDoc] = useState(null);
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

      {/* ── Left panel — document list ─────────────────────────────────────── */}
      <div className="w-72 flex-shrink-0 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
        <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-2">
          <BookMarked size={14} className="text-slate-400" />
          <span className="font-semibold text-slate-900 text-sm" style={{ fontFamily: 'Outfit, sans-serif' }}>
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
                    <p className={`text-sm font-medium truncate ${
                      selectedDoc?.path === doc.path ? 'text-indigo-700' : 'text-slate-800'
                    }`}>
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

      {/* ── Right panel — markdown viewer ──────────────────────────────────── */}
      <div className="flex-1 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
        {!selectedDoc ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
            <BookMarked size={40} className="text-slate-200 mb-3" />
            <p className="font-semibold text-slate-500" style={{ fontFamily: 'Outfit, sans-serif' }}>
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
              <span className="text-sm font-semibold text-slate-700" style={{ fontFamily: 'Outfit, sans-serif' }}>
                {selectedDoc.name}
              </span>
              <CategoryBadge category={selectedDoc.category} />
              <span className="ml-auto text-xs font-mono text-slate-400">{selectedDoc.path}</span>
            </div>

            {/* Markdown content */}
            <div className="flex-1 overflow-y-auto p-6 prose prose-slate prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
