import { useState, useEffect } from 'react';
import { Settings2, RotateCcw, Save, AlertCircle, CheckCircle2, Loader2, Info } from 'lucide-react';
import { API } from '../../api.js';
import { SkeletonTable } from '../ui/SkeletonTable.jsx';

// ── Setting groups & field metadata ───────────────────────────────────────────

const SETTING_GROUPS = [
  {
    groupKey: 'quality_gate',
    title: 'Quality Gate',
    subtitle: 'Document quality thresholds before HITL review',
    fields: [
      {
        key: 'quality_gate_mode',
        label: 'Gate Mode',
        type: 'select',
        options: ['warn', 'block'],
        hint: '"block" stops low-quality documents before HITL; "warn" logs and forwards them anyway',
      },
      {
        key: 'quality_gate_min_score',
        label: 'Min Quality Score',
        type: 'number',
        unit: '0–1',
        step: 0.01,
        hint: 'Documents scoring below this threshold trigger the gate (0 = disabled, 1 = strict)',
      },
    ],
  },
  {
    groupKey: 'rag',
    title: 'RAG & Retrieval',
    subtitle: 'Knowledge base search, ranking, and context assembly',
    fields: [
      {
        key: 'rag_distance_threshold',
        label: 'Distance Threshold',
        type: 'number',
        unit: '',
        step: 0.01,
        hint: 'Max ChromaDB L2 distance to keep a chunk (0 = perfect match, 2 = worst). Lower = stricter filtering.',
      },
      {
        key: 'rag_bm25_weight',
        label: 'BM25 Weight',
        type: 'number',
        unit: '',
        step: 0.01,
        hint: 'Ensemble weight for keyword search (BM25). ChromaDB dense weight = 1 − this value.',
      },
      {
        key: 'rag_n_results_per_query',
        label: 'Results per Query Variant',
        type: 'number',
        unit: 'chunks',
        hint: 'ChromaDB candidates fetched per query variant (4 variants × N = total candidates before re-ranking)',
      },
      {
        key: 'rag_top_k_chunks',
        label: 'Top-K Final Chunks',
        type: 'number',
        unit: 'chunks',
        hint: 'Final chunks passed to the context assembler after re-ranking. Higher = richer context, slower.',
      },
      {
        key: 'kb_max_rag_chars',
        label: 'Max KB Context',
        type: 'number',
        unit: 'ch',
        hint: 'Max characters of KB content injected into the generation prompt',
      },
    ],
  },
  {
    groupKey: 'generation',
    title: 'Document Generation',
    subtitle: 'FactPack two-step pipeline and output safety limits',
    fields: [
      {
        key: 'fact_pack_enabled',
        label: 'FactPack Pipeline',
        type: 'bool',
        hint: 'Use two-step evidence extraction before document rendering. Disable to always use single-pass fallback.',
      },
      {
        key: 'fact_pack_max_tokens',
        label: 'FactPack Max Tokens',
        type: 'number',
        unit: 'tok',
        hint: 'Token budget for the FactPack extraction LLM call (JSON output with all 11 evidence fields)',
      },
      {
        key: 'llm_max_output_chars',
        label: 'Max Output Length',
        type: 'number',
        unit: 'ch',
        hint: 'Safety cap on generated document length. Content beyond this limit is rejected by the output guard.',
      },
    ],
  },
  {
    groupKey: 'vision_rag',
    title: 'Vision & Summarization',
    subtitle: 'Advanced RAG — image captioning and RAPTOR-lite section summaries',
    fields: [
      {
        key: 'vision_captioning_enabled',
        label: 'Vision Captioning',
        type: 'bool',
        hint: 'Enable LLaVA image captioning during KB upload. Disable if no GPU is available to avoid slow uploads.',
      },
      {
        key: 'raptor_summarization_enabled',
        label: 'RAPTOR Summaries',
        type: 'bool',
        hint: 'Generate section-level LLM summaries at upload time for hierarchical retrieval (ADR-032).',
      },
      {
        key: 'kb_max_summarize_sections',
        label: 'Max Sections to Summarize',
        type: 'number',
        unit: '',
        hint: 'Safety cap on LLM summarization calls per KB document upload. Higher = richer summaries, slower uploads.',
      },
    ],
  },
  {
    groupKey: 'kb_chunking',
    title: 'KB Chunking',
    subtitle: 'Text segmentation parameters applied on next KB document upload',
    fields: [
      {
        key: 'kb_chunk_size',
        label: 'Chunk Size',
        type: 'number',
        unit: 'ch',
        hint: 'Target characters per chunk during KB ingestion. Smaller = more granular retrieval.',
      },
      {
        key: 'kb_chunk_overlap',
        label: 'Chunk Overlap',
        type: 'number',
        unit: 'ch',
        hint: 'Overlap between adjacent chunks to preserve context across boundaries.',
      },
    ],
  },
];

// Flat list of all keys, for diffing
const ALL_KEYS = SETTING_GROUPS.flatMap(g => g.fields.map(f => f.key));


// ── Field components ──────────────────────────────────────────────────────────

function BoolToggle({ value, onChange, disabled }) {
  return (
    <button
      type="button"
      onClick={() => !disabled && onChange(!value)}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-300 ${
        value ? 'bg-indigo-600' : 'bg-slate-300'
      } ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${
          value ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </button>
  );
}

function FieldRow({ fieldMeta, effectiveVal, defaultVal, onUpdate }) {
  const isOverridden = effectiveVal !== defaultVal;
  const { key, label, type, unit, step, hint, options } = fieldMeta;

  return (
    <div className="flex items-start gap-4 py-3 border-b border-slate-100 last:border-0">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
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
        <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">{hint}</p>
        {isOverridden && (
          <p className="text-[10px] text-slate-400 mt-0.5 font-mono">
            default: {String(defaultVal)}
          </p>
        )}
      </div>

      {type === 'bool' && (
        <div className="flex-shrink-0 pt-0.5">
          <BoolToggle value={effectiveVal} onChange={v => onUpdate(key, v)} />
        </div>
      )}

      {type === 'select' && (
        <select
          value={effectiveVal}
          onChange={e => onUpdate(key, e.target.value)}
          className={`w-28 text-sm px-3 py-1.5 rounded-lg border transition-colors font-mono ${
            isOverridden
              ? 'border-amber-300 bg-amber-50 focus:border-amber-400'
              : 'border-slate-200 bg-white focus:border-indigo-400'
          } focus:outline-none focus:ring-2 focus:ring-indigo-100`}
        >
          {options.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      )}

      {type === 'number' && (
        <input
          type="number"
          step={step ?? 1}
          value={effectiveVal}
          onChange={e => {
            const raw = e.target.value;
            const val = raw.includes('.') ? parseFloat(raw) : parseInt(raw, 10);
            onUpdate(key, val);
          }}
          className={`w-32 text-sm px-3 py-1.5 rounded-lg border transition-colors font-mono ${
            isOverridden
              ? 'border-amber-300 bg-amber-50 focus:border-amber-400'
              : 'border-slate-200 bg-white focus:border-indigo-400'
          } focus:outline-none focus:ring-2 focus:ring-indigo-100`}
        />
      )}
    </div>
  );
}

function SettingsCard({ groupKey, title, subtitle, fields, effective, defaults, onUpdate }) {
  const overrideCount = fields.filter(f => effective[f.key] !== defaults[f.key]).length;

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
      <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50 flex items-center gap-2">
        <Settings2 size={14} className="text-slate-400 flex-shrink-0" />
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
        {fields.map(f => (
          <FieldRow
            key={f.key}
            fieldMeta={f}
            effectiveVal={effective[f.key]}
            defaultVal={defaults[f.key]}
            onUpdate={onUpdate}
          />
        ))}
      </div>
    </div>
  );
}


// ── Page ──────────────────────────────────────────────────────────────────────

export default function AgentSettingsPage() {
  const [data,      setData]      = useState(null);
  const [draft,     setDraft]     = useState(null);
  const [loading,   setLoading]   = useState(true);
  const [saving,    setSaving]    = useState(false);
  const [resetting, setResetting] = useState(false);
  const [feedback,  setFeedback]  = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await API.agentSettings.get();
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

  const updateDraft = (key, val) => {
    setDraft(prev => ({ ...prev, [key]: val }));
  };

  const save = async () => {
    setSaving(true);
    setFeedback(null);
    try {
      // Send only fields that differ from design defaults
      const body = {};
      ALL_KEYS.forEach(key => {
        if (draft[key] !== data.defaults[key]) body[key] = draft[key];
      });

      const res = await API.agentSettings.patch(body);
      const d   = await res.json();
      if (!res.ok) throw new Error(d.detail || `Error ${res.status}`);
      setData(d.data);
      setDraft(structuredClone(d.data.effective));
      setFeedback({ type: 'success', msg: 'Settings saved — active on next agent run.' });
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
      const res = await API.agentSettings.reset();
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

  const isDirty = draft && data && ALL_KEYS.some(k => draft[k] !== data.effective[k]);

  if (loading) {
    return (
      <div className="max-w-3xl space-y-5">
        <SkeletonTable rows={6} cols={2} />
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-5">

      {/* Info banner */}
      <div className="flex items-start gap-3 px-4 py-3 bg-indigo-50 border border-indigo-200 rounded-xl text-sm text-indigo-700">
        <Info size={15} className="flex-shrink-0 mt-0.5" />
        <span>
          Settings are <strong>persisted to MongoDB</strong> and survive container restarts.
          Changes take effect on the <strong>next agent run</strong> — no restart required.
          Reset restores the values configured at deploy time (env vars / pydantic defaults).
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

      {/* Settings cards — one per group */}
      {draft && data && SETTING_GROUPS.map(({ groupKey, title, subtitle, fields }) => (
        <SettingsCard
          key={groupKey}
          groupKey={groupKey}
          title={title}
          subtitle={subtitle}
          fields={fields}
          effective={draft}
          defaults={data.defaults}
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
