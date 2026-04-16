/**
 * PipelineView — Horizontal RPG-style pipeline visualization (ADR-047 — Prompt 6).
 *
 * Props:
 *   activeStage   "ingestion"|"retrieval"|"generation"|"qa"|"enrichment" | null
 *   stageStates   { [stage]: "idle"|"working"|"success"|"error" }
 *   isRunning     boolean
 */
import Sprite from './Sprite';
import { STAGE_LABEL, AGENT_PERSONAS } from './personas';

const PIPELINE_STAGES = ['ingestion', 'retrieval', 'generation', 'qa', 'enrichment'];

export default function PipelineView({ activeStage = null, stageStates = {}, isRunning = false }) {
  return (
    <div className="pixel-panel">
      <p className="pixel-text-sm mb-3" style={{ color: 'var(--pixel-muted)' }}>
        ▶ AGENT PIPELINE
      </p>

      <div className="flex items-end justify-between gap-1 overflow-x-auto pb-1">
        {PIPELINE_STAGES.map((stage, i) => {
          const persona    = AGENT_PERSONAS[stage];
          const stageState = stageStates[stage] ?? (isRunning && stage === activeStage ? 'working' : 'idle');
          const isActive   = stage === activeStage && isRunning;
          const isDone     = stageState === 'success';
          const isError    = stageState === 'error';

          const dotColor = isError   ? 'var(--pixel-danger)'
                         : isDone    ? 'var(--pixel-primary)'
                         : isActive  ? 'var(--pixel-accent)'
                         : 'var(--pixel-muted)';

          const labelColor = isActive ? 'var(--pixel-accent)'
                           : isDone   ? 'var(--pixel-primary)'
                           : 'var(--pixel-muted)';

          return (
            <div key={stage} className="flex items-center gap-1 flex-shrink-0">
              <div className="flex flex-col items-center gap-1 min-w-[44px]">
                {/* Active indicator dot */}
                <div
                  style={{
                    width: 8, height: 8,
                    background: dotColor,
                    boxShadow: isActive ? `0 0 6px var(--pixel-accent)` : 'none',
                  }}
                />

                <Sprite
                  persona={persona}
                  state={stageState}
                  size={isActive ? 30 : 22}
                />

                <span
                  className="pixel-text-sm text-center"
                  style={{ fontSize: '5px', color: labelColor, maxWidth: 44 }}
                >
                  {STAGE_LABEL[stage]}
                </span>
              </div>

              {/* Connector arrow */}
              {i < PIPELINE_STAGES.length - 1 && (
                <span
                  className="pixel-text self-center pb-5"
                  style={{
                    fontSize: '8px',
                    color: isDone ? 'var(--pixel-primary)' : 'var(--pixel-muted)',
                    lineHeight: 1,
                  }}
                >
                  ▶
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
