import { useState, useEffect, useRef } from 'react';
import { Upload, CheckCircle, XCircle, Tags, Plus, X, Loader2, FileText, AlertCircle } from 'lucide-react';
import Badge from '../ui/Badge.jsx';
import { API } from '../../api.js';

const MAX_TAGS = 3;

const STATUS_MAP = {
  APPROVED:           { variant: 'success', label: 'Approved' },
  PENDING_APPROVAL:   { variant: 'warning', label: 'Pending Approval' },
  PENDING_TAG_REVIEW: { variant: 'info',    label: 'Pending Tags' },
  REJECTED:           { variant: 'error',   label: 'Rejected' },
  GENERATED:          { variant: 'primary', label: 'Generated' },
};

function TagChip({ tag, selected, onToggle }) {
  return (
    <button
      onClick={() => onToggle(tag)}
      className={`px-3 py-1 rounded-full text-xs font-medium border transition-all ${
        selected
          ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm'
          : 'bg-white text-slate-600 border-slate-300 hover:border-indigo-400 hover:text-indigo-600'
      }`}
    >
      {tag}
    </button>
  );
}

function TagConfirmPanel({ integrationId, onConfirmed }) {
  const [suggested, setSuggested] = useState([]);
  const [selected, setSelected]   = useState([]);
  const [custom, setCustom]       = useState('');
  const [loading, setLoading]     = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [error, setError]         = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const res  = await API.catalog.suggestTags(integrationId);
        const data = await res.json();
        const tags = data.suggested_tags || [];
        setSuggested(tags);
        setSelected(tags.slice(0, MAX_TAGS));
      } catch {
        setError('Failed to load suggested tags');
      } finally {
        setLoading(false);
      }
    })();
  }, [integrationId]);

  const toggleTag = (tag) =>
    setSelected(prev =>
      prev.includes(tag)
        ? prev.filter(t => t !== tag)
        : prev.length < MAX_TAGS ? [...prev, tag] : prev
    );

  const addCustom = () => {
    const t = custom.trim();
    if (t && !selected.includes(t) && selected.length < MAX_TAGS) {
      setSelected(prev => [...prev, t]);
      setCustom('');
    }
  };

  const confirm = async () => {
    setConfirming(true);
    setError(null);
    try {
      const res = await API.catalog.confirmTags(integrationId, selected);
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        // Pydantic 422 returns detail as an array of {loc, msg, type} objects
        const msg = Array.isArray(d.detail)
          ? d.detail.map(e => e.msg || JSON.stringify(e)).join('; ')
          : (d.detail || `Server error ${res.status}`);
        throw new Error(msg);
      }
      onConfirmed(integrationId);
    } catch (e) {
      setError(e.message || 'Failed to confirm tags');
    } finally {
      setConfirming(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-slate-500 py-3">
        <Loader2 size={14} className="animate-spin" />
        <span className="text-sm">Loading suggested tags…</span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error && (
        <div className="flex items-center gap-2 text-rose-600 text-sm bg-rose-50 px-3 py-2 rounded-lg">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      <div>
        <p className="text-xs text-slate-500 mb-2 font-medium">
          Suggested tags — select up to {MAX_TAGS}
        </p>
        <div className="flex flex-wrap gap-2">
          {suggested.map(tag => (
            <TagChip key={tag} tag={tag} selected={selected.includes(tag)} onToggle={toggleTag} />
          ))}
          {suggested.length === 0 && (
            <span className="text-xs text-amber-600 bg-amber-50 px-2 py-1 rounded">
              No suggestions — re-upload your CSV so the backend can analyse requirements, or type custom tags below.
            </span>
          )}
        </div>
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          placeholder="Add custom tag…"
          value={custom}
          onChange={e => setCustom(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && addCustom()}
          disabled={selected.length >= MAX_TAGS}
          className="flex-1 text-sm px-3 py-1.5 border border-slate-300 rounded-lg outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100 disabled:opacity-50"
        />
        <button
          onClick={addCustom}
          disabled={!custom.trim() || selected.length >= MAX_TAGS}
          className="p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-600 disabled:opacity-40 transition-colors"
        >
          <Plus size={16} />
        </button>
      </div>

      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5 items-center">
          <span className="text-xs text-slate-500 font-medium">Selected:</span>
          {selected.map(tag => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded-full text-xs font-medium"
            >
              {tag}
              <button
                onClick={() => setSelected(s => s.filter(t => t !== tag))}
                className="hover:text-indigo-900 transition-colors"
              >
                <X size={10} />
              </button>
            </span>
          ))}
        </div>
      )}

      <button
        onClick={confirm}
        disabled={selected.length === 0 || confirming}
        className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
      >
        {confirming ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
        Confirm Tags
      </button>
    </div>
  );
}

export default function RequirementsPage() {
  const [requirements, setRequirements] = useState([]);
  const [pendingTags, setPendingTags]   = useState([]);
  const [confirmedIds, setConfirmedIds] = useState(new Set());
  const [uploading, setUploading]       = useState(false);
  const [dragOver, setDragOver]         = useState(false);
  const [error, setError]               = useState(null);
  const fileInputRef = useRef(null);

  // Load existing data on mount and after each successful upload
  useEffect(() => { loadData(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleFile = async (file) => {
    const lowerName = file?.name?.toLowerCase() ?? '';
    if (!lowerName.endsWith('.csv')) {
      setError('Please upload a CSV file (.csv)');
      return;
    }
    setError(null);
    setUploading(true);
    try {
      const res = await API.requirements.upload(file);
      if (!res.ok) throw new Error('Upload failed');
      await loadData();
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  };

  const loadData = async () => {
    try {
      const [reqRes, catRes] = await Promise.all([
        API.requirements.list(),
        API.catalog.list(),
      ]);
      const reqs = await reqRes.json();
      // Backend returns { status, data: [...] }
      setRequirements(reqs.data || []);
      const cats = await catRes.json();
      // Backend returns { status, data: [...] }
      setPendingTags((cats.data || []).filter(i => i.status === 'PENDING_TAG_REVIEW'));
    } catch (e) {
      setError(`Could not load data: ${e.message}`);
    }
  };

  const onTagConfirmed = (id) =>
    setConfirmedIds(prev => new Set([...prev, id]));

  const pendingTagsList  = pendingTags.filter(p => !confirmedIds.has(p.id));
  const allTagsConfirmed = pendingTags.length > 0 && pendingTagsList.length === 0;

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Upload zone */}
      <div
        onDragOver={e => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]); }}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-2xl p-10 text-center transition-all cursor-pointer select-none ${
          dragOver
            ? 'border-indigo-400 bg-indigo-50'
            : 'border-slate-300 hover:border-indigo-300 hover:bg-slate-50/80'
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv"
          className="hidden"
          onChange={e => handleFile(e.target.files[0])}
        />
        {uploading ? (
          <div className="flex flex-col items-center gap-3 text-indigo-600">
            <Loader2 size={32} className="animate-spin" />
            <p className="font-medium" style={{ fontFamily: 'Outfit, sans-serif' }}>
              Uploading and parsing…
            </p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3">
            <div className="w-14 h-14 rounded-full bg-indigo-50 border border-indigo-100 flex items-center justify-center">
              <Upload size={24} className="text-indigo-500" />
            </div>
            <div>
              <p className="font-semibold text-slate-700" style={{ fontFamily: 'Outfit, sans-serif' }}>
                Drop your CSV file here
              </p>
              <p className="text-sm text-slate-400 mt-1">or click to browse — accepts .csv files</p>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-4 py-3 text-sm">
          <XCircle size={16} /> {error}
        </div>
      )}

      {/* Requirements table */}
      {requirements.length > 0 && (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
            <FileText size={15} className="text-slate-400" />
            <h2
              className="font-semibold text-slate-900"
              style={{ fontFamily: 'Outfit, sans-serif' }}
            >
              Parsed Requirements
            </h2>
            <Badge variant="slate">{requirements.length}</Badge>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr>
                  {['Req ID', 'Description', 'Source', 'Target', 'Category', 'Status'].map(h => (
                    <th
                      key={h}
                      className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {requirements.map((req, i) => (
                  <tr key={i} className="hover:bg-slate-50/70 transition-colors">
                    {/* field names match Requirement schema: req_id, source_system, target_system, category, description */}
                    <td className="px-4 py-3 font-mono text-xs text-slate-400">{req.req_id || '—'}</td>
                    <td className="px-4 py-3 font-medium text-slate-900 max-w-xs truncate" title={req.description}>{req.description || '—'}</td>
                    <td className="px-4 py-3 text-slate-600">{req.source_system || '—'}</td>
                    <td className="px-4 py-3 text-slate-600">{req.target_system || '—'}</td>
                    <td className="px-4 py-3 text-slate-600">{req.category || '—'}</td>
                    <td className="px-4 py-3">
                      <Badge variant="primary" dot>Parsed</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tag confirmation panel */}
      {pendingTags.length > 0 && (
        <div className="bg-white rounded-2xl border border-indigo-200 shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-indigo-100 bg-indigo-50/40 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Tags size={15} className="text-indigo-600" />
              <h2 className="font-semibold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                Tag Confirmation
              </h2>
              <Badge variant="info">{pendingTagsList.length} pending</Badge>
            </div>
            {allTagsConfirmed && (
              <div className="flex items-center gap-1.5 text-emerald-600 text-sm font-medium">
                <CheckCircle size={15} />
                All confirmed — ready to run agent!
              </div>
            )}
          </div>

          <div className="divide-y divide-slate-100">
            {pendingTags.map(integration => {
              const confirmed = confirmedIds.has(integration.id);
              return (
                <div key={integration.id} className={`px-5 py-4 transition-opacity ${confirmed ? 'opacity-50' : ''}`}>
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <p className="font-semibold text-slate-900">{integration.name}</p>
                      <p className="text-xs font-mono text-slate-400 mt-0.5">{integration.id}</p>
                    </div>
                    {confirmed && (
                      <div className="flex items-center gap-1.5 text-emerald-600 text-xs font-semibold">
                        <CheckCircle size={14} /> Tags confirmed
                      </div>
                    )}
                  </div>
                  {!confirmed && (
                    <TagConfirmPanel
                      integrationId={integration.id}
                      onConfirmed={onTagConfirmed}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
