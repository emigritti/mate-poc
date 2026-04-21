import { useState, useEffect } from 'react';
import { SlidersHorizontal, RotateCcw, Save, AlertCircle, CheckCircle2, Loader2, Info, Zap } from 'lucide-react';
import { API } from '../../api.js';

const MODEL_FIELDS = [
  { key: 'model',           label: 'Model',             type: 'text',   unit: '',    hint: 'Model name — Ollama: e.g. qwen2.5:14b · Gemini: e.g. gemini-2.0-flash' },
  { key: 'num_predict',     label: 'Max Tokens',        type: 'number', unit: 'tok', hint: 'Token cap for generation — set to 3000–5000 for full Integration Specs' },
  { key: 'timeout_seconds', label: 'Timeout',           type: 'number', unit: 's',   hint: 'HTTP timeout for LLM calls — increase for large models on CPU' },
  { key: 'temperature',     label: 'Temperature',       type: 'number', unit: '',    step: 0.01, hint: '0 = deterministic, 1 = creative' },
  { key: 'rag_max_chars',   label: 'RAG Context Limit', type: 'number', unit: 'ch',  hint: 'Max characters of retrieved context injected into prompt' },
  { key: 'num_ctx',         label: 'Context Window',    type: 'number', unit: 'tok', hint: 'Ollama context window size (ignored by Gemini)' },
  { key: 'top_p',           label: 'Top-P',             type: 'number', unit: '',    step: 0.01, hint: 'Nucleus sampling (Ollama only — ignored by Gemini)' },
  { key: 'top_k',           label: 'Top-K',             type: 'number', unit: '',    hint: 'Top-K sampling (Ollama only — ignored by Gemini)' },
  { key: 'repeat_penalty',  label: 'Repeat Penalty',    type: 'number', unit: '',    step: 0.01, hint: 'Penalizes repeated tokens (Ollama only — ignored by Gemini)' },
];

// groupKey mapping for the two main modes
const MAIN_PROFILES = {
  standard:    { groupKey: 'doc_llm',     label: 'Standard',    subtitle: 'Document generation, FactPack extraction, RAG' },
  high_quality: { groupKey: 'premium_llm', label: 'High Quality', subtitle: 'Complex integrations — larger model, slower' },
};

const TAG_PROFILE = { groupKey: 'tag_llm', title: 'Fast-Utility', subtitle: 'Tag suggestion & query expansion only' };

const PROVIDER_OPTIONS = [
  { value: 'ollama', label: 'Ollama (local)' },
  { value: 'gemini', label: 'Google Gemini API' },
];


function ProviderRow({ effectiveVal, defaultVal, groupKey, onUpdate }) {
  const isOverridden = effectiveVal !== defaultVal;
  return (
    <div className="flex items-start gap-4 py-3 border-b border-slate-100">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-700">Provider</span>
          {isOverridden && (
            <span className="text-[10px] font-bold text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-200">
              MODIFIED
            </span>
          )}
        </div>
        <p className="text-xs text-slate-400 mt-0.5">LLM backend — Ollama (local) or Google Gemini API (requires GEMINI_API_KEY in .env)</p>
        {isOverridden && (
          <p className="text-[10px] text-slate-400 mt-0.5 font-mono">default: {defaultVal}</p>
        )}
      </div>
      <select
        value={effectiveVal}
        onChange={e => onUpdate(groupKey, 'provider', e.target.value)}
        className={`w-36 text-sm px-3 py-1.5 rounded-lg border transition-colors ${
          isOverridden
            ? 'border-amber-300 bg-amber-50 focus:border-amber-400'
            : 'border-slate-200 bg-white focus:border-indigo-400'
        } focus:outline-none focus:ring-2 focus:ring-indigo-100`}
      >
        {PROVIDER_OPTIONS.map(opt => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    </div>
  );
}


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

function SettingsCard({ title, subtitle, fields, effective, defaults, groupKey, onUpdate, compact = false }) {
  const overrideCount = [
    effective.provider !== defaults.provider ? 1 : 0,
    ...fields.map(({ key }) => effective[key] !== defaults[key] ? 1 : 0),
  ].reduce((a, b) => a + b, 0);

  const isGemini = effective.provider === 'gemini';

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
      <div className={`px-5 border-b border-slate-100 bg-slate-50 flex items-center gap-2 ${compact ? 'py-2.5' : 'py-3.5'}`}>
        {compact
          ? <Zap size={13} className="text-slate-400 flex-shrink-0" />
          : <SlidersHorizontal size={14} className="text-slate-400 flex-shrink-0" />}
        <div className="flex-1 min-w-0">
          <span className="text-sm font-semibold text-slate-700 block" style={{ fontFamily: 'Outfit, sans-serif' }}>
            {title}
          </span>
          {subtitle && <span className="text-[11px] text-slate-400">{subtitle}</span>}
        </div>
        {overrideCount > 0 && (
          <span className="ml-auto text-[10px] font-bold text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-200 flex-shrink-0">
            {overrideCount} override{overrideCount > 1 ? 's' : ''} active
          </span>
        )}
      </div>
      <div className="px-5">
        <ProviderRow
          effectiveVal={effective.provider}
          defaultVal={defaults.provider}
          groupKey={groupKey}
          onUpdate={onUpdate}
        />
        {isGemini && (
          <div className="flex items-center gap-2 py-2 text-xs text-indigo-600 bg-indigo-50 -mx-5 px-5 border-b border-indigo-100">
            <Info size={12} className="flex-shrink-0" />
            Gemini ignores Context Window, Top-K, Top-P and Repeat Penalty — only Model, Max Tokens, Timeout and Temperature apply.
          </div>
        )}
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
  const [data,         setData]         = useState(null);
  const [draft,        setDraft]        = useState(null);
  const [activeMode,   setActiveMode]   = useState('standard');
  const [loading,      setLoading]      = useState(true);
  const [saving,       setSaving]       = useState(false);
  const [resetting,    setResetting]    = useState(false);
  const [feedback,     setFeedback]     = useState(null);

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
      const allGroups = [...Object.values(MAIN_PROFILES).map(p => p.groupKey), TAG_PROFILE.groupKey];
      for (const groupKey of allGroups) {
        const changes = {};
        // Check provider override
        if (draft[groupKey].provider !== data.defaults[groupKey].provider) {
          changes.provider = draft[groupKey].provider;
        }
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

  const allGroups = draft && data
    ? [...Object.values(MAIN_PROFILES).map(p => p.groupKey), TAG_PROFILE.groupKey]
    : [];
  const isDirty = allGroups.some(gk => {
    if (!draft || !data) return false;
    if (draft[gk].provider !== data.effective[gk].provider) return true;
    return MODEL_FIELDS.some(({ key }) => draft[gk][key] !== data.effective[gk][key]);
  });

  const { groupKey: activeGroupKey, label: activeLabel, subtitle: activeSubtitle } = MAIN_PROFILES[activeMode];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={24} className="animate-spin text-indigo-400" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-5">

      {/* Mode toggle */}
      <div className="flex items-center gap-2">
        {Object.entries(MAIN_PROFILES).map(([mode, { label }]) => {
          const active = activeMode === mode;
          const gk = MAIN_PROFILES[mode].groupKey;
          const hasOverride = draft && data && (
            draft[gk].provider !== data.defaults[gk].provider ||
            MODEL_FIELDS.some(({ key }) => draft[gk][key] !== data.defaults[gk][key])
          );
          return (
            <button
              key={mode}
              onClick={() => setActiveMode(mode)}
              className={`relative flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-semibold transition-all ${
                active
                  ? 'bg-indigo-600 text-white shadow-md shadow-indigo-200'
                  : 'bg-white text-slate-500 border border-slate-200 hover:border-slate-300 hover:text-slate-700'
              }`}
            >
              {label}
              {hasOverride && !active && (
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0" />
              )}
            </button>
          );
        })}
        <span className="ml-2 text-xs text-slate-400">
          Toggle to configure parameters per quality level
        </span>
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-3 px-4 py-3 bg-indigo-50 border border-indigo-200 rounded-xl text-sm text-indigo-700">
        <Info size={15} className="flex-shrink-0 mt-0.5" />
        <span>
          Changes apply <strong>immediately</strong> without restart and persist in MongoDB.
          <strong> Standard</strong> is used for all document generation and FactPack extraction.
          <strong> High Quality</strong> is selected per-run from the Agent Workspace.
          Set <strong>GEMINI_API_KEY</strong> in <code>.env</code> to enable the Gemini provider.
          Reset restores env-var / pydantic defaults.
        </span>
      </div>

      {/* Feedback */}
      {feedback && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-xl text-sm border ${
          feedback.type === 'success'
            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
            : 'bg-rose-50 border-rose-200 text-rose-700'
        }`}>
          {feedback.type === 'success' ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
          {feedback.msg}
        </div>
      )}

      {/* Active profile card */}
      {draft && data && (
        <SettingsCard
          title={activeLabel}
          subtitle={activeSubtitle}
          fields={MODEL_FIELDS}
          effective={draft[activeGroupKey]}
          defaults={data.defaults[activeGroupKey]}
          groupKey={activeGroupKey}
          onUpdate={updateDraft}
        />
      )}

      {/* Fast-Utility — compact, always visible */}
      {draft && data && (
        <SettingsCard
          title={TAG_PROFILE.title}
          subtitle={TAG_PROFILE.subtitle}
          fields={MODEL_FIELDS}
          effective={draft[TAG_PROFILE.groupKey]}
          defaults={data.defaults[TAG_PROFILE.groupKey]}
          groupKey={TAG_PROFILE.groupKey}
          onUpdate={updateDraft}
          compact
        />
      )}

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
