import { Database, Search, Cpu, ShieldCheck, Sparkles, Check } from 'lucide-react';

const PIPELINE_STAGES = [
  {
    id: 'ingestion',
    label: 'Ingestion',
    icon: Database,
    keywords: ['ingestion', 'loading', 'reading', 'requirements', 'csv', 'parsed', 'upload'],
  },
  {
    id: 'retrieval',
    label: 'Retrieval',
    icon: Search,
    keywords: ['retrieval', 'rag', 'bm25', 'hybrid', 'context', 'chunk', 'retrieving', 'searching kb'],
  },
  {
    id: 'generation',
    label: 'Generation',
    icon: Cpu,
    keywords: ['generation', 'generating', 'llm', 'ollama', 'prompt', 'calling', 'model'],
  },
  {
    id: 'qa',
    label: 'QA',
    icon: ShieldCheck,
    keywords: ['quality', 'qa', 'guard', 'validation', 'checking', 'output guard'],
  },
  {
    id: 'enrichment',
    label: 'Enrichment',
    icon: Sparkles,
    keywords: ['enrichment', 'enriching', 'claude', 'anthropic', 'finalizing', 'enrich'],
  },
];

const STAGE_ORDER = PIPELINE_STAGES.map(s => s.id);

function detectStageFromText(text) {
  if (!text) return null;
  const lower = text.toLowerCase();
  for (const stage of PIPELINE_STAGES) {
    if (stage.keywords.some(kw => lower.includes(kw))) return stage.id;
  }
  return null;
}

function findLatestStageIdx(logs) {
  let latest = -1;
  for (const log of logs) {
    const id = detectStageFromText(log.message ?? '');
    if (id) {
      const idx = STAGE_ORDER.indexOf(id);
      if (idx > latest) latest = idx;
    }
  }
  return latest;
}

function findCurrentStageIdx(logs, progressStep) {
  if (progressStep) {
    const id = detectStageFromText(progressStep);
    if (id) return STAGE_ORDER.indexOf(id);
  }
  const recent = [...logs].reverse().slice(0, 15);
  for (const log of recent) {
    const id = detectStageFromText(log.message ?? '');
    if (id) return STAGE_ORDER.indexOf(id);
  }
  return -1;
}

function deriveStatuses(logs, isRunning, progressStep) {
  if (logs.length === 0) {
    return PIPELINE_STAGES.map(s => ({ ...s, status: 'idle' }));
  }
  if (!isRunning) {
    const latestIdx = findLatestStageIdx(logs);
    return PIPELINE_STAGES.map((s, i) => ({
      ...s,
      status: i <= latestIdx ? 'done' : 'idle',
    }));
  }
  const currentIdx = findCurrentStageIdx(logs, progressStep);
  return PIPELINE_STAGES.map((s, i) => ({
    ...s,
    status: i < currentIdx ? 'done' : i === currentIdx ? 'active' : 'idle',
  }));
}

const STAGE_STYLE = {
  idle:   { ring: 'border-zinc-700',     bg: 'bg-zinc-900',    text: 'text-zinc-600'    },
  active: { ring: 'border-sky-500',      bg: 'bg-sky-950',     text: 'text-sky-300'     },
  done:   { ring: 'border-emerald-600',  bg: 'bg-emerald-950', text: 'text-emerald-400' },
  error:  { ring: 'border-rose-500',     bg: 'bg-rose-950',    text: 'text-rose-400'    },
};

const ICON_COLOR = {
  idle:   'text-zinc-600',
  active: 'text-sky-400',
  done:   'text-emerald-400',
  error:  'text-rose-400',
};

const CONNECTOR_COLOR = {
  done:   'bg-emerald-700',
  active: 'bg-sky-800',
  idle:   'bg-zinc-800',
};

export default function PipelineStrip({ logs, isRunning, progress }) {
  const stages = deriveStatuses(logs, isRunning, progress?.overall?.step);

  return (
    <div className="bg-zinc-900 rounded-xl border border-zinc-800 px-6 py-5">
      <p className="text-zinc-600 text-[10px] uppercase tracking-wider mb-5">Pipeline</p>
      <div className="flex items-start">
        {stages.map((stage, idx) => {
          const style   = STAGE_STYLE[stage.status];
          const icon    = ICON_COLOR[stage.status];
          const Icon    = stage.icon;
          const isActive = stage.status === 'active';
          const isDone   = stage.status === 'done';

          return (
            <div key={stage.id} className="flex items-start flex-1 last:flex-none">
              {/* Stage node */}
              <div className="flex flex-col items-center gap-2 flex-shrink-0">
                <div
                  className={`relative w-10 h-10 rounded-full border-2 ${style.ring} ${style.bg} flex items-center justify-center`}
                >
                  {isDone
                    ? <Check size={16} className="text-emerald-400" strokeWidth={2.5} />
                    : <Icon size={16} className={icon} />
                  }
                  {isActive && (
                    <span className="absolute -top-0.5 -right-0.5 w-3 h-3 rounded-full bg-sky-500 border-2 border-zinc-900 animate-pulse" />
                  )}
                </div>
                <p className={`text-[11px] font-medium whitespace-nowrap ${style.text}`}>
                  {stage.label}
                </p>
              </div>

              {/* Connector */}
              {idx < stages.length - 1 && (
                <div className={`flex-1 h-px mt-5 mx-2 transition-colors duration-500 ${
                  CONNECTOR_COLOR[stage.status] ?? CONNECTOR_COLOR.idle
                }`} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
