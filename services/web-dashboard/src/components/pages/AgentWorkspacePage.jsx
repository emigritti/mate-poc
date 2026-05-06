import { useState, useRef, useEffect, useCallback } from 'react';
import { Play, Square, Pin, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useAgentLogs } from '../../hooks/useAgentLogs';
import { API } from '../../api.js';
import PinnedRefsSelector from '../kb/PinnedRefsSelector';
import PipelineStrip from '../agent/PipelineStrip';
import LogStream from '../agent/LogStream';
import { useProject } from '../../context/ProjectContext.jsx';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger,
} from '../ui/sheet';

const TIMEOUT_SECS = 120;
const MAX_PINNED   = 3;

const LLM_PROFILES = [
  { key: 'default',      label: 'Default',      model: 'qwen2.5:14b'  },
  { key: 'high_quality', label: 'High Quality',  model: 'gemma4:26b'   },
];

const STATUS_LABEL = {
  idle:    'Ready to start agent processing',
  running: 'Agent is processing requirements…',
  done:    'Processing complete — check Integration Catalog',
  error:   'Agent encountered an error',
};

export default function AgentWorkspacePage() {
  const { activeProjectId } = useProject();
  const { logs, isRunning, trigger, cancel, triggerError, progress: apiProgress } = useAgentLogs();

  const [status,       setStatus]       = useState('idle');
  const [elapsed,      setElapsed]      = useState(0);
  const [localError,   setLocalError]   = useState(null);
  const [pinnedDocIds, setPinnedDocIds] = useState([]);
  const [kbDocs,       setKbDocs]       = useState([]);
  const [llmProfile,   setLlmProfile]   = useState('default');

  const progressRef = useRef(null);

  useEffect(() => {
    API.kb.list()
      .then(r => r.json())
      .then(d => setKbDocs((d.data || []).filter(doc => doc.file_type !== 'url')))
      .catch(() => {});
  }, []);

  const startTimer = useCallback(() => {
    clearInterval(progressRef.current);
    let secs = 0;
    setElapsed(0);
    progressRef.current = setInterval(() => {
      secs += 1;
      setElapsed(secs);
    }, 1000);
  }, []);

  const stopTimer = useCallback(() => {
    clearInterval(progressRef.current);
    setElapsed(0);
  }, []);

  useEffect(() => () => clearInterval(progressRef.current), []);

  useEffect(() => {
    if (isRunning && status !== 'running') {
      setStatus('running');
      startTimer();
    } else if (!isRunning && status === 'running') {
      stopTimer();
      setStatus('done');
    }
  }, [isRunning, status, startTimer, stopTimer]);

  const handleStart = () => {
    setLocalError(null);
    trigger(
      { pinnedDocIds, llmProfile, projectId: activeProjectId },
      {
        onError: (e) => {
          setLocalError(e.message || 'Failed to start agent');
          setStatus('error');
        },
      },
    );
  };

  const handleStop = () => {
    stopTimer();
    setStatus('idle');
    cancel(undefined, {
      onError: (e) => setLocalError(e.message || 'Cancel failed'),
    });
  };

  const displayError   = localError || triggerError;
  const activeProfile  = LLM_PROFILES.find(p => p.key === llmProfile) ?? LLM_PROFILES[0];
  const runningElapsed = isRunning && elapsed > 0 ? ` · ${elapsed}s elapsed` : '';

  return (
    <div className="flex flex-col gap-4">
      {/* ── Header ───────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-zinc-200 px-5 py-4 flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1
            className="text-lg font-semibold text-zinc-900 leading-tight"
            style={{ fontFamily: 'Outfit, sans-serif' }}
          >
            Agent Workspace
          </h1>
          <p className="text-zinc-500 text-sm mt-0.5">
            {STATUS_LABEL[status]}{runningElapsed}
          </p>
          {displayError && (
            <p className="text-rose-600 text-xs mt-0.5 flex items-center gap-1">
              <AlertCircle size={11} /> {displayError}
            </p>
          )}
          {status === 'done' && !displayError && (
            <p className="text-emerald-600 text-xs mt-0.5 flex items-center gap-1">
              <CheckCircle2 size={11} /> Done
            </p>
          )}
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {/* LLM profile toggle — hidden while running */}
          {!isRunning && (
            <div className="flex gap-0.5 bg-zinc-100 rounded-lg p-0.5 border border-zinc-200">
              {LLM_PROFILES.map(p => (
                <button
                  key={p.key}
                  onClick={() => setLlmProfile(p.key)}
                  title={p.model}
                  className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${
                    llmProfile === p.key
                      ? 'bg-white text-zinc-900 shadow-sm'
                      : 'text-zinc-500 hover:text-zinc-700'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          )}

          {/* Pinned refs drawer — hidden while running */}
          {!isRunning && (
            <Sheet>
              <SheetTrigger asChild>
                <button
                  className={`flex items-center gap-1.5 px-3 py-2 border rounded-lg text-xs font-medium transition-colors ${
                    pinnedDocIds.length > 0
                      ? 'border-sky-300 text-sky-700 bg-sky-50 hover:bg-sky-100'
                      : 'border-zinc-200 text-zinc-600 hover:border-zinc-300 hover:bg-zinc-50'
                  }`}
                >
                  <Pin size={12} />
                  Pinned {pinnedDocIds.length}/{MAX_PINNED}
                </button>
              </SheetTrigger>
              <SheetContent className="w-[400px] sm:w-[440px]">
                <SheetHeader>
                  <SheetTitle className="flex items-center gap-2">
                    <Pin size={15} className="text-sky-600" />
                    Pinned References
                  </SheetTitle>
                </SheetHeader>
                <div className="mt-6">
                  <p className="text-zinc-500 text-xs mb-4">
                    Pin up to {MAX_PINNED} KB documents to inject their chunks verbatim into the LLM prompt,
                    regardless of RAG retrieval score.
                  </p>
                  {kbDocs.length === 0 ? (
                    <p className="text-zinc-400 text-sm text-center py-8">
                      No KB documents available. Upload documents to the Knowledge Base first.
                    </p>
                  ) : (
                    <PinnedRefsSelector
                      docs={kbDocs}
                      selected={pinnedDocIds}
                      onChange={setPinnedDocIds}
                    />
                  )}
                </div>
              </SheetContent>
            </Sheet>
          )}

          {/* LLM model badge while running */}
          {isRunning && (
            <span className="text-xs text-zinc-500 font-mono px-2 py-1 bg-zinc-100 rounded-md border border-zinc-200">
              {activeProfile.model}
            </span>
          )}

          {/* Start / Stop */}
          {isRunning ? (
            <button
              onClick={handleStop}
              className="flex items-center gap-2 px-4 py-2 bg-rose-600 text-white rounded-lg text-sm font-semibold hover:bg-rose-700 transition-colors"
            >
              <Square size={13} fill="currentColor" />
              Cancel
            </button>
          ) : (
            <button
              onClick={handleStart}
              className="flex items-center gap-2 px-4 py-2 bg-sky-600 text-white rounded-lg text-sm font-semibold hover:bg-sky-700 transition-colors"
            >
              <Play size={13} fill="currentColor" />
              Start Generation
            </button>
          )}
        </div>
      </div>

      {/* ── Pipeline strip ───────────────────────────────────────────── */}
      <PipelineStrip logs={logs} isRunning={isRunning} progress={apiProgress} />

      {/* ── Log stream ───────────────────────────────────────────────── */}
      <LogStream logs={logs} isRunning={isRunning} />
    </div>
  );
}
