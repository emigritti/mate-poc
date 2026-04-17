/**
 * PixelAgentWorkspace — 8-bit RPG-style agent workspace (ADR-047).
 * Replaces AgentWorkspacePage when ui_mode = "pixel".
 * Uses the same useAgentLogs / API hooks as classic mode.
 */
import { useState, useRef, useEffect } from 'react';
import { useAgentLogs } from '../../hooks/useAgentLogs';
import PipelineView from './PipelineView';
import { narrateLog } from './PersonaNarrator';
import { inferStageFromLog } from './personas';

/** Build stage → state map from the last N log entries. */
function buildStageStates(logs) {
  const states = {};
  for (let i = logs.length - 1; i >= 0; i--) {
    const log   = logs[i];
    const stage = inferStageFromLog(log.message);
    if (!stage || states[stage]) continue;
    const lvl = (log.level ?? '').toUpperCase();
    states[stage] = lvl === 'ERROR' ? 'error' : lvl === 'SUCCESS' ? 'success' : 'working';
  }
  return states;
}

export default function PixelAgentWorkspace() {
  const { logs, isRunning, trigger, cancel, triggerError, progress: apiProgress } = useAgentLogs();

  const [llmProfile, setLlmProfile] = useState('default'); // "default" | "high_quality"
  const [localError,  setLocalError]  = useState(null);
  const [pinnedDocIds]                = useState([]);
  const logEndRef = useRef(null);

  // Derive active stage from the last log entry
  const lastLog     = logs[logs.length - 1];
  const activeStage = isRunning && lastLog ? (inferStageFromLog(lastLog.message) ?? 'ingestion') : null;
  const stageStates = isRunning ? buildStageStates(logs) : {};

  // Auto-scroll narration log
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const handleStart = () => {
    setLocalError(null);
    trigger(
      { pinnedDocIds, llmProfile },
      { onError: (e) => setLocalError(e.message || 'Failed to start quest') },
    );
  };

  const overall  = apiProgress?.overall;
  const questPct = overall?.total > 0 ? Math.round((overall.done / overall.total) * 100) : 0;

  return (
    <div className="space-y-4 p-2">

      {/* ── Pipeline visualization ── */}
      <PipelineView activeStage={activeStage} stageStates={stageStates} isRunning={isRunning} />

      {/* ── Quest control panel ── */}
      <div className="pixel-panel-accent">
        <p className="pixel-text-sm mb-1" style={{ color: 'var(--pixel-muted)' }}>
          ▶ COMMAND CENTER
        </p>

        {/* Profile selector */}
        {!isRunning && (
          <div className="flex gap-2 mb-3">
            {[
              { key: 'default',      label: 'DEFAULT RUNTIME', sub: 'qwen2.5:14b' },
              { key: 'high_quality', label: 'HIGH QUALITY',    sub: 'gemma4:26b'  },
            ].map(({ key, label, sub }) => (
              <button
                key={key}
                onClick={() => setLlmProfile(key)}
                className={`pixel-button ${key === 'high_quality' ? 'pixel-button-accent' : ''}`}
                style={llmProfile === key ? {
                  background: key === 'high_quality' ? 'var(--pixel-accent)' : 'var(--pixel-primary)',
                  color: 'var(--pixel-bg)',
                } : {}}
              >
                {label}
                <span style={{ fontSize: 5, display: 'block', opacity: 0.7 }}>{sub}</span>
              </button>
            ))}
          </div>
        )}

        <div className="flex items-center justify-between gap-4">
          <div>
            {isRunning ? (
              <p className="pixel-text" style={{ color: 'var(--pixel-accent)' }}>⚔ QUEST IN PROGRESS...</p>
            ) : (
              <p className="pixel-text" style={{ color: 'var(--pixel-muted)' }}>READY FOR ADVENTURE</p>
            )}
            {(localError || triggerError) && (
              <p className="pixel-text-sm" style={{ color: 'var(--pixel-danger)' }}>
                ✗ {localError || triggerError}
              </p>
            )}
          </div>

          {isRunning ? (
            <button onClick={() => cancel()} className="pixel-button pixel-button-danger">■ ABORT</button>
          ) : (
            <button onClick={handleStart} className="pixel-button">▶ START QUEST</button>
          )}
        </div>

        {/* Quest progress bar */}
        {isRunning && (
          <div className="mt-3">
            <div className="flex justify-between mb-1">
              <span className="pixel-text-sm" style={{ color: 'var(--pixel-muted)' }}>QUEST PROGRESS</span>
              <span className="pixel-text-sm" style={{ color: 'var(--pixel-accent)' }}>{questPct}%</span>
            </div>
            <div className="w-full h-3" style={{ background: 'var(--pixel-muted)', border: '1px solid var(--pixel-border)' }}>
              <div
                className="h-full transition-all duration-500"
                style={{
                  width: `${questPct}%`,
                  background: questPct >= 100 ? 'var(--pixel-primary)' : 'var(--pixel-accent)',
                }}
              />
            </div>
            {overall?.step && (
              <p className="pixel-text-sm mt-1" style={{ color: 'var(--pixel-muted)' }}>{overall.step}</p>
            )}
          </div>
        )}
      </div>

      {/* ── Narration log terminal ── */}
      <div className="pixel-panel">
        <p className="pixel-text-sm mb-2" style={{ color: 'var(--pixel-muted)' }}>▶ QUEST LOG</p>
        <div
          className="pixel-scroll overflow-y-auto space-y-1"
          style={{ height: 320, background: 'var(--pixel-bg)', padding: 8 }}
        >
          {logs.length === 0 ? (
            <p className="pixel-text-sm" style={{ color: 'var(--pixel-muted)' }}>
              {isRunning ? '▶ Awaiting first battle report...' : '$ Start the quest to see the log'}
            </p>
          ) : (
            logs.map((log, i) => {
              const { text } = narrateLog(log);
              const isErr    = (log.level ?? '').toUpperCase() === 'ERROR';
              const isOk     = (log.level ?? '').toUpperCase() === 'SUCCESS';
              return (
                <div key={`${log.timestamp ?? i}-${i}`} className="flex gap-2">
                  <span
                    className="pixel-text-sm flex-shrink-0"
                    style={{ color: 'var(--pixel-muted)', minWidth: 40, fontSize: 5 }}
                  >
                    {log.timestamp
                      ? new Date(log.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                      : ''}
                  </span>
                  <span
                    className="pixel-text-sm"
                    style={{ color: isErr ? 'var(--pixel-danger)' : isOk ? 'var(--pixel-primary)' : 'var(--pixel-text)' }}
                  >
                    {text}
                  </span>
                </div>
              );
            })
          )}
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  );
}
