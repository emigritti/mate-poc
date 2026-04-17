import { useState, useEffect } from 'react';
import { SlidersHorizontal, RotateCcw, Save, AlertCircle, CheckCircle2, Loader2, Info } from 'lucide-react';
import { API } from '../../api.js';

// ── Unified field metadata (same for all 3 profiles) ──────────────────────────
const MODEL_FIELDS = [
  { key: 'model',           label: 'Model',             type: 'text',   unit: '',    hint: 'Ollama model name (e.g. qwen2.5:14b)' },
  { key: 'num_predict',     label: 'Max Tokens',        type: 'number', unit: 'tok', hint: 'Token cap for generation' },
  { key: 'timeout_seconds', label: 'Timeout',           type: 'number', unit: 's',   hint: 'HTTP timeout for Ollama calls' },
  { key: 'temperature',     label: 'Temperature',       type: 'number', unit: '',    step: 0.01, hint: '0 = deterministic, 1 = creative' },
  { key: 'rag_max_chars',   label: 'RAG Context Limit', type: 'number', unit: 'ch',  hint: 'Max characters of retrieved context injected into prompt' },
  { key: 'num_ctx',         label: 'Context Window',    type: 'number', unit: 'tok', hint: 'Ollama context window size (num_ctx)' },
  { key: 'top_p',           label: 'Top-P',             type: 'number', unit: '',    step: 0.01, hint: 'Nucleus sampling threshold' },
  { key: 'top_k',           label: 'Top-K',             type: 'number', unit: '',    hint: 'Top-K sampling tokens' },
  { key: 'repeat_penalty',  label: 'Repeat Penalty',    type: 'number', unit: '',    step: 0.01, hint: 'Penalizes token repetition' },
];

const PROFILES = [
  { groupKey: 'doc_llm',     title: 'Default Profile',      subtitle: 'Standard document generation' },
  { groupKey: 'premium_llm', title: 'Premium Profile',      subtitle: 'High-quality complex integrations' },
  { groupKey: 'tag_llm',     title: 'Fast-Utility Profile', subtitle: 'Tag suggestion & query expansion' },
];

function FieldRow({ fieldMeta, effectiveVal, defaultVal, groupKey, onUpdate }) {
  const isOverridden = effectiveVal !== defaultVal;
  const { key, label, type, unit, step, hint } = fieldMeta;

  return (
    <div className="flex items-start gap-4 py-3 border-b border-slate-100 last:border-0">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-700">{label}</span>
          {unit && (
            <span className="text-[10px] text-slate-400 font-mono bg-slate-100 px-1.5 py-0.5 rounded">
              {unit}
            </span>
          )}
          {isOverridden && (
            <span className="text-[10px] font-bold text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-200">
              MODIFIED
            </span>
          )}
        </div>
        <p className="text-xs text-slate-400 mt-0.5">{hint}</p>
        {isOverridden && (
          <p className="text-[10px] text-slate-400 mt-0.5 font-mono">default: {String(defaultVal)}</p>
        )}
      </div>
      <input
        type={type}
        step={step ?? (type === 'number' ? 1 : undefined)}
        value={effectiveVal}
        onChange={e => {
          const raw = e.target.value;
          const val = type === 'number'
            ? (raw.includes('.') ? parseFloat(raw) : parseInt(raw, 10))
            : raw;
          onUpdate(groupKey, key, val);
        }}
        className={`w-36 text-sm px-3 py-1.5 rounded-lg border transition-colors font-mono ${
          isOverridden
            ? 'border-amber-300 bg-amber-50 focus:border-amber-400'
            : 'border-slate-200 bg-white focus:border-indigo-400'
        } focus:outline-none focus:ring-2 focus:ring-indigo-100`}
      />
    </div>
  );
}

function SettingsCard({ title, subtitle, fields, effective, defaults, groupKey, onUpdate }) {
  const overrideCount = fields.filter(({ key }) => effective[key] !== defaults[key]).length;

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
      <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50 flex items-center gap-2">
        <SlidersHorizontal size={14} className="text-slate-400" />
        <div className="flex-1 min-w-0">
          <span
            className="text-sm font-semibold text-slate-700 block"
            style={{ fontFamily: 'Outfit, sans-serif' }}
          >
            {title}
          </span>
          {subtitle && (
            <span className="text-[11px] text-slate-400">{subtitle}</span>
          )}
        </div>
        {overrideCount > 0 && (
          <span className="ml-auto text-[10px] font-bold text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-200">
            {overrideCount} override{overrideCount > 1 ? 's' : ''} active
          </span>
        )}
      </div>
      <div className="px-5">
        {fields.map(f => (
          <FieldRow
            key={f.key}
            fieldMeta={f}
            effectiveVal={effective[f.key]}
            defaultVal={defaults[f.key]}
            groupKey={groupKey}
            onUpdate={onUpdate}
          />
        ))}
      </div>
    </div>
  );
}

export default function LlmSettingsPage() {
  const [data,      setData]      = useState(null);
  const [draft,     setDraft]     = useState(null);
  const [loading,   setLoading]   = useState(true);
  const [saving,    setSaving]    = useState(false);
  const [resetting, setResetting] = useState(false);
  const [feedback,  setFeedback]  = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await API.llmSettings.get();
      const d   = await res.json();
      if (!res.ok) throw new Error(d.detail || `Error ${res.status}`);
      setData(d.data);
      setDraft(structuredClone(d.data.effective));
    } catch (e) {
      setFeedback({ type: 'error', msg: e.message || 'Failed to load settings' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const updateDraft = (group, key, val) => {
    setDraft(prev => ({ ...prev, [group]: { ...prev[group], [key]: val } }));
  };

  const save = async () => {
    setSaving(true);
    setFeedback(null);
    try {
      const body = {};
      for (const { groupKey } of PROFILES) {
        const changes = {};
        MODEL_FIELDS.forEach(({ key }) => {
          if (draft[groupKey][key] !== data.defaults[groupKey][key]) {
            changes[key] = draft[groupKey][key];
          }
        });
        if (Object.keys(changes).length) body[groupKey] = changes;
      }

      const res = await API.llmSettings.patch(body);
      const d   = await res.json();
      if (!res.ok) throw new Error(d.detail || `Error ${res.status}`);
      setData(d.data);
      setDraft(structuredClone(d.data.effective));
      setFeedback({ type: 'success', msg: 'Settings saved and applied immediately.' });
    } catch (e) {
      setFeedback({ type: 'error', msg: e.message || 'Save failed' });
    } finally {
      setSaving(false);
    }
  };

  const resetAll = async () => {
    setResetting(true);
    setFeedback(null);
    try {
      const res = await API.llmSettings.reset();
      const d   = await res.json();
      if (!res.ok) throw new Error(d.detail || `Error ${res.status}`);
      setData(d.data);
      setDraft(structuredClone(d.data.effective));
      setFeedback({ type: 'success', msg: 'Reset to design defaults.' });
    } catch (e) {
      setFeedback({ type: 'error', msg: e.message || 'Reset failed' });
    } finally {
      setResetting(false);
    }
  };

  const isDirty = draft && data && PROFILES.some(({ groupKey }) =>
    MODEL_FIELDS.some(({ key }) => draft[groupKey][key] !== data.effective[groupKey][key])
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={24} className="animate-spin text-indigo-400" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-5">

      {/* Info banner */}
      <div className="flex items-start gap-3 px-4 py-3 bg-indigo-50 border border-indigo-200 rounded-xl text-sm text-indigo-700">
        <Info size={15} className="flex-shrink-0 mt-0.5" />
        <span>
          Changes apply <strong>immediately</strong> without restart and are persisted in MongoDB.
          Full Reset restores the values configured at design time (env vars / pydantic defaults).
        </span>
      </div>

      {/* Feedback */}
      {feedback && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-xl text-sm border ${
          feedback.type === 'success'
            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
            : 'bg-rose-50 border-rose-200 text-rose-700'
        }`}>
          {feedback.type === 'success'
            ? <CheckCircle2 size={15} />
            : <AlertCircle size={15} />}
          {feedback.msg}
        </div>
      )}

      {/* Settings cards — one per profile */}
      {draft && data && PROFILES.map(({ groupKey, title, subtitle }) => (
        <SettingsCard
          key={groupKey}
          title={title}
          subtitle={subtitle}
          fields={MODEL_FIELDS}
          effective={draft[groupKey]}
          defaults={data.defaults[groupKey]}
          groupKey={groupKey}
          onUpdate={updateDraft}
        />
      ))}

      {/* Action buttons */}
      <div className="flex items-center justify-between pt-2">
        <button
          onClick={resetAll}
          disabled={resetting || (!data?.overrides_active && !isDirty)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-slate-600 border border-slate-200 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {resetting ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
          Reset to Defaults
        </button>

        <button
          onClick={save}
          disabled={saving || !isDirty}
          className="flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm shadow-indigo-200"
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          Save Changes
        </button>
      </div>

    </div>
  );
}
