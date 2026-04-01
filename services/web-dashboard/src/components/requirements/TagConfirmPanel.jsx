import { useState, useEffect } from 'react';
import { CheckCircle, Plus, X, Loader2, AlertCircle } from 'lucide-react';
import { API } from '../../api.js';

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
        setSelected(tags);
      } catch {
        setError('Failed to load suggested tags');
      } finally {
        setLoading(false);
      }
    })();
  }, [integrationId]);

  const toggleTag = (tag) =>
    setSelected(prev =>
      prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]
    );

  const addCustom = () => {
    const t = custom.trim();
    if (t && !selected.includes(t)) {
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
          Suggested tags — select any
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
          className="flex-1 text-sm px-3 py-1.5 border border-slate-300 rounded-lg outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100"
        />
        <button
          onClick={addCustom}
          disabled={!custom.trim()}
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

export default TagConfirmPanel;
