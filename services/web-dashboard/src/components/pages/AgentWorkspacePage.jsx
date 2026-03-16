import { useState, useRef, useEffect, useCallback } from 'react';
import { Play, Square, Terminal, AlertCircle, CheckCircle2 } from 'lucide-react';
import { API } from '../../api.js';

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
  const [running,  setRunning]  = useState(false);
  const [logs,     setLogs]     = useState([]);
  const [status,   setStatus]   = useState('idle'); // idle | running | done | error
  const [elapsed,  setElapsed]  = useState(0);
  const [progress, setProgress] = useState(0);

  const offsetRef   = useRef(0);
  const pollingRef  = useRef(null);
  const progressRef = useRef(null);
  const logEndRef   = useRef(null);

  // cleanup on unmount
  useEffect(() => () => {
    clearInterval(pollingRef.current);
    clearInterval(progressRef.current);
  }, []);

  // auto-scroll log to bottom
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const startProgress = useCallback(() => {
    let secs = 0;
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

  const startPolling = useCallback(() => {
    pollingRef.current = setInterval(async () => {
      try {
        const res  = await API.agent.logs(offsetRef.current);
        const data = await res.json();
        if (data.logs?.length > 0) {
          setLogs(prev => [...prev, ...data.logs]);
          offsetRef.current = data.next_offset ?? (offsetRef.current + data.logs.length);
        }
        if (data.finished) {
          clearInterval(pollingRef.current);
          stopProgress(true);
          setRunning(false);
          setStatus('done');
        }
      } catch {
        // keep polling through transient network errors
      }
    }, 2000);
  }, [stopProgress]);

  const handleStart = async () => {
    setLogs([]);
    offsetRef.current = 0;
    setElapsed(0);
    setProgress(0);
    setStatus('running');
    setRunning(true);
    try {
      const res = await API.agent.trigger();
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        setLogs([{
          level: 'ERROR',
          message: d.detail || 'Failed to start agent',
          timestamp: new Date().toISOString(),
        }]);
        setStatus('error');
        setRunning(false);
        stopProgress(false);
        return;
      }
      startPolling();
      startProgress();
    } catch (e) {
      setLogs([{ level: 'ERROR', message: e.message, timestamp: new Date().toISOString() }]);
      setStatus('error');
      setRunning(false);
      stopProgress(false);
    }
  };

  const handleStop = async () => {
    clearInterval(pollingRef.current);
    stopProgress(false);
    await API.agent.cancel().catch(() => {});
    setRunning(false);
    setStatus('idle');
  };

  const statusLabel = {
    idle:    'Ready to start agent processing',
    running: 'Agent is processing requirements…',
    done:    'Processing complete — check Integration Catalog',
    error:   'Agent encountered an error',
  }[status];

  return (
    <div className="space-y-4">
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

            {running ? (
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

        {running && <ProgressBar elapsed={elapsed} progress={progress} />}
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
              {running
                ? '▶  Waiting for first log entry…'
                : '$ Start the agent to see live logs here'}
            </p>
          ) : (
            <div className="space-y-0.5">
              {logs.map((log, i) => <LogLine key={i} log={log} />)}
              <div ref={logEndRef} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
