import { useState, useRef, useEffect, useCallback } from 'react';
import { Play, Square, Terminal, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useAgentLogs } from '../../hooks/useAgentLogs';
import { API } from '../../api.js';
import PinnedRefsSelector from '../kb/PinnedRefsSelector';

const TIMEOUT_SECS = 120; // matches ollama_timeout_seconds default

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

function LogLine({ log }) {
  const cls  = LOG_LEVEL_CLASS[log.level?.toUpperCase()] ?? 'text-slate-400';
  const time = log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : '';
  return (
    <div className="flex gap-3 leading-5 text-xs">
      <span className="text-slate-600 flex-shrink-0 w-20 font-mono">{time}</span>
      <span className={`font-mono font-semibold flex-shrink-0 w-16 ${cls}`}>
        [{log.level}]
      </span>
      <span className="text-slate-300 font-mono break-all">{log.message}</span>
    </div>
  );
}

function ProgressBar({ elapsed, progress }) {
  const isNearDone = progress >= 90;
  const barColor   = isNearDone ? 'bg-emerald-500' : 'bg-indigo-500';
  return (
    <div className="mt-4 space-y-1.5">
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span className="font-medium text-indigo-600">Processing…</span>
        <span className="font-mono tabular-nums">{elapsed}s / {TIMEOUT_SECS}s</span>
      </div>
      <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-1000 ease-linear ${barColor}`}
          style={{ width: `${progress}%` }}
        />
      </div>
      <div className="text-right text-xs font-semibold text-indigo-600 tabular-nums">
        {progress}%
      </div>
    </div>
  );
}

export default function AgentWorkspacePage() {
  const { logs, isRunning, trigger, cancel, triggerError, progress: apiProgress } = useAgentLogs();

  const [status,       setStatus]       = useState('idle'); // idle | running | done | error
  const [elapsed,      setElapsed]      = useState(0);
  const [progress,     setProgress]     = useState(0);
  const [localError,   setLocalError]   = useState(null);
  const [pinnedDocIds, setPinnedDocIds] = useState([]);
  const [kbDocs,       setKbDocs]       = useState([]);
  const [llmProfile,   setLlmProfile]   = useState('default'); // "default" | "high_quality"

  // Load KB docs (exclude URL-type; those have no chunks to pin)
  useEffect(() => {
    API.kb.list()
      .then(r => r.json())
      .then(d => setKbDocs((d.data || []).filter(doc => doc.file_type !== 'url')))
      .catch(() => {});
  }, []);

  // Real progress from API
  const overall     = apiProgress?.overall;
  const realPercent = overall?.total > 0
    ? Math.round((overall.done / overall.total) * 100)
    : 0;

  const progressRef = useRef(null);
  const logEndRef   = useRef(null);

  // Declare callbacks BEFORE any useEffect that references them (avoids TDZ ReferenceError)
  const startProgress = useCallback(() => {
    clearInterval(progressRef.current);
    let secs = 0;
    setElapsed(0);
    setProgress(0);
    progressRef.current = setInterval(() => {
      secs += 1;
      setElapsed(secs);
      setProgress(Math.min(Math.round((secs / TIMEOUT_SECS) * 100), 99));
    }, 1000);
  }, []);

  const stopProgress = useCallback((done = false) => {
    clearInterval(progressRef.current);
    if (done) {
      setProgress(100);
    } else {
      setProgress(0);
      setElapsed(0);
    }
  }, []);

  // cleanup on unmount
  useEffect(() => () => {
    clearInterval(progressRef.current);
  }, []);

  // Sync status and progress bar with isRunning from hook
  useEffect(() => {
    if (isRunning && status !== 'running') {
      setStatus('running');
      startProgress();
    } else if (!isRunning && status === 'running') {
      stopProgress(true);
      setStatus('done');
    }
  }, [isRunning, startProgress, stopProgress]);

  // auto-scroll log to bottom
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const handleStart = () => {
    setLocalError(null);
    trigger(
      { pinnedDocIds, llmProfile },
      {
        onError: (e) => {
          setLocalError(e.message || 'Failed to start agent');
          setStatus('error');
        },
      },
    );
  };

  const handleStop = () => {
    stopProgress(false);
    setStatus('idle');
    cancel(undefined, {
      onError: (e) => setLocalError(e.message || 'Cancel failed'),
    });
  };

  const displayError = localError || triggerError;

  const statusLabel = {
    idle:    'Ready to start agent processing',
    running: 'Agent is processing requirements…',
    done:    'Processing complete — check Integration Catalog',
    error:   'Agent encountered an error',
  }[status];

  return (
    <div className="space-y-4">
      {/* Pinned references selector — only shown when idle/done and KB has docs */}
      {!isRunning && kbDocs.length > 0 && (
        <PinnedRefsSelector
          docs={kbDocs}
          selected={pinnedDocIds}
          onChange={setPinnedDocIds}
        />
      )}

      {/* LLM profile selector — shown when idle/done (ADR-046) */}
      {!isRunning && (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
            Generation Profile
          </p>
          <div className="flex gap-2">
            {[
              { key: 'default',      label: 'Default Runtime', sub: 'qwen2.5:14b' },
              { key: 'high_quality', label: 'High Quality',    sub: 'gemma4:26b'  },
            ].map(({ key, label, sub }) => (
              <button
                key={key}
                onClick={() => setLlmProfile(key)}
                className={`flex flex-col items-start px-4 py-2 rounded-lg text-sm font-semibold transition-colors border ${
                  llmProfile === key
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : 'bg-white text-slate-600 border-slate-200 hover:border-indigo-400'
                }`}
              >
                <span>{label}</span>
                <span className={`text-xs font-normal font-mono ${llmProfile === key ? 'text-indigo-200' : 'text-slate-400'}`}>
                  {sub}
                </span>
              </button>
            ))}
          </div>
          <p className="text-xs text-slate-400 mt-1.5">
            {llmProfile === 'high_quality'
              ? 'Higher quality — slower. Recommended for complex integrations.'
              : 'Balanced — stable latency, good quality for most integrations.'}
          </p>
        </div>
      )}

      {/* Control panel */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
        <div className="flex items-center justify-between gap-6">
          <div className="min-w-0">
            <h2
              className="font-semibold text-slate-900 text-lg"
              style={{ fontFamily: 'Outfit, sans-serif' }}
            >
              Agent Control
            </h2>
            <p className="text-sm text-slate-500 mt-0.5">{statusLabel}</p>
            {displayError && (
              <p className="text-xs text-rose-600 mt-1">{displayError}</p>
            )}
          </div>

          <div className="flex items-center gap-3 flex-shrink-0">
            {status === 'done' && (
              <span className="flex items-center gap-1.5 text-emerald-600 text-sm font-semibold">
                <CheckCircle2 size={16} /> Complete
              </span>
            )}
            {status === 'error' && (
              <span className="flex items-center gap-1.5 text-rose-600 text-sm font-semibold">
                <AlertCircle size={16} /> Error
              </span>
            )}

            {isRunning ? (
              <button
                onClick={handleStop}
                className="flex items-center gap-2 px-6 py-3 bg-rose-600 text-white rounded-xl text-sm font-semibold hover:bg-rose-700 transition-colors"
              >
                <Square size={14} fill="currentColor" />
                Stop Agent
              </button>
            ) : (
              <button
                onClick={handleStart}
                className="flex items-center gap-2 px-6 py-3 bg-indigo-600 text-white rounded-xl text-sm font-semibold hover:bg-indigo-700 transition-colors"
              >
                <Play size={14} fill="currentColor" />
                Start Agent
              </button>
            )}
          </div>
        </div>

        {isRunning && (
          <>
            <ProgressBar elapsed={elapsed} progress={realPercent > 0 ? realPercent : progress} />
            {overall?.step && (
              <p className="text-xs text-slate-500 mt-1">{overall.step}</p>
            )}
          </>
        )}
      </div>

      {/* Terminal */}
      <div className="bg-slate-900 rounded-2xl overflow-hidden border border-slate-700 shadow-xl">
        {/* macOS-style header */}
        <div className="flex items-center gap-2 px-4 py-3 bg-slate-800 border-b border-slate-700">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-rose-500 opacity-80" />
            <div className="w-3 h-3 rounded-full bg-amber-400 opacity-80" />
            <div className="w-3 h-3 rounded-full bg-emerald-400 opacity-80" />
          </div>
          <div className="flex items-center gap-2 ml-2">
            <Terminal size={11} className="text-slate-500" />
            <span className="text-xs text-slate-500 font-mono">
              integration-agent — live log stream
            </span>
          </div>
        </div>

        {/* Log output */}
        <div className="p-4 h-[600px] overflow-y-auto terminal-scroll">
          {logs.length === 0 ? (
            <p className="text-slate-600 text-xs font-mono">
              {isRunning
                ? '▶  Waiting for first log entry…'
                : '$ Start the agent to see live logs here'}
            </p>
          ) : (
            <div className="space-y-0.5">
              {logs.map((log, i) => <LogLine key={`${log.timestamp ?? i}-${i}`} log={log} />)}
              <div ref={logEndRef} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
