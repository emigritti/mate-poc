import { useState, useEffect, useRef } from 'react';
import { FlaskConical, Play, Loader2, CheckCircle, XCircle, BookOpen, BarChart2, History, ChevronDown, ChevronRight, Trash2 } from 'lucide-react';
import { API } from '../../api.js';
import {
  AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogFooter,
  AlertDialogTitle, AlertDialogDescription, AlertDialogAction, AlertDialogCancel,
} from '../ui/alert-dialog.jsx';

// ── Metric thresholds ─────────────────────────────────────────────────────────

const THRESHOLDS = {
  'recall@5':              { good: 0.70, ok: 0.50 },
  'mrr':                   { good: 0.60, ok: 0.40 },
  'ndcg@5':                { good: 0.65, ok: 0.45 },
  'faithfulness_substring':{ good: 0.60, ok: 0.40 },
};

function scoreColor(key, value) {
  const t = THRESHOLDS[key];
  if (!t) return 'text-slate-400';
  if (value >= t.good) return 'text-emerald-400';
  if (value >= t.ok)   return 'text-amber-400';
  return 'text-rose-400';
}

function scoreBar(key, value) {
  const t = THRESHOLDS[key];
  const pct = t ? Math.min(100, Math.round(value * 100)) : Math.min(100, Math.round(value));
  const color = t
    ? value >= t.good ? 'bg-emerald-500' : value >= t.ok ? 'bg-amber-500' : 'bg-rose-500'
    : 'bg-slate-500';
  return (
    <div className="flex items-center gap-2 flex-1">
      <div className="flex-1 bg-slate-700 rounded-full h-1.5">
        <div className={`${color} h-1.5 rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-500 w-8 text-right">{pct}%</span>
    </div>
  );
}

// ── Metric label lookup ────────────────────────────────────────────────────────

const METRIC_LABELS = {
  'recall@5':              'Recall@5',
  'mrr':                   'MRR',
  'ndcg@5':                'NDCG@5',
  'faithfulness_substring':'Faithfulness',
  'latency_p50_ms':        'P50 Latency',
  'latency_p95_ms':        'P95 Latency',
  'n_queries':             'Questions',
};

function fmtValue(key, v) {
  if (key.includes('latency')) return `${Math.round(v)} ms`;
  if (key === 'n_queries') return String(v);
  return typeof v === 'number' ? v.toFixed(3) : String(v);
}

// ── Sub-components ────────────────────────────────────────────────────────────

function MetricsTable({ metrics }) {
  const ordered = ['recall@5', 'mrr', 'ndcg@5', 'faithfulness_substring', 'latency_p50_ms', 'latency_p95_ms', 'n_queries'];
  return (
    <div className="space-y-2">
      {ordered.filter(k => k in metrics).map(k => (
        <div key={k} className="flex items-center gap-3">
          <span className="text-xs text-slate-400 w-36 shrink-0">{METRIC_LABELS[k] || k}</span>
          <span className={`text-sm font-mono font-semibold w-20 shrink-0 ${scoreColor(k, metrics[k])}`}>
            {fmtValue(k, metrics[k])}
          </span>
          {THRESHOLDS[k] && scoreBar(k, metrics[k])}
        </div>
      ))}
    </div>
  );
}

function DeltaCell({ val }) {
  if (val == null) return <span className="text-slate-500">—</span>;
  const sign = val > 0 ? '+' : '';
  const color = val > 0.01 ? 'text-emerald-400' : val < -0.01 ? 'text-rose-400' : 'text-slate-400';
  return <span className={`font-mono text-xs ${color}`}>{sign}{val.toFixed(3)}</span>;
}

function CompareTable({ data }) {
  const ordered = ['recall@5', 'mrr', 'ndcg@5', 'faithfulness_substring', 'latency_p50_ms', 'latency_p95_ms'];
  const rows = ordered.filter(k => k in data.metrics);
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-slate-500 border-b border-slate-700">
          <th className="text-left py-1 pr-3 font-medium">Metric</th>
          <th className="text-right py-1 px-3 font-medium">{data.label_a}</th>
          <th className="text-right py-1 px-3 font-medium">{data.label_b}</th>
          <th className="text-right py-1 pl-3 font-medium">Δ abs</th>
          <th className="text-right py-1 pl-3 font-medium">Δ %</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(k => {
          const m = data.metrics[k];
          return (
            <tr key={k} className="border-b border-slate-800">
              <td className="py-1.5 pr-3 text-slate-300">{METRIC_LABELS[k] || k}</td>
              <td className="py-1.5 px-3 text-right font-mono text-slate-400">{m.a.toFixed(3)}</td>
              <td className={`py-1.5 px-3 text-right font-mono ${scoreColor(k, m.b)}`}>{m.b.toFixed(3)}</td>
              <td className="py-1.5 pl-3 text-right"><DeltaCell val={m.delta} /></td>
              <td className="py-1.5 pl-2 text-right">
                {m.pct != null
                  ? <span className={m.pct > 0 ? 'text-emerald-400' : m.pct < 0 ? 'text-rose-400' : 'text-slate-400'}>
                      {m.pct > 0 ? '+' : ''}{m.pct.toFixed(1)}%
                    </span>
                  : <span className="text-slate-500">—</span>
                }
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function LogLine({ item, idx }) {
  const hitDot = item.recall1 === null
    ? <span className="w-2 h-2 rounded-full bg-slate-600 inline-block" title="no expected_doc_ids" />
    : item.recall1 >= 1
      ? <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" title="top-1 hit" />
      : <span className="w-2 h-2 rounded-full bg-slate-500 inline-block" title="not in top-1" />;

  return (
    <div className={`flex items-start gap-2 py-0.5 px-2 text-xs font-mono ${idx % 2 === 0 ? '' : 'bg-slate-800/30'}`}>
      <span className="text-slate-600 w-12 shrink-0">[{item.n}/{item.total}]</span>
      <span className="text-slate-300 flex-1 truncate">{item.question}</span>
      <span className="text-slate-500 w-16 shrink-0 text-right">{item.latency_ms}ms</span>
      <span className="text-slate-600 w-14 shrink-0 text-right">{item.n_chunks} ch</span>
      <span className="w-4 shrink-0 flex justify-center">{hitDot}</span>
    </div>
  );
}

// ── Guidelines content ────────────────────────────────────────────────────────

const METRIC_GUIDE = [
  {
    key: 'recall@5',
    label: 'Recall@5',
    thresholds: '≥0.70 good · ≥0.50 ok · <0.50 poor',
    desc: 'Fraction of questions for which at least one relevant document appears in the top-5 retrieved chunks. This is the primary signal for retrieval coverage — if the right document is not in the top-5, the LLM cannot answer correctly regardless of generation quality.',
    action: 'If low: check that expected_doc_ids are populated, try increasing RAG_TOP_K, or re-ingest with X4 contextual annotations.',
  },
  {
    key: 'mrr',
    label: 'Mean Reciprocal Rank (MRR)',
    thresholds: '≥0.60 good · ≥0.40 ok · <0.40 poor',
    desc: 'Average of 1/rank for the first relevant result. MRR=1.0 means the first result is always relevant. MRR=0.5 means the first relevant result is on average at position 2. Measures how high the first useful chunk is ranked.',
    action: 'If low vs recall@5: ranking is the problem, not coverage. Check reranker (X3) config — RERANKER_ENABLED=true, RAG_USE_RRF=true.',
  },
  {
    key: 'ndcg@5',
    label: 'NDCG@5',
    thresholds: '≥0.65 good · ≥0.45 ok · <0.45 poor',
    desc: 'Normalized Discounted Cumulative Gain at rank 5. Rewards not just finding relevant chunks but finding them early — a relevant result at rank 1 is worth more than one at rank 5. Combines coverage and ordering quality.',
    action: 'NDCG lower than MRR indicates multiple relevant docs exist but later ones are poorly ranked. Increase RERANKER_TOP_N.',
  },
  {
    key: 'faithfulness_substring',
    label: 'Faithfulness (Substring)',
    thresholds: '≥0.60 good · ≥0.40 ok',
    desc: 'Keyword coverage proxy: fraction of expected_answer_must_contain tokens found in the top-3 retrieved chunk texts. This is NOT end-to-end LLM answer faithfulness — it measures retrieval quality as a proxy. Requires expected_answer_must_contain populated in question YAML.',
    action: 'Only meaningful when expected_answer_must_contain is populated. If low: the relevant chunks are retrieved but contain the answer in different phrasing — consider lowering CONTEXTUAL_MAX_TOKENS to add more annotation context.',
  },
  {
    key: 'latency',
    label: 'P50 / P95 Latency',
    thresholds: 'P95 < 2 s good · < 5 s ok · ≥ 5 s poor',
    desc: 'Retrieval-only latency (not including LLM generation). P50 is the median; P95 is the 95th percentile. On a cold start or a loaded EC2 CPU instance, P95 can spike. The cross-encoder (X3) adds 800–1500ms on 30 pairs.',
    action: 'If P95 > 5s: reduce RERANKER_TOP_N (30→20) or set RERANKER_ENABLED=false. Latency is CPU-bound; GPU deployment reduces it ~10×.',
  },
];

function GuidelinesSection() {
  const [open, setOpen] = useState(null);
  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-400 mb-3">
        All metrics are measured on the <strong className="text-slate-300">retrieval layer only</strong> — they measure how well the pipeline surfaces relevant KB documents, not LLM generation quality. Run with <code className="text-indigo-300">--domain all</code> for a full picture; use a single domain to diagnose domain-specific regressions.
      </p>
      {METRIC_GUIDE.map(g => (
        <div key={g.key} className="border border-slate-700 rounded-lg overflow-hidden">
          <button
            onClick={() => setOpen(open === g.key ? null : g.key)}
            className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-slate-800 transition-colors"
          >
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-slate-200">{g.label}</span>
              <span className="text-xs text-slate-500 font-mono">{g.thresholds}</span>
            </div>
            {open === g.key ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}
          </button>
          {open === g.key && (
            <div className="px-3 pb-3 space-y-2 bg-slate-900/40">
              <p className="text-xs text-slate-300 leading-relaxed">{g.desc}</p>
              <p className="text-xs text-indigo-300 leading-relaxed">
                <span className="font-semibold">If low: </span>{g.action}
              </p>
            </div>
          )}
        </div>
      ))}
      <div className="mt-4 p-3 bg-slate-800/50 rounded-lg border border-slate-700 text-xs text-slate-400 space-y-1">
        <p className="font-semibold text-slate-300">Baseline → delta workflow</p>
        <p>1. Before deploying an ADR: run with label <code className="text-indigo-300">baseline</code></p>
        <p>2. Deploy ADR + re-ingest KB (required for X2, X4)</p>
        <p>3. Run with label <code className="text-indigo-300">post-x2</code> (or post-x3, post-x4)</p>
        <p>4. Use the <strong className="text-slate-300">Compare</strong> tab to diff the two runs</p>
        <p className="mt-2">Expected gains: +35% recall@20 from X4 alone (Anthropic benchmark); X3 improves MRR/NDCG more than recall.</p>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function EvalPage() {
  const [domains, setDomains]         = useState([]);
  const [selected, setSelected]       = useState([]);
  const [label, setLabel]             = useState('');
  const [running, setRunning]         = useState(false);
  const [logLines, setLogLines]       = useState([]);
  const [metrics, setMetrics]         = useState(null);
  const [runError, setRunError]       = useState(null);
  const [reports, setReports]         = useState([]);
  const [compareA, setCompareA]       = useState('');
  const [compareB, setCompareB]       = useState('');
  const [compareData, setCompareData] = useState(null);
  const [compareErr, setCompareErr]   = useState(null);
  const [tab, setTab]                 = useState('run');
  const [deleteTarget, setDeleteTarget] = useState(null);
  const logRef = useRef(null);
  const esRef  = useRef(null);

  useEffect(() => {
    API.eval.domains()
      .then(r => r.json())
      .then(d => { setDomains(d); setSelected(d); })
      .catch(() => {});
    fetchReports();
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logLines]);

  function fetchReports() {
    API.eval.reports()
      .then(r => r.json())
      .then(setReports)
      .catch(() => {});
  }

  function toggleDomain(d) {
    setSelected(prev => prev.includes(d) ? prev.filter(x => x !== d) : [...prev, d]);
  }

  function toggleAll() {
    setSelected(selected.length === domains.length ? [] : [...domains]);
  }

  async function startRun() {
    if (!label.trim()) return;
    if (selected.length === 0) return;

    setRunning(true);
    setLogLines([]);
    setMetrics(null);
    setRunError(null);

    const body = { label: label.trim(), domains: selected };
    const res = await API.eval.run(body);
    if (!res.ok) { setRunError('Failed to start job'); setRunning(false); return; }
    const { job_id } = await res.json();

    const es = new EventSource(`/agent/api/v1/eval/stream/${job_id}`);
    esRef.current = es;

    es.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.type === 'start') {
        setLogLines([{ type: 'info', text: `▶ Running ${data.total} questions — label: ${data.label}` }]);
      } else if (data.type === 'progress') {
        setLogLines(prev => [...prev, { type: 'progress', ...data }]);
      } else if (data.type === 'done') {
        setMetrics(data.metrics);
        setRunning(false);
        es.close();
        fetchReports();
      } else if (data.type === 'error') {
        setRunError(data.message);
        setRunning(false);
        es.close();
      }
    };
    es.onerror = () => {
      setRunError('SSE connection lost');
      setRunning(false);
      es.close();
    };
  }

  function stopRun() {
    esRef.current?.close();
    setRunning(false);
  }

  async function runCompare() {
    setCompareData(null);
    setCompareErr(null);
    const res = await API.eval.compare(compareA, compareB);
    if (!res.ok) { setCompareErr('Compare failed — check labels'); return; }
    setCompareData(await res.json());
  }

  async function confirmDeleteReport() {
    if (!deleteTarget) return;
    const lbl = deleteTarget;
    setDeleteTarget(null);
    await API.eval.deleteReport(lbl);
    fetchReports();
    if (compareA === lbl) setCompareA('');
    if (compareB === lbl) setCompareB('');
  }

  const TABS = [
    { id: 'run',       label: 'Run',      icon: Play      },
    { id: 'reports',   label: 'Reports',  icon: History   },
    { id: 'compare',   label: 'Compare',  icon: BarChart2 },
    { id: 'guide',     label: 'Guide',    icon: BookOpen  },
  ];

  return (
    <div className="flex flex-col h-full max-w-6xl" style={{ fontFamily: 'Outfit, sans-serif' }}>

      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <FlaskConical size={20} className="text-indigo-500" />
        <div>
          <h1 className="text-xl font-bold text-slate-900">RAG Eval Harness</h1>
          <p className="text-xs text-slate-500">recall@5 · MRR · NDCG@5 · latency — per-domain golden questions</p>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-4 border-b border-slate-200">
        {TABS.map(t => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm rounded-t transition-colors ${
                tab === t.id
                  ? 'border-b-2 border-indigo-600 text-indigo-700 font-medium bg-white'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              <Icon size={13} />
              {t.label}
              {t.id === 'reports' && reports.length > 0 && (
                <span className="ml-1 text-xs bg-slate-100 text-slate-500 rounded-full px-1.5">{reports.length}</span>
              )}
            </button>
          );
        })}
      </div>

      {/* ── TAB: Run ─────────────────────────────────────────────── */}
      {tab === 'run' && (
        <div className="flex gap-4 flex-1 min-h-0">

          {/* Left: config */}
          <div className="w-56 shrink-0 space-y-4">
            <div>
              <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider block mb-1">Label</label>
              <input
                value={label}
                onChange={e => setLabel(e.target.value)}
                placeholder="e.g. post-x4"
                className="w-full px-2 py-1.5 text-sm border border-slate-200 rounded focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-white"
                disabled={running}
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Domains</label>
                <button onClick={toggleAll} className="text-xs text-indigo-500 hover:text-indigo-700" disabled={running}>
                  {selected.length === domains.length ? 'None' : 'All'}
                </button>
              </div>
              <div className="space-y-1">
                {domains.map(d => (
                  <label key={d} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selected.includes(d)}
                      onChange={() => toggleDomain(d)}
                      disabled={running}
                      className="accent-indigo-600"
                    />
                    <span className="text-sm text-slate-700">{d}</span>
                  </label>
                ))}
              </div>
              {selected.length > 0 && (
                <p className="text-xs text-slate-400 mt-1">{selected.length} domain{selected.length > 1 ? 's' : ''} selected</p>
              )}
            </div>

            <button
              onClick={running ? stopRun : startRun}
              disabled={!running && (!label.trim() || selected.length === 0)}
              className={`w-full flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-medium transition-colors ${
                running
                  ? 'bg-rose-600 hover:bg-rose-700 text-white'
                  : 'bg-indigo-600 hover:bg-indigo-700 text-white disabled:bg-slate-200 disabled:text-slate-400'
              }`}
            >
              {running
                ? <><Loader2 size={14} className="animate-spin" /> Stop</>
                : <><Play size={14} /> Run Eval</>
              }
            </button>
          </div>

          {/* Right: log + results */}
          <div className="flex-1 flex flex-col gap-3 min-w-0">

            {/* Live log */}
            <div
              ref={logRef}
              className="flex-1 bg-slate-950 rounded-lg overflow-y-auto min-h-32 border border-slate-800"
            >
              {logLines.length === 0 && !running && (
                <div className="flex items-center justify-center h-full text-slate-600 text-sm">
                  Configure a run and click <strong className="ml-1">Run Eval</strong>
                </div>
              )}
              {logLines.map((line, i) => (
                line.type === 'info'
                  ? <div key={i} className="px-3 py-1.5 text-xs text-indigo-400 font-mono border-b border-slate-800">{line.text}</div>
                  : <LogLine key={i} item={line} idx={i} />
              ))}
              {running && (
                <div className="px-3 py-1.5 flex items-center gap-2 text-xs text-slate-500 font-mono">
                  <Loader2 size={10} className="animate-spin" /> waiting…
                </div>
              )}
            </div>

            {/* Error */}
            {runError && (
              <div className="flex items-center gap-2 p-2 bg-rose-50 border border-rose-200 rounded text-sm text-rose-700">
                <XCircle size={14} /> {runError}
              </div>
            )}

            {/* Results */}
            {metrics && (
              <div className="bg-slate-900 rounded-lg p-4 border border-slate-700">
                <div className="flex items-center gap-2 mb-3">
                  <CheckCircle size={14} className="text-emerald-500" />
                  <span className="text-sm font-semibold text-slate-200">Results — {label}</span>
                </div>
                <MetricsTable metrics={metrics} />
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── TAB: Reports ─────────────────────────────────────────── */}
      {tab === 'reports' && (
        <div className="flex-1 overflow-y-auto space-y-2">
          {reports.length === 0 && (
            <div className="text-sm text-slate-400 py-8 text-center">No saved reports yet — run an eval first.</div>
          )}
          {reports.map(r => (
            <div key={r.label} className="border border-slate-200 rounded-lg p-3 bg-white">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-slate-800 font-mono">{r.label}</span>
                <button onClick={() => setDeleteTarget(r.label)} className="text-slate-400 hover:text-rose-500 transition-colors">
                  <Trash2 size={13} />
                </button>
              </div>
              <MetricsTable metrics={r.metrics} />
            </div>
          ))}
        </div>
      )}

      {/* ── TAB: Compare ─────────────────────────────────────────── */}
      {tab === 'compare' && (
        <div className="flex-1 space-y-4">
          <div className="flex items-end gap-3">
            <div>
              <label className="text-xs text-slate-500 block mb-1">Baseline (A)</label>
              <select
                value={compareA}
                onChange={e => setCompareA(e.target.value)}
                className="px-2 py-1.5 text-sm border border-slate-200 rounded bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
              >
                <option value="">— select —</option>
                {reports.map(r => <option key={r.label} value={r.label}>{r.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-500 block mb-1">Comparison (B)</label>
              <select
                value={compareB}
                onChange={e => setCompareB(e.target.value)}
                className="px-2 py-1.5 text-sm border border-slate-200 rounded bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
              >
                <option value="">— select —</option>
                {reports.map(r => <option key={r.label} value={r.label}>{r.label}</option>)}
              </select>
            </div>
            <button
              onClick={runCompare}
              disabled={!compareA || !compareB || compareA === compareB}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-400 transition-colors"
            >
              <BarChart2 size={13} /> Compare
            </button>
          </div>

          {compareErr && (
            <div className="flex items-center gap-2 p-2 bg-rose-50 border border-rose-200 rounded text-sm text-rose-700">
              <XCircle size={14} /> {compareErr}
            </div>
          )}

          {compareData && (
            <div className="border border-slate-200 rounded-lg p-4 bg-white">
              <CompareTable data={compareData} />
            </div>
          )}
        </div>
      )}

      {/* ── TAB: Guide ───────────────────────────────────────────── */}
      {tab === 'guide' && (
        <div className="flex-1 overflow-y-auto">
          <div className="bg-slate-900 rounded-lg p-4 text-slate-200">
            <GuidelinesSection />
          </div>
        </div>
      )}

      {/* Delete report confirmation */}
      <AlertDialog open={!!deleteTarget} onOpenChange={open => { if (!open) setDeleteTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete report</AlertDialogTitle>
            <AlertDialogDescription>
              Delete report &ldquo;{deleteTarget}&rdquo;? This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDeleteReport}
              className="bg-rose-600 hover:bg-rose-700 text-white"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
