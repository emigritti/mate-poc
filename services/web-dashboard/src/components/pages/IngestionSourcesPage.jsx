import { useState, useRef, useEffect, useCallback } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  DatabaseZap, Play, Pause, Trash2, ChevronDown, ChevronRight,
  Plus, X, AlertCircle, CheckCircle2, Loader2, Clock,
  Hash, Activity, RefreshCw,
} from 'lucide-react';
import Badge from '../ui/Badge.jsx';
import { API } from '../../api.js';

// ── Constants ────────────────────────────────────────────────────────────────

const CRON_PRESETS = [
  { label: 'Every hour',          value: '0 * * * *'   },
  { label: 'Every 6 hours',       value: '0 */6 * * *' },
  { label: 'Every 12 hours',      value: '0 */12 * * *'},
  { label: 'Daily at midnight',   value: '0 0 * * *'   },
  { label: 'Daily at 6am',        value: '0 6 * * *'   },
  { label: 'Weekly (Sun midnight)', value: '0 0 * * 0' },
  { label: 'Custom…',             value: 'custom'      },
];

const SOURCE_TYPES = [
  { value: 'openapi', label: 'OpenAPI', hint: 'e.g. https://api.example.com/openapi.json' },
  { value: 'html',    label: 'HTML',    hint: 'Seed URL(s) for the crawler' },
  { value: 'mcp',     label: 'MCP',     hint: 'MCP server address(es) — Phase 3, not yet active' },
];

const TYPE_BADGE_VARIANT = { openapi: 'primary', html: 'info', mcp: 'warning' };
const STATE_BADGE_VARIANT = { active: 'success', paused: 'slate', error: 'error' };

const RUN_STATUS_VARIANT = {
  pending: 'slate', running: 'info', success: 'success', failed: 'error', partial: 'warning',
};

const TRIGGER_VARIANT = { scheduler: 'slate', manual: 'primary', webhook: 'info' };

const POLL_INTERVAL_MS  = 3000;
const POLL_TIMEOUT_MS   = 60000;

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

function fmtDuration(started, finished) {
  if (!started || !finished) return '—';
  const secs = Math.round((new Date(finished) - new Date(started)) / 1000);
  return secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

function isValidSlug(v) { return /^[a-z0-9_]+$/.test(v); }

function isValidCron(v) { return v.trim().split(/\s+/).length === 5; }

// ── Sub-components ────────────────────────────────────────────────────────────

function StatCard({ icon: Icon, label, value, color = 'text-indigo-600' }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm px-5 py-4 flex items-center gap-4">
      <div className={`w-9 h-9 rounded-lg bg-slate-100 flex items-center justify-center flex-shrink-0`}>
        <Icon size={18} className={color} />
      </div>
      <div>
        <p className="text-xs text-slate-500 font-medium">{label}</p>
        <p className="text-lg font-bold text-slate-800 leading-tight">{value}</p>
      </div>
    </div>
  );
}

function TagChips({ tags, onRemove }) {
  return (
    <div className="flex flex-wrap gap-1.5 mt-1">
      {tags.map(t => (
        <span key={t} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 text-xs font-medium border border-indigo-100">
          {t}
          {onRemove && (
            <button type="button" onClick={() => onRemove(t)} className="hover:text-rose-500">
              <X size={11} />
            </button>
          )}
        </span>
      ))}
    </div>
  );
}

function RunRow({ run }) {
  const [showErrors, setShowErrors] = useState(false);
  return (
    <>
      <tr className="hover:bg-slate-50 text-sm">
        <td className="px-3 py-2 font-mono text-xs text-slate-500">{run.id?.slice(0, 20)}…</td>
        <td className="px-3 py-2">
          <Badge variant={TRIGGER_VARIANT[run.trigger] ?? 'slate'}>{run.trigger}</Badge>
        </td>
        <td className="px-3 py-2">
          <Badge variant={RUN_STATUS_VARIANT[run.status] ?? 'slate'}>{run.status}</Badge>
        </td>
        <td className="px-3 py-2 text-slate-600 text-xs">{fmtDate(run.started_at)}</td>
        <td className="px-3 py-2 text-slate-600 text-xs">{fmtDuration(run.started_at, run.finished_at)}</td>
        <td className="px-3 py-2 text-slate-700 text-xs text-right">{run.chunks_created ?? 0}</td>
        <td className="px-3 py-2 text-right">
          {run.errors?.length > 0 && (
            <button onClick={() => setShowErrors(v => !v)} className="text-rose-500 hover:text-rose-600">
              <AlertCircle size={14} />
            </button>
          )}
        </td>
      </tr>
      {showErrors && run.errors?.length > 0 && (
        <tr>
          <td colSpan={7} className="px-3 pb-3">
            <pre className="text-xs bg-rose-50 border border-rose-200 rounded p-2 text-rose-700 whitespace-pre-wrap break-all">
              {run.errors.join('\n')}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}

function SnapshotCard({ snap }) {
  return (
    <div className="bg-slate-50 rounded-lg border border-slate-200 p-4 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono text-xs text-slate-500 bg-white border border-slate-200 px-2 py-0.5 rounded">
          <Hash size={10} className="inline mr-1" />{snap.content_hash?.slice(0, 8)}
        </span>
        {snap.is_current && <Badge variant="success" dot>current</Badge>}
        <span className="text-xs text-slate-500">{fmtDate(snap.captured_at)}</span>
        <span className="text-xs text-slate-500 ml-auto">{snap.capabilities_count} capabilities</span>
      </div>
      {snap.diff_summary && (
        <p className="text-sm text-slate-700 leading-relaxed">{snap.diff_summary}</p>
      )}
      {!snap.diff_summary && (
        <p className="text-xs text-slate-400 italic">No diff summary available</p>
      )}
    </div>
  );
}

// ── Expanded Detail Panel ──────────────────────────────────────────────────

function ExpandedPanel({ sourceId, panel, onPanelChange }) {
  const { data: runs = [], isLoading: runsLoading } = useQuery({
    queryKey: ['ingestion', 'runs', sourceId],
    queryFn: () => API.ingestion.getSourceRuns(sourceId).then(r => r.json()),
    enabled: panel === 'runs',
  });

  const { data: snapshots = [], isLoading: snapsLoading } = useQuery({
    queryKey: ['ingestion', 'snapshots', sourceId],
    queryFn: () => API.ingestion.getSourceSnapshots(sourceId).then(r => r.json()),
    enabled: panel === 'snapshots',
  });

  return (
    <tr>
      <td colSpan={6} className="px-4 pb-4 bg-slate-50 border-b border-slate-200">
        <div className="mt-2 space-y-3">
          {/* Tab bar */}
          <div className="flex gap-1 border-b border-slate-200 pb-2">
            {['runs', 'snapshots'].map(p => (
              <button
                key={p}
                onClick={() => onPanelChange(p)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  panel === p
                    ? 'bg-indigo-600 text-white'
                    : 'text-slate-500 hover:text-slate-700 hover:bg-slate-100'
                }`}
              >
                {p === 'runs' ? 'Run History' : 'Snapshots'}
              </button>
            ))}
          </div>

          {/* Run history */}
          {panel === 'runs' && (
            runsLoading ? (
              <div className="flex items-center gap-2 text-slate-400 text-sm py-2">
                <Loader2 size={14} className="animate-spin" /> Loading runs…
              </div>
            ) : runs.length === 0 ? (
              <p className="text-sm text-slate-400 italic py-2">No runs yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-slate-500 font-semibold border-b border-slate-200">
                      <th className="px-3 py-1.5 text-left">Run ID</th>
                      <th className="px-3 py-1.5 text-left">Trigger</th>
                      <th className="px-3 py-1.5 text-left">Status</th>
                      <th className="px-3 py-1.5 text-left">Started</th>
                      <th className="px-3 py-1.5 text-left">Duration</th>
                      <th className="px-3 py-1.5 text-right">Chunks</th>
                      <th className="px-3 py-1.5 text-right">Errors</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map(r => <RunRow key={r.id} run={r} />)}
                  </tbody>
                </table>
              </div>
            )
          )}

          {/* Snapshots */}
          {panel === 'snapshots' && (
            snapsLoading ? (
              <div className="flex items-center gap-2 text-slate-400 text-sm py-2">
                <Loader2 size={14} className="animate-spin" /> Loading snapshots…
              </div>
            ) : snapshots.length === 0 ? (
              <p className="text-sm text-slate-400 italic py-2">No snapshots yet.</p>
            ) : (
              <div className="space-y-2">
                {snapshots.map(s => <SnapshotCard key={s.id} snap={s} />)}
              </div>
            )
          )}
        </div>
      </td>
    </tr>
  );
}

// ── Register Source Modal ──────────────────────────────────────────────────

function RegisterSourceModal({ onClose, onCreated }) {
  const [form, setForm] = useState({
    code: '',
    source_type: 'openapi',
    entrypoints: [''],
    tags: [],
    cronPreset: '0 */6 * * *',
    cronCustom: '',
    description: '',
  });
  const [tagInput, setTagInput] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState({});

  const typeInfo = SOURCE_TYPES.find(t => t.value === form.source_type);

  function setField(k, v) { setForm(f => ({ ...f, [k]: v })); }

  function validate() {
    const e = {};
    if (!form.code) e.code = 'Required';
    else if (!isValidSlug(form.code)) e.code = 'Only lowercase letters, digits, underscores';
    if (!form.entrypoints.some(u => u.trim())) e.entrypoints = 'At least one URL is required';
    if (!form.tags.length) e.tags = 'At least one tag is required';
    const cronVal = form.cronPreset === 'custom' ? form.cronCustom : form.cronPreset;
    if (!isValidCron(cronVal)) e.cron = 'Invalid cron expression (5 fields)';
    return e;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const errs = validate();
    if (Object.keys(errs).length) { setErrors(errs); return; }
    setSubmitting(true);
    try {
      const cronVal = form.cronPreset === 'custom' ? form.cronCustom : form.cronPreset;
      const body = {
        code: form.code,
        source_type: form.source_type,
        entrypoints: form.entrypoints.filter(u => u.trim()),
        tags: form.tags,
        refresh_cron: cronVal,
        description: form.description || null,
      };
      const res = await API.ingestion.createSource(body);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast.error(err.detail || 'Failed to create source');
        return;
      }
      toast.success(`Source "${form.code}" registered`);
      onCreated();
    } finally {
      setSubmitting(false);
    }
  }

  function addTag() {
    const t = tagInput.trim().toLowerCase();
    if (t && !form.tags.includes(t)) setField('tags', [...form.tags, t]);
    setTagInput('');
  }

  function removeEntrypoint(i) {
    const next = form.entrypoints.filter((_, idx) => idx !== i);
    setField('entrypoints', next.length ? next : ['']);
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <div>
            <h2 className="text-base font-semibold text-slate-800">Register Ingestion Source</h2>
            <p className="text-xs text-slate-500 mt-0.5">Add an OpenAPI, HTML or MCP source to the KB pipeline</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {/* Code */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">Source code <span className="text-rose-500">*</span></label>
            <input
              type="text"
              value={form.code}
              onChange={e => setField('code', e.target.value)}
              placeholder="e.g. payment_api_v3"
              className={`w-full px-3 py-2 text-sm border rounded-lg focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100 outline-none ${errors.code ? 'border-rose-400' : 'border-slate-300'}`}
            />
            {errors.code && <p className="text-xs text-rose-500 mt-0.5">{errors.code}</p>}
          </div>

          {/* Source type */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">Source type <span className="text-rose-500">*</span></label>
            <select
              value={form.source_type}
              onChange={e => setField('source_type', e.target.value)}
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100 outline-none bg-white"
            >
              {SOURCE_TYPES.map(t => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
            {form.source_type === 'mcp' && (
              <p className="text-xs text-amber-600 mt-0.5">Phase 3 — MCP ingestion not yet active</p>
            )}
          </div>

          {/* Entrypoints */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">
              {typeInfo?.label} URL(s) <span className="text-rose-500">*</span>
              <span className="font-normal text-slate-400 ml-1">— {typeInfo?.hint}</span>
            </label>
            <div className="space-y-2">
              {form.entrypoints.map((url, i) => (
                <div key={i} className="flex gap-2">
                  <input
                    type="url"
                    value={url}
                    onChange={e => {
                      const next = [...form.entrypoints];
                      next[i] = e.target.value;
                      setField('entrypoints', next);
                    }}
                    placeholder="https://…"
                    className={`flex-1 px-3 py-2 text-sm border rounded-lg focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100 outline-none ${errors.entrypoints && !url.trim() ? 'border-rose-400' : 'border-slate-300'}`}
                  />
                  {form.entrypoints.length > 1 && (
                    <button type="button" onClick={() => removeEntrypoint(i)} className="text-slate-400 hover:text-rose-500">
                      <X size={16} />
                    </button>
                  )}
                </div>
              ))}
              <button
                type="button"
                onClick={() => setField('entrypoints', [...form.entrypoints, ''])}
                className="text-xs text-indigo-600 hover:text-indigo-700 flex items-center gap-1"
              >
                <Plus size={12} /> Add URL
              </button>
            </div>
            {errors.entrypoints && <p className="text-xs text-rose-500 mt-0.5">{errors.entrypoints}</p>}
          </div>

          {/* Tags */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">Tags <span className="text-rose-500">*</span></label>
            <div className={`border rounded-lg p-2 focus-within:border-indigo-400 focus-within:ring-1 focus-within:ring-indigo-100 ${errors.tags ? 'border-rose-400' : 'border-slate-300'}`}>
              <TagChips tags={form.tags} onRemove={t => setField('tags', form.tags.filter(x => x !== t))} />
              <input
                type="text"
                value={tagInput}
                onChange={e => setTagInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addTag(); } }}
                placeholder="Type tag + Enter"
                className="w-full text-sm outline-none mt-1 px-1"
              />
            </div>
            {errors.tags && <p className="text-xs text-rose-500 mt-0.5">{errors.tags}</p>}
          </div>

          {/* Cron */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">Refresh schedule</label>
            <select
              value={form.cronPreset}
              onChange={e => setField('cronPreset', e.target.value)}
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100 outline-none bg-white"
            >
              {CRON_PRESETS.map(p => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
            {form.cronPreset === 'custom' && (
              <input
                type="text"
                value={form.cronCustom}
                onChange={e => setField('cronCustom', e.target.value)}
                placeholder="0 */6 * * *"
                className={`mt-2 w-full px-3 py-2 text-sm border rounded-lg font-mono focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100 outline-none ${errors.cron ? 'border-rose-400' : 'border-slate-300'}`}
              />
            )}
            {errors.cron && <p className="text-xs text-rose-500 mt-0.5">{errors.cron}</p>}
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">Description <span className="text-slate-400 font-normal">(optional)</span></label>
            <textarea
              value={form.description}
              onChange={e => setField('description', e.target.value)}
              rows={2}
              placeholder="Short description of this source…"
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100 outline-none resize-none"
            />
          </div>
        </form>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-200">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg bg-slate-100 text-slate-600 hover:bg-slate-200"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="px-4 py-2 text-sm rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 flex items-center gap-2"
          >
            {submitting && <Loader2 size={14} className="animate-spin" />}
            Register Source
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Source Row ────────────────────────────────────────────────────────────────

function SourceRow({ source, expanded, expandedPanel, onToggle, onPanelChange, triggeringId, onTrigger, deletingId, onDeleteConfirm, onDeleteCancel, onDelete, onPauseActivate }) {
  const isTriggering = triggeringId === source.id;
  const isDeleting = deletingId === source.id;
  const state = source.status?.state ?? 'active';

  return (
    <>
      <tr className="hover:bg-slate-50 text-sm border-b border-slate-100">
        {/* Expand toggle */}
        <td className="px-3 py-3 w-8">
          <button onClick={() => onToggle(source.id)} className="text-slate-400 hover:text-slate-600">
            {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </button>
        </td>

        {/* Code */}
        <td className="px-3 py-3">
          <span className="font-mono font-medium text-slate-800">{source.code}</span>
          {source.description && (
            <p className="text-xs text-slate-400 mt-0.5 truncate max-w-[200px]">{source.description}</p>
          )}
        </td>

        {/* Type */}
        <td className="px-3 py-3">
          <Badge variant={TYPE_BADGE_VARIANT[source.source_type] ?? 'slate'}>
            {source.source_type?.toUpperCase()}
          </Badge>
        </td>

        {/* State */}
        <td className="px-3 py-3">
          <span title={source.status?.last_error ?? undefined}>
            <Badge variant={STATE_BADGE_VARIANT[state] ?? 'slate'} dot>
              {state}
            </Badge>
          </span>
        </td>

        {/* Last run */}
        <td className="px-3 py-3 text-xs text-slate-500">
          {fmtDate(source.status?.last_run_at)}
        </td>

        {/* Actions */}
        <td className="px-3 py-3 text-right">
          {isDeleting ? (
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={() => onDeleteConfirm(source.id)}
                className="px-2.5 py-1 text-xs rounded-md bg-rose-600 text-white hover:bg-rose-700"
              >
                Confirm
              </button>
              <button
                onClick={onDeleteCancel}
                className="px-2.5 py-1 text-xs rounded-md bg-slate-100 text-slate-600 hover:bg-slate-200"
              >
                Cancel
              </button>
            </div>
          ) : (
            <div className="flex items-center justify-end gap-1">
              {/* Trigger */}
              <button
                onClick={() => onTrigger(source)}
                disabled={isTriggering}
                title="Trigger ingestion now"
                className="p-1.5 rounded-lg text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 disabled:opacity-40"
              >
                {isTriggering
                  ? <Loader2 size={15} className="animate-spin text-indigo-500" />
                  : <Play size={15} />}
              </button>

              {/* Pause / Activate */}
              <button
                onClick={() => onPauseActivate(source)}
                title={state === 'active' ? 'Pause source' : 'Activate source'}
                className="p-1.5 rounded-lg text-slate-500 hover:text-amber-600 hover:bg-amber-50"
              >
                {state === 'active' ? <Pause size={15} /> : <Play size={15} />}
              </button>

              {/* Delete */}
              <button
                onClick={() => onDelete(source.id)}
                title="Delete source"
                className="p-1.5 rounded-lg text-slate-500 hover:text-rose-600 hover:bg-rose-50"
              >
                <Trash2 size={15} />
              </button>
            </div>
          )}
        </td>
      </tr>

      {expanded && (
        <ExpandedPanel
          sourceId={source.id}
          panel={expandedPanel}
          onPanelChange={onPanelChange}
        />
      )}
    </>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function IngestionSourcesPage() {
  const queryClient = useQueryClient();

  const [showRegisterModal, setShowRegisterModal] = useState(false);
  const [expandedSourceId, setExpandedSourceId] = useState(null);
  const [expandedPanel, setExpandedPanel] = useState('runs');
  const [deletingId, setDeletingId] = useState(null);
  const [triggeringId, setTriggeringId] = useState(null);
  const pollRef = useRef(null);

  const { data: sources = [], isLoading, isError } = useQuery({
    queryKey: ['ingestion', 'sources'],
    queryFn: () => API.ingestion.listSources().then(r => r.json()),
  });

  // Cleanup poll on unmount
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  // ── Derived stats ──────────────────────────────────────────────────────────

  const totalSources = sources.length;
  const activeSources = sources.filter(s => s.status?.state === 'active').length;
  const pausedSources = sources.filter(s => s.status?.state === 'paused').length;
  const lastRunAt = sources.reduce((latest, s) => {
    const t = s.status?.last_run_at;
    if (!t) return latest;
    return !latest || new Date(t) > new Date(latest) ? t : latest;
  }, null);

  // ── Handlers ───────────────────────────────────────────────────────────────

  function handleToggleRow(sourceId) {
    if (expandedSourceId === sourceId) {
      setExpandedSourceId(null);
    } else {
      setExpandedSourceId(sourceId);
      setExpandedPanel('runs');
    }
  }

  async function handleTrigger(source) {
    if (triggeringId) return;
    setTriggeringId(source.id);

    let runId = null;
    try {
      const res = await API.ingestion.triggerIngest(source.id, source.source_type);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast.error(err.detail || 'Failed to trigger ingestion');
        setTriggeringId(null);
        return;
      }
      const data = await res.json();
      runId = data.run_id;
      toast.info(`Ingestion started for "${source.code}"…`);
    } catch {
      toast.error('Network error triggering ingestion');
      setTriggeringId(null);
      return;
    }

    // Poll until terminal state or timeout
    const startedAt = Date.now();
    pollRef.current = setInterval(async () => {
      try {
        if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
          clearInterval(pollRef.current);
          setTriggeringId(null);
          toast.warning(`"${source.code}" ingestion is taking longer than expected — check Run History`);
          return;
        }

        const res = await API.ingestion.getRun(runId);
        if (!res.ok) return;
        const run = await res.json();
        const terminal = ['success', 'failed', 'partial'];

        if (terminal.includes(run.status)) {
          clearInterval(pollRef.current);
          setTriggeringId(null);
          queryClient.invalidateQueries({ queryKey: ['ingestion', 'sources'] });
          queryClient.invalidateQueries({ queryKey: ['ingestion', 'runs', source.id] });

          if (run.status === 'success') {
            toast.success(`"${source.code}" ingested successfully (${run.chunks_created} chunks)`);
          } else if (run.status === 'partial') {
            toast.warning(`"${source.code}" ingested with warnings (${run.chunks_created} chunks)`);
          } else {
            toast.error(`"${source.code}" ingestion failed — see Run History`);
          }
        }
      } catch {
        // Network hiccup — keep polling
      }
    }, POLL_INTERVAL_MS);
  }

  async function handlePauseActivate(source) {
    const state = source.status?.state;
    try {
      const res = state === 'active'
        ? await API.ingestion.pauseSource(source.id)
        : await API.ingestion.activateSource(source.id);
      if (!res.ok) throw new Error();
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'sources'] });
      toast.success(`"${source.code}" ${state === 'active' ? 'paused' : 'activated'}`);
    } catch {
      toast.error('Failed to update source state');
    }
  }

  async function handleDeleteConfirm(id) {
    try {
      const res = await API.ingestion.deleteSource(id);
      if (!res.ok) throw new Error();
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'sources'] });
      if (expandedSourceId === id) setExpandedSourceId(null);
      toast.success('Source deleted');
    } catch {
      toast.error('Failed to delete source');
    } finally {
      setDeletingId(null);
    }
  }

  function handleCreated() {
    setShowRegisterModal(false);
    queryClient.invalidateQueries({ queryKey: ['ingestion', 'sources'] });
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Stats bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard icon={DatabaseZap}   label="Total Sources"  value={totalSources} />
        <StatCard icon={CheckCircle2}  label="Active"         value={activeSources} color="text-emerald-600" />
        <StatCard icon={Pause}         label="Paused"         value={pausedSources} color="text-amber-500" />
        <StatCard icon={Clock}         label="Last Run"       value={lastRunAt ? fmtDate(lastRunAt) : 'Never'} color="text-slate-400" />
      </div>

      {/* Header + Add button */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-800">Sources</h2>
          <p className="text-xs text-slate-500 mt-0.5">Register and manage knowledge base ingestion sources</p>
        </div>
        <button
          onClick={() => setShowRegisterModal(true)}
          className="flex items-center gap-2 px-4 py-2 text-sm rounded-lg bg-indigo-600 text-white hover:bg-indigo-700"
        >
          <Plus size={14} /> Add Source
        </button>
      </div>

      {/* Sources table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        {isLoading && (
          <div className="flex items-center justify-center gap-2 py-16 text-slate-400">
            <Loader2 size={20} className="animate-spin" /> Loading sources…
          </div>
        )}
        {isError && (
          <div className="flex items-center justify-center gap-2 py-16 text-rose-500">
            <AlertCircle size={20} /> Failed to load sources. Is the ingestion platform running?
          </div>
        )}
        {!isLoading && !isError && sources.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-slate-400 gap-3">
            <DatabaseZap size={32} className="text-slate-300" />
            <p className="text-sm">No sources registered yet.</p>
            <button
              onClick={() => setShowRegisterModal(true)}
              className="text-sm text-indigo-600 hover:text-indigo-700 flex items-center gap-1"
            >
              <Plus size={14} /> Add your first source
            </button>
          </div>
        )}
        {!isLoading && !isError && sources.length > 0 && (
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-xs text-slate-500 font-semibold">
                <th className="px-3 py-2.5 w-8" />
                <th className="px-3 py-2.5 text-left">Code</th>
                <th className="px-3 py-2.5 text-left">Type</th>
                <th className="px-3 py-2.5 text-left">State</th>
                <th className="px-3 py-2.5 text-left">Last Run</th>
                <th className="px-3 py-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {sources.map(s => (
                <SourceRow
                  key={s.id}
                  source={s}
                  expanded={expandedSourceId === s.id}
                  expandedPanel={expandedPanel}
                  onToggle={handleToggleRow}
                  onPanelChange={setExpandedPanel}
                  triggeringId={triggeringId}
                  onTrigger={handleTrigger}
                  deletingId={deletingId}
                  onDeleteConfirm={handleDeleteConfirm}
                  onDeleteCancel={() => setDeletingId(null)}
                  onDelete={setDeletingId}
                  onPauseActivate={handlePauseActivate}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Register modal */}
      {showRegisterModal && (
        <RegisterSourceModal
          onClose={() => setShowRegisterModal(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  );
}
