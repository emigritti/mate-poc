import { useState, useEffect, useCallback } from 'react';
import { BookOpen, RefreshCw, ArrowRight, Loader2, AlertCircle, X, FileText } from 'lucide-react';
import MarkdownViewer from '../ui/MarkdownViewer.jsx';
import Badge from '../ui/Badge.jsx';
import { API } from '../../api.js';

const STATUS_MAP = {
  APPROVED:           { variant: 'success', label: 'Approved' },
  PENDING_APPROVAL:   { variant: 'warning', label: 'Pending Approval' },
  PENDING_TAG_REVIEW: { variant: 'info',    label: 'Pending Tags' },
  REJECTED:           { variant: 'error',   label: 'Rejected' },
  GENERATED:          { variant: 'primary', label: 'Generated' },
};

const TYPE_PILL = {
  'REST-to-REST': 'bg-blue-100 text-blue-700',
  'REST-to-SOAP': 'bg-purple-100 text-purple-700',
  'SOAP-to-REST': 'bg-violet-100 text-violet-700',
  'File-based':   'bg-amber-100 text-amber-700',
};

// ── Markdown viewer modal ────────────────────────────────────────────────────

function DocModal({ title, content, onClose }) {
  useEffect(() => {
    const esc = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.45)' }}
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl flex flex-col overflow-hidden"
        style={{ width: '90vw', maxWidth: 900, maxHeight: '88vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50 flex-shrink-0">
          <div className="flex items-center gap-2">
            <FileText size={14} className="text-slate-400" />
            <span className="font-semibold text-slate-800 text-sm" style={{ fontFamily: 'Outfit, sans-serif' }}>
              {title}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-slate-200 text-slate-500 hover:text-slate-800 transition-colors"
          >
            <X size={16} />
          </button>
        </div>
        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6">
          <MarkdownViewer>{content}</MarkdownViewer>
        </div>
      </div>
    </div>
  );
}

// ── Integration card ─────────────────────────────────────────────────────────

function IntegrationCard({ integration, onRefresh }) {
  const statusCfg = STATUS_MAP[integration.status] ?? { variant: 'slate', label: integration.status };
  const typeColor = TYPE_PILL[integration.type] ?? 'bg-slate-100 text-slate-600';
  const [modal,   setModal]   = useState(null); // { title, content }
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState(null);

  const hasSpec = integration.status === 'DONE';

  const viewSpec = async () => {
    setLoading(true);
    setError(null);
    try {
      const res  = await API.catalog.integrationSpec(integration.id);
      const data = await res.json();
      if (!res.ok || data.status === 'error') {
        throw new Error(data.message || data.detail || `Error ${res.status}`);
      }
      setModal({
        title: `Integration Spec — ${integration.name || integration.id}`,
        content: data.data?.content || '',
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {modal && <DocModal title={modal.title} content={modal.content} onClose={() => setModal(null)} />}

      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 overflow-hidden flex flex-col">
        {/* Status accent bar */}
        <div
          className={`h-1 flex-shrink-0 ${
            statusCfg.variant === 'success' ? 'bg-emerald-400'
            : statusCfg.variant === 'warning' ? 'bg-amber-400'
            : statusCfg.variant === 'error' ? 'bg-rose-400'
            : statusCfg.variant === 'info' ? 'bg-blue-400'
            : statusCfg.variant === 'primary' ? 'bg-indigo-400'
            : 'bg-slate-200'
          }`}
        />

        <div className="px-5 pt-4 pb-4 flex-1">
          <div className="flex items-start justify-between mb-3">
            <div className="flex-1 min-w-0 pr-3">
              <h3
                className="font-semibold text-slate-900 truncate"
                style={{ fontFamily: 'Outfit, sans-serif' }}
              >
                {integration.name}
              </h3>
              <p className="text-xs font-mono text-slate-400 mt-0.5 truncate">{integration.id}</p>
            </div>
            <Badge variant={statusCfg.variant} dot>{statusCfg.label}</Badge>
          </div>

          {/* Source → Target */}
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs font-medium text-slate-600 truncate max-w-[110px] bg-slate-100 px-2 py-0.5 rounded">
              {integration.source?.system || '—'}
            </span>
            <ArrowRight size={12} className="text-slate-400 flex-shrink-0" />
            <span className="text-xs font-medium text-slate-600 truncate max-w-[110px] bg-slate-100 px-2 py-0.5 rounded">
              {integration.target?.system || '—'}
            </span>
          </div>

          {integration.type && (
            <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold ${typeColor}`}>
              {integration.type}
            </span>
          )}

          {/* Tags — always shown */}
          <div className="flex flex-wrap gap-1 mt-2.5">
            {(integration.tags || []).length > 0 ? (
              integration.tags.map(tag => (
                <span
                  key={tag}
                  className="px-2 py-0.5 bg-indigo-50 text-indigo-600 border border-indigo-100 rounded-full text-xs font-medium"
                >
                  {tag}
                </span>
              ))
            ) : (
              <span className="text-xs text-slate-400 italic">No tags</span>
            )}
          </div>
        </div>

        {integration.requirement_ids?.length > 0 && (
          <div className="px-5 py-2.5 bg-slate-50 border-t border-slate-100">
            <p className="text-xs text-slate-400">
              <span className="font-semibold text-slate-600">{integration.requirement_ids.length}</span>
              {' '}linked requirement{integration.requirement_ids.length !== 1 ? 's' : ''}
            </p>
          </div>
        )}

        {/* Integration Spec action */}
        {hasSpec && (
          <div className="px-5 py-3 border-t border-slate-100 bg-slate-50 space-y-1.5">
            <button
              onClick={viewSpec}
              disabled={loading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? <Loader2 size={11} className="animate-spin" /> : <FileText size={11} />}
              {loading ? 'Caricamento...' : 'View Integration Spec'}
            </button>
            {error && (
              <p className="text-xs text-rose-600 flex items-center gap-1">
                <AlertCircle size={11} />
                {error.length > 120 ? `${error.slice(0, 120)}…` : error}
              </p>
            )}
          </div>
        )}
      </div>
    </>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function CatalogPage() {
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState(null);
  const [filter, setFilter]             = useState('all');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res  = await API.catalog.list();
      const data = await res.json();
      setIntegrations(data.data || []);
    } catch {
      setError('Failed to load integrations');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const statuses = ['all', ...new Set(integrations.map(i => i.status).filter(Boolean))];
  const filtered = filter === 'all' ? integrations : integrations.filter(i => i.status === filter);
  const countFor = (s) =>
    s === 'all' ? integrations.length : integrations.filter(i => i.status === s).length;

  return (
    <div className="space-y-5">
      {/* Toolbar */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          {statuses.map(s => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                filter === s
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'bg-white text-slate-600 border border-slate-200 hover:border-indigo-300 hover:text-indigo-600'
              }`}
            >
              {s === 'all' ? 'All' : (STATUS_MAP[s]?.label ?? s)} ({countFor(s)})
            </button>
          ))}
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm text-slate-600 border border-slate-200 hover:border-indigo-300 hover:text-indigo-600 bg-white transition-colors"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={24} className="animate-spin text-indigo-400" />
        </div>
      ) : error ? (
        <div className="flex items-center gap-2 text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-4 py-3 text-sm">
          <AlertCircle size={16} /> {error}
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <BookOpen size={40} className="text-slate-200 mb-3" />
          <p className="font-semibold text-slate-500" style={{ fontFamily: 'Outfit, sans-serif' }}>
            No integrations yet
          </p>
          <p className="text-slate-400 text-sm mt-1">Run the agent to generate integration specifications</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map(int => (
            <IntegrationCard key={int.id} integration={int} onRefresh={load} />
          ))}
        </div>
      )}
    </div>
  );
}
