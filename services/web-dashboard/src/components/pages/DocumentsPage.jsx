import { useState, useEffect } from 'react';
import { FileText, BookOpen, Loader2, AlertCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import Badge from '../ui/Badge.jsx';
import { API } from '../../api.js';

export default function DocumentsPage() {
  const [integrations, setIntegrations] = useState([]);
  const [selectedId, setSelectedId]     = useState(null);
  const [specType, setSpecType]         = useState('functional');
  const [content, setContent]           = useState('');
  const [listLoading, setListLoading]   = useState(true);
  const [specLoading, setSpecLoading]   = useState(false);
  const [error, setError]               = useState(null);
  const [docStatuses, setDocStatuses]   = useState({});
  const [promoting, setPromoting]       = useState(false);
  const [promoteMsg, setPromoteMsg]     = useState('');
  const [selectedDocId, setSelectedDocId] = useState(null);

  const loadDocStatuses = async () => {
    try {
      const docs = await API.documents.list();
      const map = {};
      if (Array.isArray(docs)) {
        docs.forEach(d => { map[d.id] = d.kb_status; });
      }
      setDocStatuses(map);
    } catch (e) {
      console.error('Failed to load document statuses', e);
    }
  };

  useEffect(() => {
    API.catalog.list()
      .then(r => r.json())
      .then(d => setIntegrations(d.data || []))
      .catch(() => {})
      .finally(() => setListLoading(false));
    loadDocStatuses();
  }, []);

  const loadSpec = async (id, type) => {
    setSpecLoading(true);
    setError(null);
    setContent('');
    try {
      const fn  = type === 'functional' ? API.catalog.functionalSpec : API.catalog.technicalSpec;
      const res = await fn(id);
      const d   = await res.json();
      // Backend returns { status, data: { content, ... } }
      setContent(d.data?.content || d.content || '');
    } catch {
      setError('Failed to load specification');
    } finally {
      setSpecLoading(false);
    }
  };

  const handlePromote = async () => {
    if (!selectedDocId) return;
    setPromoting(true);
    setPromoteMsg('');
    try {
      const result = await API.documents.promoteToKB(selectedDocId);
      if (result.status === 'success') {
        setPromoteMsg('Successfully promoted to Knowledge Base!');
        await loadDocStatuses();
      } else {
        setPromoteMsg(result.detail || 'Promotion failed.');
      }
    } catch (e) {
      setPromoteMsg('Error: could not promote document.');
    } finally {
      setPromoting(false);
    }
  };

  const handleSelect = (id, type) => {
    setSelectedId(id);
    setSpecType(type);
    setSelectedDocId(`${id}-${type}`);
    setPromoteMsg('');
    setPromoting(false);
    loadSpec(id, type);
  };

  return (
    <div className="flex gap-5" style={{ height: 'calc(100vh - 200px)' }}>
      {/* Left: integration list */}
      <div className="w-72 flex-shrink-0 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
        <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-2">
          <BookOpen size={14} className="text-slate-400" />
          <span
            className="font-semibold text-slate-900 text-sm"
            style={{ fontFamily: 'Outfit, sans-serif' }}
          >
            Integrations
          </span>
          <Badge variant="slate">{integrations.length}</Badge>
        </div>

        <div className="overflow-y-auto flex-1">
          {listLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 size={20} className="animate-spin text-slate-300" />
            </div>
          ) : integrations.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <p className="text-sm text-slate-400">No integrations found</p>
            </div>
          ) : (
            integrations.map(int => (
              <div
                key={int.id}
                className={`border-b border-slate-100 last:border-0 ${
                  selectedId === int.id ? 'bg-indigo-50/60' : ''
                }`}
              >
                <div className="px-4 py-3">
                  <p className="text-sm font-medium text-slate-900 truncate">{int.name}</p>
                  <p className="text-xs font-mono text-slate-400 mt-0.5 truncate">{int.id}</p>
                  {docStatuses[`${int.id}-functional`] && (
                    <span className={
                      docStatuses[`${int.id}-functional`] === 'promoted'
                        ? 'text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                        : 'text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30'
                    }>
                      {docStatuses[`${int.id}-functional`] === 'promoted' ? 'In KB' : 'Staged'}
                    </span>
                  )}
                  <div className="flex gap-2 mt-2">
                    {['functional', 'technical'].map(type => (
                      <button
                        key={type}
                        onClick={() => handleSelect(int.id, type)}
                        className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                          selectedId === int.id && specType === type
                            ? 'bg-indigo-600 text-white'
                            : 'bg-slate-100 text-slate-600 hover:bg-indigo-100 hover:text-indigo-700'
                        }`}
                      >
                        <FileText size={10} />
                        {type.charAt(0).toUpperCase() + type.slice(1)}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Right: spec viewer */}
      <div className="flex-1 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
        {!selectedId ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
            <FileText size={40} className="text-slate-200 mb-3" />
            <p
              className="font-semibold text-slate-500"
              style={{ fontFamily: 'Outfit, sans-serif' }}
            >
              Select a specification
            </p>
            <p className="text-slate-400 text-sm mt-1">
              Choose an integration and click Functional or Technical
            </p>
          </div>
        ) : specLoading ? (
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
            <div className="px-5 py-3 border-b border-slate-100 bg-slate-50 flex items-center gap-2">
              <FileText size={13} className="text-slate-400" />
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                {specType === 'functional' ? 'Functional' : 'Technical'} Specification
              </span>
            </div>
            <div className="flex-1 overflow-y-auto p-6 prose prose-slate prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
            {selectedDocId && docStatuses[selectedDocId] === 'staged' && (
              <div className="px-6 py-4 border-t border-slate-100 flex items-center gap-3">
                <button
                  onClick={handlePromote}
                  disabled={promoting}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium disabled:opacity-50 transition-colors"
                >
                  {promoting ? 'Promoting...' : '⬆ Promote to KB'}
                </button>
                {promoteMsg && (
                  <span className={promoteMsg.startsWith('Error') || promoteMsg.includes('failed') ? 'text-rose-400 text-sm' : 'text-emerald-400 text-sm'}>
                    {promoteMsg}
                  </span>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
