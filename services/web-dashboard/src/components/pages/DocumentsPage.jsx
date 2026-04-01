import { useState, useEffect } from 'react';
import { FileText, BookOpen, Loader2, AlertCircle } from 'lucide-react';
import MarkdownViewer from '../ui/MarkdownViewer.jsx';
import Badge from '../ui/Badge.jsx';
import { API } from '../../api.js';

export default function DocumentsPage() {
  const [integrations, setIntegrations]   = useState([]);
  const [selectedId, setSelectedId]       = useState(null);
  const [content, setContent]             = useState('');
  const [listLoading, setListLoading]     = useState(true);
  const [specLoading, setSpecLoading]     = useState(false);
  const [error, setError]                 = useState(null);
  const [docStatuses, setDocStatuses]     = useState({});
  const [promoting, setPromoting]         = useState(false);
  const [promoteMsg, setPromoteMsg]       = useState('');

  // doc ID follows backend convention: {integration_id}-integration
  const selectedDocId = selectedId ? `${selectedId}-integration` : null;

  const loadDocStatuses = async () => {
    try {
      const res  = await API.documents.list();
      const docs = await res.json();
      const map  = {};
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

  const handleSelect = async (id) => {
    setSelectedId(id);
    setSpecLoading(true);
    setError(null);
    setContent('');
    setPromoteMsg('');
    setPromoting(false);
    try {
      const res = await API.catalog.integrationSpec(id);
      const d   = await res.json();
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
      const res    = await API.documents.promoteToKB(selectedDocId);
      const result = await res.json();
      if (result.status === 'success') {
        setPromoteMsg('Successfully promoted to Knowledge Base!');
        await loadDocStatuses();
      } else {
        setPromoteMsg(result.detail || 'Promotion failed.');
      }
    } catch {
      setPromoteMsg('Error: could not promote document.');
    } finally {
      setPromoting(false);
    }
  };

  const handleDownload = () => {
    if (!content || !selectedId) return;
    const blob = new Blob([content], { type: 'text/markdown' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `${selectedId}-integration.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const kbStatus = selectedDocId ? docStatuses[selectedDocId] : null;

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
            integrations.map(int => {
              const docId    = `${int.id}-integration`;
              const kbState  = docStatuses[docId];
              const isActive = selectedId === int.id;
              return (
                <div
                  key={int.id}
                  className={`border-b border-slate-100 last:border-0 ${isActive ? 'bg-indigo-50/60' : ''}`}
                >
                  <div className="px-4 py-3">
                    <p className="text-sm font-medium text-slate-900 truncate">{int.name}</p>
                    <p className="text-xs font-mono text-slate-400 mt-0.5 truncate">{int.id}</p>

                    {kbState && (
                      <span className={
                        kbState === 'promoted'
                          ? 'inline-block mt-1 text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-600 border border-emerald-500/30'
                          : 'inline-block mt-1 text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-600 border border-amber-500/30'
                      }>
                        {kbState === 'promoted' ? 'In KB' : 'Staged'}
                      </span>
                    )}

                    {/* Tags — always shown */}
                    <div className="flex flex-wrap gap-1 mt-2">
                      {(int.tags || []).length > 0 ? (
                        int.tags.map(tag => (
                          <span
                            key={tag}
                            className="px-1.5 py-0.5 bg-indigo-50 text-indigo-600 border border-indigo-100 rounded-full text-xs font-medium"
                          >
                            {tag}
                          </span>
                        ))
                      ) : (
                        <span className="text-xs text-slate-400 italic">No tags</span>
                      )}
                    </div>

                    <div className="mt-2">
                      <button
                        onClick={() => handleSelect(int.id)}
                        className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                          isActive
                            ? 'bg-indigo-600 text-white'
                            : 'bg-slate-100 text-slate-600 hover:bg-indigo-100 hover:text-indigo-700'
                        }`}
                      >
                        <FileText size={10} />
                        Integration Spec
                      </button>
                    </div>
                  </div>
                </div>
              );
            })
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
              Select an integration
            </p>
            <p className="text-slate-400 text-sm mt-1">
              Click "Integration Spec" to view the generated document
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
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider flex-1">
                Integration Specification
              </span>
              {content && (
                <button
                  onClick={handleDownload}
                  className="flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-medium bg-slate-100 text-slate-600 hover:bg-indigo-100 hover:text-indigo-700 transition-all"
                  title={`Download ${selectedId}-integration.md`}
                >
                  ⬇ Download
                </button>
              )}
            </div>

            <div className="flex-1 overflow-y-auto p-6">
              <MarkdownViewer>{content}</MarkdownViewer>
            </div>

            {/* Promote to KB — only when staged */}
            {kbStatus === 'staged' && (
              <div className="px-6 pt-4 border-t border-slate-100">
                <button
                  onClick={handlePromote}
                  disabled={promoting}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium disabled:opacity-50 transition-colors"
                >
                  {promoting ? 'Promoting...' : '⬆ Promote to KB'}
                </button>
              </div>
            )}

            {promoteMsg && (
              <div className={`px-6 pb-4${kbStatus === 'staged' ? ' pt-2' : ' pt-4 border-t border-slate-100'}`}>
                <span className={
                  promoteMsg.startsWith('Error') || promoteMsg.includes('failed')
                    ? 'text-rose-500 text-sm'
                    : 'text-emerald-600 text-sm'
                }>
                  {promoteMsg}
                </span>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
