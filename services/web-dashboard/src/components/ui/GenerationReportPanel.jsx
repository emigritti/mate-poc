import { useState } from 'react';
import {
  ChevronDown, ChevronRight, BookOpen, Database, Link, Layers,
  Cpu, BarChart2, Sparkles, AlertTriangle, CheckCircle,
} from 'lucide-react';

const SOURCE_META = {
  approved_example: { label: 'Approved Example',  color: 'bg-emerald-100 text-emerald-700', icon: BookOpen  },
  kb_document:      { label: 'KB Document',        color: 'bg-indigo-100 text-indigo-700',   icon: Database  },
  kb_url:           { label: 'KB URL',             color: 'bg-sky-100 text-sky-700',         icon: Link      },
  summary:          { label: 'Section Summary',    color: 'bg-violet-100 text-violet-700',   icon: Layers    },
};

function ScoreBar({ value }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.7 ? 'bg-emerald-500' : value >= 0.4 ? 'bg-amber-400' : 'bg-rose-400';
  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-400 w-8 text-right flex-shrink-0">{pct}%</span>
    </div>
  );
}

function SourceGroup({ label, chunks, meta }) {
  const [open, setOpen] = useState(false);
  const Icon = meta.icon;
  return (
    <div className="border border-slate-100 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-slate-50 hover:bg-slate-100 transition-colors text-left"
      >
        {open ? <ChevronDown size={12} className="text-slate-400 flex-shrink-0" />
               : <ChevronRight size={12} className="text-slate-400 flex-shrink-0" />}
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${meta.color}`}>
          <Icon size={10} /> {label}
        </span>
        <span className="text-xs text-slate-400 ml-auto">{chunks.length} chunk{chunks.length !== 1 ? 's' : ''}</span>
      </button>

      {open && (
        <div className="divide-y divide-slate-100">
          {chunks.map((c, i) => (
            <div key={i} className="px-3 py-2 space-y-1">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-mono text-slate-500 truncate">{c.doc_id || '—'}</span>
                <ScoreBar value={c.score} />
              </div>
              <p className="text-xs text-slate-500 leading-relaxed line-clamp-2">{c.preview}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function GenerationReportPanel({ report }) {
  const [open, setOpen] = useState(false);

  if (!report) return null;

  // Group sources by label
  const grouped = {};
  for (const chunk of (report.sources || [])) {
    grouped[chunk.source_label] = grouped[chunk.source_label] || [];
    grouped[chunk.source_label].push(chunk);
  }

  const qScore = report.quality_score ?? 0;
  const qColor = qScore >= 0.7 ? 'text-emerald-600' : qScore >= 0.4 ? 'text-amber-500' : 'text-rose-500';
  const totalSources = (report.sources || []).length;

  return (
    <div className="border-b border-slate-100 flex-shrink-0">
      {/* Toggle header */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-5 py-2 bg-slate-50 hover:bg-slate-100 transition-colors text-left"
      >
        {open
          ? <ChevronDown size={13} className="text-slate-400" />
          : <ChevronRight size={13} className="text-slate-400" />}
        <BarChart2 size={13} className="text-indigo-500" />
        <span className="text-xs font-semibold text-slate-600">Source Report</span>

        {/* Summary pills */}
        <div className="ml-auto flex items-center gap-2">
          <span className={`text-xs font-semibold ${qColor}`}>
            Q {Math.round(qScore * 100)}%
          </span>
          <span className="text-xs text-slate-400">
            {report.sections_count} sections
          </span>
          <span className={`inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded-full border ${
            report.na_count > 0
              ? 'text-amber-600 bg-amber-50 border-amber-200'
              : 'text-slate-400 bg-slate-50 border-slate-200'
          }`}>
            {report.na_count > 0 && <AlertTriangle size={9} />}
            {report.na_count} n/a
          </span>
          <span className={`inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded-full border ${
            totalSources > 0
              ? 'text-indigo-600 bg-indigo-50 border-indigo-200'
              : 'text-slate-400 bg-slate-50 border-slate-200'
          }`}>
            {totalSources} KB chunks
          </span>
          {report.claude_enriched && (
            <span className="inline-flex items-center gap-0.5 text-xs text-violet-600 bg-violet-50 border border-violet-200 px-1.5 py-0.5 rounded-full">
              <Sparkles size={9} /> Claude
            </span>
          )}
        </div>
      </button>

      {open && (
        <div className="px-5 py-4 space-y-4 bg-white max-h-80 overflow-y-auto">

          {/* Model & prompt stats */}
          <div className="flex flex-wrap gap-3 text-xs text-slate-500">
            <span className="flex items-center gap-1">
              <Cpu size={11} className="text-slate-400" />
              <span className="font-mono">{report.model}</span>
            </span>
            <span>Prompt <strong>{report.prompt_chars.toLocaleString()}</strong> chars</span>
            <span>Context <strong>{report.context_chars.toLocaleString()}</strong> chars</span>
            {report.claude_enriched && (
              <span className="flex items-center gap-1 text-violet-600">
                <Sparkles size={11} /> Claude enrichment applied
              </span>
            )}
          </div>

          {/* Quality issues */}
          {report.quality_issues?.length > 0 && (
            <div className="flex flex-col gap-1">
              {report.quality_issues.map((issue, i) => (
                <div key={i} className="flex items-start gap-1.5 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5">
                  <AlertTriangle size={10} className="mt-0.5 flex-shrink-0" /> {issue}
                </div>
              ))}
            </div>
          )}
          {!report.quality_issues?.length && (
            <div className="flex items-center gap-1.5 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-2.5 py-1.5">
              <CheckCircle size={10} /> Quality checks passed
            </div>
          )}

          {/* Sources grouped by type */}
          {totalSources === 0 ? (
            <p className="text-xs text-slate-400 italic">
              No KB context was retrieved — document generated from requirements only.
            </p>
          ) : (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                Retrieved Context ({totalSources} chunks)
              </p>
              {Object.entries(grouped).map(([label, chunks]) => {
                const meta = SOURCE_META[label] || { label, color: 'bg-slate-100 text-slate-600', icon: Database };
                return (
                  <SourceGroup key={label} label={meta.label} chunks={chunks} meta={meta} />
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
