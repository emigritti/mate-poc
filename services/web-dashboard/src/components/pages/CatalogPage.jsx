import { useState, useEffect } from 'react';
import { BookOpen, RefreshCw, ArrowRight, Loader2, AlertCircle } from 'lucide-react';
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

function IntegrationCard({ integration }) {
  const statusCfg = STATUS_MAP[integration.status] ?? { variant: 'slate', label: integration.status };
  const typeColor = TYPE_PILL[integration.type] ?? 'bg-slate-100 text-slate-600';

  return (
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
      </div>

      {integration.requirement_ids?.length > 0 && (
        <div className="px-5 py-2.5 bg-slate-50 border-t border-slate-100">
          <p className="text-xs text-slate-400">
            <span className="font-semibold text-slate-600">{integration.requirement_ids.length}</span>
            {' '}linked requirement{integration.requirement_ids.length !== 1 ? 's' : ''}
          </p>
        </div>
      )}
    </div>
  );
}

export default function CatalogPage() {
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState(null);
  const [filter, setFilter]             = useState('all');

  useEffect(() => { load(); }, []);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res  = await API.catalog.list();
      const data = await res.json();
      // Backend returns { status, data: [...] }
      setIntegrations(data.data || []);
    } catch {
      setError('Failed to load integrations');
    } finally {
      setLoading(false);
    }
  };

  const statuses  = ['all', ...new Set(integrations.map(i => i.status).filter(Boolean))];
  const filtered  = filter === 'all' ? integrations : integrations.filter(i => i.status === filter);

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
            <IntegrationCard key={int.id} integration={int} />
          ))}
        </div>
      )}
    </div>
  );
}
