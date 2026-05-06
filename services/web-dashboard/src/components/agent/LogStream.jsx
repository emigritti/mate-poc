import { useRef, useEffect, useState } from 'react';
import { Terminal, ArrowDownToLine, ArrowDown, ChevronDown, ChevronRight } from 'lucide-react';

const LOG_LEVEL_CLASS = {
  INFO:    'log-info',
  LLM:     'log-llm',
  RAG:     'log-rag',
  SUCCESS: 'log-success',
  WARN:    'log-warn',
  WARNING: 'log-warning',
  ERROR:   'log-error',
  CANCEL:  'log-cancel',
};

const STAGE_KEYWORDS = {
  ingestion:  ['ingestion', 'loading', 'reading', 'requirements', 'csv', 'parsed', 'upload'],
  retrieval:  ['retrieval', 'rag', 'bm25', 'hybrid', 'context', 'chunk', 'retrieving', 'searching'],
  generation: ['generation', 'generating', 'llm', 'ollama', 'prompt', 'calling', 'model'],
  qa:         ['quality', 'qa', 'guard', 'validation', 'checking', 'output guard'],
  enrichment: ['enrichment', 'enriching', 'claude', 'anthropic', 'finalizing', 'enrich'],
};

const STAGE_LABEL = {
  ingestion:  'Ingestion',
  retrieval:  'Retrieval',
  generation: 'Generation',
  qa:         'QA',
  enrichment: 'Enrichment',
};

function detectStage(text) {
  if (!text) return null;
  const lower = text.toLowerCase();
  for (const [stage, keywords] of Object.entries(STAGE_KEYWORDS)) {
    if (keywords.some(kw => lower.includes(kw))) return stage;
  }
  return null;
}

function groupLogs(logs) {
  const groups = [];
  let current = null;
  for (const log of logs) {
    const stage = detectStage(log.message ?? '') ?? current?.stage ?? null;
    if (!current || (detectStage(log.message ?? '') && stage !== current.stage)) {
      current = { stage, entries: [] };
      groups.push(current);
    }
    current.entries.push(log);
  }
  return groups;
}

function LogLine({ log }) {
  const cls  = LOG_LEVEL_CLASS[log.level?.toUpperCase()] ?? 'text-zinc-500';
  const time = log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : '';
  return (
    <div className="flex gap-3 leading-5 text-xs py-0.5">
      <span className="text-zinc-600 flex-shrink-0 w-20 font-mono">{time}</span>
      <span className={`font-mono font-semibold flex-shrink-0 w-16 ${cls}`}>[{log.level}]</span>
      <span className="text-zinc-300 font-mono break-all">{log.message}</span>
    </div>
  );
}

function StageGroup({ stage, entries, isLast }) {
  const [open, setOpen] = useState(isLast);

  useEffect(() => {
    if (isLast) setOpen(true);
  }, [isLast]);

  const label = stage ? (STAGE_LABEL[stage] ?? stage) : 'General';

  return (
    <div className="mb-3">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 text-zinc-500 hover:text-zinc-300 transition-colors py-0.5 w-full text-left"
      >
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        <span className="text-[10px] font-semibold uppercase tracking-wider">{label}</span>
        <span className="text-zinc-700 text-[10px] ml-1">({entries.length})</span>
      </button>
      {open && (
        <div className="mt-1 pl-4 border-l border-zinc-800">
          {entries.map((log, i) => (
            <LogLine key={`${log.timestamp ?? i}-${i}`} log={log} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function LogStream({ logs, isRunning }) {
  const endRef       = useRef(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    if (autoScroll) {
      endRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  const groups = groupLogs(logs);
  const lastIdx = groups.length - 1;

  return (
    <div
      className="bg-zinc-950 rounded-xl overflow-hidden border border-zinc-800 flex flex-col"
      style={{ height: 'calc(100vh - 390px)', minHeight: '300px' }}
    >
      {/* Terminal header */}
      <div className="flex items-center justify-between px-4 py-3 bg-zinc-900 border-b border-zinc-800 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-rose-500 opacity-80" />
            <div className="w-3 h-3 rounded-full bg-amber-400 opacity-80" />
            <div className="w-3 h-3 rounded-full bg-emerald-400 opacity-80" />
          </div>
          <div className="flex items-center gap-2 ml-1">
            <Terminal size={11} className="text-zinc-600" />
            <span className="text-xs text-zinc-600 font-mono">integration-agent — live log stream</span>
            {isRunning && (
              <span className="flex items-center gap-1 text-sky-500 text-xs ml-2">
                <span className="w-1.5 h-1.5 rounded-full bg-sky-500 animate-pulse" />
                live
              </span>
            )}
          </div>
        </div>

        <button
          onClick={() => setAutoScroll(a => !a)}
          title={autoScroll ? 'Pause auto-scroll' : 'Resume auto-scroll'}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors border ${
            autoScroll
              ? 'bg-sky-900/60 text-sky-400 border-sky-700'
              : 'bg-zinc-800 text-zinc-500 border-zinc-700 hover:text-zinc-300'
          }`}
        >
          {autoScroll ? <ArrowDownToLine size={11} /> : <ArrowDown size={11} />}
          {autoScroll ? 'Auto-scroll' : 'Scroll off'}
        </button>
      </div>

      {/* Log output */}
      <div className="flex-1 p-4 overflow-y-auto terminal-scroll">
        {logs.length === 0 ? (
          <p className="text-zinc-600 text-xs font-mono">
            {isRunning ? '▶  Waiting for first log entry…' : '$ Start the agent to see live logs here'}
          </p>
        ) : (
          <div>
            {groups.map((group, gi) => (
              <StageGroup
                key={gi}
                stage={group.stage}
                entries={group.entries}
                isLast={gi === lastIdx}
              />
            ))}
            <div ref={endRef} />
          </div>
        )}
      </div>
    </div>
  );
}
