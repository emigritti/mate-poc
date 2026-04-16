# Pixel UI Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a dual UI system where users can toggle between Classic (current) and Pixel (8-bit RPG gamified) mode, with persona-driven pipeline visualization and character-narrated agent logs.

**Architecture:** A `UiModeContext` React context (localStorage-persisted) wraps the entire app. When `mode === "pixel"`, the main layout applies pixel CSS classes and swaps `AgentWorkspacePage` for `PixelAgentWorkspace` (with RPG pipeline + persona narration). All other pages receive pixel CSS via a root class. Sprites are emoji/CSS-based (no PNG assets required). Classic mode is entirely unaffected by pixel code paths.

**Tech Stack:** React 18, Vite, Tailwind CSS 3.4, Lucide React, Press Start 2P (Google Fonts), CSS custom properties.

---

### Task 1: Font + Pixel CSS Design System

**Files:**
- Modify: `services/web-dashboard/index.html`
- Modify: `services/web-dashboard/src/index.css`

**Step 1: Add Press Start 2P to Google Fonts in index.html**

Add to the existing `<link rel="preconnect">` block:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Outfit:wght@300;400;500;600;700;800&family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```
(Merge Press Start 2P into the existing Fonts URL — combine into one request.)

**Step 2: Add pixel CSS classes to index.css**

Append to end of file:
```css
/* ─────────────────────────────────────────
   Pixel Mode Design System (ADR-047)
   ───────────────────────────────────────── */
:root {
  --pixel-bg:        #0d0d0d;
  --pixel-surface:   #1a1a2e;
  --pixel-primary:   #4ade80;
  --pixel-accent:    #fbbf24;
  --pixel-danger:    #f87171;
  --pixel-text:      #86efac;
  --pixel-muted:     #4b5563;
  --pixel-border:    #4ade80;
  --pixel-shadow:    4px 4px 0px #166534;
  --pixel-font:      'Press Start 2P', monospace;
}

/* Root wrapper toggled by UiModeProvider */
.pixel-mode {
  background-color: var(--pixel-bg);
  color: var(--pixel-text);
  font-family: var(--pixel-font);
}

/* ── Utility classes ── */
.pixel-panel {
  background-color: var(--pixel-surface);
  border: 2px solid var(--pixel-border);
  box-shadow: var(--pixel-shadow);
  border-radius: 0 !important;
  padding: 16px;
}

.pixel-panel-accent {
  background-color: var(--pixel-surface);
  border: 2px solid var(--pixel-accent);
  box-shadow: 4px 4px 0px #92400e;
  border-radius: 0 !important;
  padding: 16px;
}

.pixel-button {
  font-family: var(--pixel-font);
  font-size: 7px;
  background-color: var(--pixel-surface);
  color: var(--pixel-primary);
  border: 2px solid var(--pixel-border);
  box-shadow: 3px 3px 0 #166534;
  border-radius: 0 !important;
  padding: 8px 14px;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  transition: transform 0.05s, box-shadow 0.05s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.pixel-button:hover {
  transform: translate(2px, 2px);
  box-shadow: 1px 1px 0 #166534;
}

.pixel-button:active {
  transform: translate(3px, 3px);
  box-shadow: none;
}

.pixel-button-danger {
  color: var(--pixel-danger);
  border-color: var(--pixel-danger);
  box-shadow: 3px 3px 0 #7f1d1d;
}

.pixel-button-danger:hover {
  transform: translate(2px, 2px);
  box-shadow: 1px 1px 0 #7f1d1d;
}

.pixel-button-accent {
  color: var(--pixel-accent);
  border-color: var(--pixel-accent);
  box-shadow: 3px 3px 0 #92400e;
}

.pixel-text {
  font-family: var(--pixel-font);
  font-size: 7px;
  line-height: 2;
}

.pixel-text-sm {
  font-family: var(--pixel-font);
  font-size: 6px;
  line-height: 2;
}

.pixel-heading {
  font-family: var(--pixel-font);
  font-size: 10px;
  color: var(--pixel-accent);
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.pixel-heading-lg {
  font-family: var(--pixel-font);
  font-size: 13px;
  color: var(--pixel-accent);
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.pixel-badge {
  font-family: var(--pixel-font);
  font-size: 5px;
  padding: 3px 6px;
  border: 1px solid currentColor;
  border-radius: 0;
  text-transform: uppercase;
}

/* ── Sprite animations ── */
@keyframes pixel-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

@keyframes pixel-shake {
  0%, 100% { transform: translateX(0); }
  20%       { transform: translateX(-3px); }
  40%       { transform: translateX(3px); }
  60%       { transform: translateX(-2px); }
  80%       { transform: translateX(2px); }
}

@keyframes pixel-bounce {
  0%, 100% { transform: translateY(0); }
  50%       { transform: translateY(-4px); }
}

@keyframes pixel-glow {
  0%, 100% { text-shadow: 0 0 4px var(--pixel-primary); }
  50%       { text-shadow: 0 0 12px var(--pixel-primary), 0 0 20px var(--pixel-primary); }
}

.pixel-working  { animation: pixel-blink  0.8s ease-in-out infinite; }
.pixel-success  { animation: pixel-glow   1.5s ease-in-out infinite; }
.pixel-error    { animation: pixel-shake  0.4s ease-in-out; }
.pixel-bounce   { animation: pixel-bounce 0.6s ease-in-out infinite; }

/* ── Scrollbar (pixel mode terminal) ── */
.pixel-scroll::-webkit-scrollbar        { width: 6px; }
.pixel-scroll::-webkit-scrollbar-track  { background: var(--pixel-bg); }
.pixel-scroll::-webkit-scrollbar-thumb  { background: var(--pixel-border); border-radius: 0; }
```

**Step 3: Commit**

```bash
git add services/web-dashboard/index.html services/web-dashboard/src/index.css
git commit -m "feat(pixel-ui): add Press Start 2P font and pixel CSS design system (ADR-047)"
```

---

### Task 2: UiModeContext + useUiMode hook

**Files:**
- Create: `services/web-dashboard/src/context/UiModeContext.jsx`

**Step 1: Implement**

```jsx
/**
 * UiModeContext — Global UI mode switch (ADR-047).
 * Persists to localStorage under key "ui_mode".
 * Supported modes: "classic" | "pixel"
 */
import { createContext, useContext, useState } from 'react';

const UiModeContext = createContext({ mode: 'classic', setMode: () => {} });

export function UiModeProvider({ children }) {
  const [mode, setModeState] = useState(
    () => localStorage.getItem('ui_mode') || 'classic',
  );

  const setMode = (m) => {
    setModeState(m);
    localStorage.setItem('ui_mode', m);
  };

  return (
    <UiModeContext.Provider value={{ mode, setMode }}>
      <div className={mode === 'pixel' ? 'pixel-mode h-full' : 'h-full'}>
        {children}
      </div>
    </UiModeContext.Provider>
  );
}

/** Returns { mode, setMode } */
export function useUiMode() {
  return useContext(UiModeContext);
}
```

**Step 2: Commit**

```bash
git add services/web-dashboard/src/context/UiModeContext.jsx
git commit -m "feat(pixel-ui): add UiModeContext with localStorage persistence"
```

---

### Task 3: UiModeToggle component

**Files:**
- Create: `services/web-dashboard/src/components/pixel/UiModeToggle.jsx`

**Step 1: Implement**

```jsx
/**
 * UiModeToggle — Toggle between Classic and Pixel UI modes.
 * Rendered in TopBar. Uses useUiMode from UiModeContext.
 */
import { Gamepad2, Monitor } from 'lucide-react';
import { useUiMode } from '../../context/UiModeContext';

export default function UiModeToggle() {
  const { mode, setMode } = useUiMode();

  if (mode === 'pixel') {
    return (
      <button
        onClick={() => setMode('classic')}
        title="Switch to Classic mode"
        className="pixel-button pixel-button-accent text-[6px] flex items-center gap-1.5"
      >
        <Monitor size={11} />
        Classic
      </button>
    );
  }

  return (
    <button
      onClick={() => setMode('pixel')}
      title="Switch to Pixel mode"
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                 border border-slate-200 text-slate-600 hover:border-indigo-400
                 hover:text-indigo-600 transition-colors"
    >
      <Gamepad2 size={13} />
      Pixel
    </button>
  );
}
```

**Step 2: Commit**

```bash
git add services/web-dashboard/src/components/pixel/UiModeToggle.jsx
git commit -m "feat(pixel-ui): add UiModeToggle component for header"
```

---

### Task 4: personas.js + Sprite component

**Files:**
- Create: `services/web-dashboard/src/components/pixel/personas.js`
- Create: `services/web-dashboard/src/components/pixel/Sprite.jsx`

**Step 1: personas.js**

```js
/**
 * Agent persona definitions (ADR-047 — Prompt 4).
 *
 * Maps pipeline stages to RPG character names and emoji sprites.
 * Sprite states: idle | working | success | error
 */

export const AGENT_PERSONAS = {
  ingestion:  'archivist',
  retrieval:  'librarian',
  generation: 'writer',
  qa:         'guardian',
  enrichment: 'mage',
};

export const PERSONA_EMOJI = {
  archivist: { idle: '📜', working: '📖', success: '🗝️', error: '💀' },
  librarian: { idle: '🔍', working: '🔎', success: '📚', error: '❌' },
  writer:    { idle: '✍️', working: '📝', success: '📄', error: '💔' },
  guardian:  { idle: '🛡️', working: '⚔️', success: '✅', error: '🚫' },
  mage:      { idle: '🔮', working: '✨', success: '⭐', error: '💥' },
};

export const PERSONA_TITLE = {
  archivist: 'Archivist',
  librarian: 'Librarian',
  writer:    'Writer',
  guardian:  'Guardian',
  mage:      'Mage',
};

export const STAGE_LABEL = {
  ingestion:  'INGESTION',
  retrieval:  'RETRIEVAL',
  generation: 'GENERATION',
  qa:         'QA',
  enrichment: 'ENRICHMENT',
};

/** Infer pipeline stage from an agent log message. */
export function inferStageFromLog(message) {
  if (!message) return null;
  const m = message.toUpperCase();
  if (m.includes('[RAG]') || m.includes('RETRIEV') || m.includes('BM25') || m.includes('HYBRID'))
    return 'retrieval';
  if (m.includes('[LLM]') || m.includes('PROMPT') || m.includes('GENERAT') || m.includes('RENDER'))
    return 'generation';
  if (m.includes('[QUALITY]') || m.includes('[GUARD]') || m.includes('QUALITY') || m.includes('SANITIZ'))
    return 'qa';
  if (m.includes('CLAUDE') || m.includes('ENRICH') || m.includes('FACTPACK'))
    return 'enrichment';
  // Default — catalog/requirements reading is ingestion
  return 'ingestion';
}

/** Get the persona name for a given pipeline stage. */
export function getPersona(stage) {
  return AGENT_PERSONAS[stage] || 'archivist';
}
```

**Step 2: Sprite.jsx**

```jsx
/**
 * Sprite — Renders a pixel character (emoji-based, CSS-animated).
 *
 * Props:
 *   persona: "archivist" | "librarian" | "writer" | "guardian" | "mage"
 *   state:   "idle" | "working" | "success" | "error"
 *   size:    number (font-size in px, default 32)
 *   label:   show persona name below sprite (default false)
 */
import { PERSONA_EMOJI, PERSONA_TITLE } from './personas';

const STATE_CLASS = {
  idle:    '',
  working: 'pixel-working',
  success: 'pixel-success',
  error:   'pixel-error',
};

export default function Sprite({ persona = 'archivist', state = 'idle', size = 32, label = false }) {
  const emojiMap = PERSONA_EMOJI[persona] || PERSONA_EMOJI.archivist;
  const emoji    = emojiMap[state] ?? emojiMap.idle;
  const cls      = STATE_CLASS[state] ?? '';

  return (
    <div className="flex flex-col items-center gap-1">
      <span
        className={cls}
        style={{ fontSize: size, lineHeight: 1, display: 'block', userSelect: 'none' }}
        role="img"
        aria-label={`${PERSONA_TITLE[persona] ?? persona} — ${state}`}
      >
        {emoji}
      </span>
      {label && (
        <span className="pixel-text-sm" style={{ color: 'var(--pixel-muted)' }}>
          {PERSONA_TITLE[persona] ?? persona}
        </span>
      )}
    </div>
  );
}
```

**Step 3: Commit**

```bash
git add services/web-dashboard/src/components/pixel/personas.js \
        services/web-dashboard/src/components/pixel/Sprite.jsx
git commit -m "feat(pixel-ui): add agent personas mapping and Sprite component"
```

---

### Task 5: PipelineView component

**Files:**
- Create: `services/web-dashboard/src/components/pixel/PipelineView.jsx`

**Step 1: Implement**

```jsx
/**
 * PipelineView — Horizontal RPG-style pipeline visualization.
 *
 * Props:
 *   activeStage: "ingestion"|"retrieval"|"generation"|"qa"|"enrichment" | null
 *   stageStates: { [stage]: "idle"|"working"|"success"|"error" }
 *   isRunning: boolean
 */
import Sprite from './Sprite';
import { STAGE_LABEL, AGENT_PERSONAS } from './personas';

const PIPELINE_STAGES = ['ingestion', 'retrieval', 'generation', 'qa', 'enrichment'];

export default function PipelineView({ activeStage, stageStates = {}, isRunning = false }) {
  return (
    <div
      className="pixel-panel w-full"
      style={{ background: 'var(--pixel-surface)' }}
    >
      <p className="pixel-text-sm mb-3" style={{ color: 'var(--pixel-muted)' }}>
        ▶ AGENT PIPELINE
      </p>
      <div className="flex items-end justify-between gap-1 overflow-x-auto pb-1">
        {PIPELINE_STAGES.map((stage, i) => {
          const persona     = AGENT_PERSONAS[stage];
          const stageState  = stageStates[stage] ?? 'idle';
          const isActive    = stage === activeStage;
          const isDone      = stageState === 'success';
          const isError     = stageState === 'error';

          return (
            <div key={stage} className="flex items-center gap-1 flex-shrink-0">
              <div className="flex flex-col items-center gap-1">
                {/* Stage indicator dot */}
                <div
                  className="w-2 h-2 mb-0.5"
                  style={{
                    background: isError  ? 'var(--pixel-danger)'
                               : isDone  ? 'var(--pixel-primary)'
                               : isActive ? 'var(--pixel-accent)'
                               : 'var(--pixel-muted)',
                    boxShadow: isActive ? '0 0 6px var(--pixel-accent)' : 'none',
                  }}
                />

                <Sprite
                  persona={persona}
                  state={stageState}
                  size={isActive ? 30 : 22}
                  label={false}
                />

                <span
                  className="pixel-text-sm mt-0.5 text-center"
                  style={{
                    fontSize: '5px',
                    color: isActive ? 'var(--pixel-accent)'
                          : isDone  ? 'var(--pixel-primary)'
                          : 'var(--pixel-muted)',
                    maxWidth: 50,
                  }}
                >
                  {STAGE_LABEL[stage]}
                </span>
              </div>

              {/* Connector arrow (except after last stage) */}
              {i < PIPELINE_STAGES.length - 1 && (
                <span
                  className="pixel-text-sm self-center pb-5"
                  style={{
                    color: isDone ? 'var(--pixel-primary)' : 'var(--pixel-muted)',
                    fontSize: '8px',
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
```

**Step 2: Commit**

```bash
git add services/web-dashboard/src/components/pixel/PipelineView.jsx
git commit -m "feat(pixel-ui): add PipelineView RPG-style pipeline visualization"
```

---

### Task 6: PersonaNarrator message formatter

**Files:**
- Create: `services/web-dashboard/src/components/pixel/PersonaNarrator.js`

**Step 1: Implement**

```js
/**
 * PersonaNarrator — Transforms technical agent log messages into
 * RPG-style character narrations (ADR-047 — Prompt 9).
 *
 * Usage:
 *   narrateLog(log)  → { stage, text }
 */
import { inferStageFromLog, PERSONA_TITLE, getPersona } from './personas';

const PATTERNS = [
  // RAG / retrieval
  [/hybrid retrieval/i,          (m) => `🔍 ${t('librarian')} scours the archives for matching scrolls...`],
  [/\[RAG\].*assembled/i,        (m) => `📚 ${t('librarian')} assembled the context grimoire!`],
  [/query expansion/i,           (m) => `🔍 ${t('librarian')} expands the search with arcane queries...`],
  [/BM25|chromadb/i,             (m) => `🔍 ${t('librarian')} cross-references the knowledge vault...`],

  // LLM / generation
  [/calling.*generate|generate_with_retry/i, (m) => `✍️ ${t('writer')} begins inscribing the integration scroll...`],
  [/\[LLM\].*done|generated/i,   (m) => `✍️ ${t('writer')} has completed the first draft!`],
  [/prompt ready/i,              (m) => `✍️ ${t('writer')} prepares the quill...`],
  [/render.*section/i,           (m) => `✍️ ${t('writer')} renders the sacred sections...`],
  [/factpack.*extract/i,         (m) => `📜 ${t('archivist')} extracts structured facts from the lore...`],

  // Quality / guard
  [/quality.*OK|quality.*pass/i, (m) => `✅ ${t('guardian')} seals the document — quality approved!`],
  [/quality.*low|quality.*warn/i,(m) => `⚔️ ${t('guardian')} flags a potential weakness in the scroll...`],
  [/\[GUARD\]/i,                  (m) => `🛡️ ${t('guardian')} inspects the output for threats...`],

  // Enrichment / Claude
  [/enrich.*claude|claude.*enrich/i, (m) => `✨ ${t('mage')} invokes the Ancient API for enrichment...`],
  [/enriched|claude.*applied/i,  (m) => `⭐ ${t('mage')} infuses the scroll with arcane knowledge!`],

  // Approval / HITL
  [/approval.*queued|HITL/i,     (m) => `📜 ${t('archivist')} archives the scroll for Council review.`],

  // Progress / general
  [/processing.*integration/i,   (m) => `📜 ${t('archivist')} prepares integration entry...`],
  [/generation.*complete|completed/i, (m) => `🎉 Quest complete! All scrolls have been generated.`],
  [/error|failed/i,              (m) => `💀 ${t('guardian')} encountered a critical failure!`],
  [/timeout/i,                   (m) => `⌛ The ancient model takes too long to respond...`],
  [/started.*agent|agent.*started/i, (m) => `🗺️ ${t('archivist')} opens the quest log...`],
  [/TAG_CONFIRMED|processing.*requirement/i, (m) => `📜 ${t('archivist')} reads the requirements scroll...`],
];

function t(persona) {
  return PERSONA_TITLE[persona] ?? persona;
}

/**
 * @param {object} log - { level, message }
 * @returns {{ stage: string, text: string }}
 */
export function narrateLog(log) {
  const msg   = log?.message ?? '';
  const stage = inferStageFromLog(msg);

  for (const [pattern, formatter] of PATTERNS) {
    if (pattern.test(msg)) {
      return { stage, text: formatter(msg) };
    }
  }

  // Fallback: show shortened raw message
  const short = msg.length > 60 ? msg.slice(0, 60) + '…' : msg;
  return { stage, text: `› ${short}` };
}
```

**Step 2: Commit**

```bash
git add services/web-dashboard/src/components/pixel/PersonaNarrator.js
git commit -m "feat(pixel-ui): add PersonaNarrator RPG message formatter"
```

---

### Task 7: PixelAgentWorkspace page

**Files:**
- Create: `services/web-dashboard/src/components/pixel/PixelAgentWorkspace.jsx`

**Step 1: Implement**

Full pixel-mode agent workspace that uses `useAgentLogs` (same hook as classic) and renders:
- PipelineView with live stage detection from log messages
- Narrated log stream in a pixel terminal
- Pixel-styled Start/Stop buttons

```jsx
/**
 * PixelAgentWorkspace — 8-bit RPG-style agent workspace.
 * Replaces AgentWorkspacePage when ui_mode = "pixel".
 * Uses the same useAgentLogs / API hooks as classic mode.
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { useAgentLogs } from '../../hooks/useAgentLogs';
import PipelineView from './PipelineView';
import { narrateLog } from './PersonaNarrator';
import { inferStageFromLog } from './personas';

const PIPELINE_STAGES = ['ingestion', 'retrieval', 'generation', 'qa', 'enrichment'];

/** Build stage → state map from the last N narrated logs. */
function buildStageStates(logs) {
  const states = {};
  // Walk logs newest-first to find the most recent state per stage
  for (let i = logs.length - 1; i >= 0; i--) {
    const log   = logs[i];
    const stage = inferStageFromLog(log.message);
    if (!stage) continue;
    if (states[stage]) continue; // already have newest

    const lvl = (log.level ?? '').toUpperCase();
    if (lvl === 'ERROR')   states[stage] = 'error';
    else if (lvl === 'SUCCESS') states[stage] = 'success';
    else                        states[stage] = 'working';
  }
  return states;
}

export default function PixelAgentWorkspace() {
  const {
    logs, isRunning, trigger, cancel, triggerError, progress: apiProgress,
  } = useAgentLogs();

  const [llmProfile,   setLlmProfile]   = useState('default');
  const [localError,   setLocalError]   = useState(null);
  const [pinnedDocIds]                  = useState([]);
  const logEndRef = useRef(null);

  // Derive active stage from the last log entry
  const lastLog     = logs[logs.length - 1];
  const activeStage = isRunning && lastLog
    ? (inferStageFromLog(lastLog.message) ?? 'ingestion')
    : null;

  // Build stage states from log history
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

  const handleStop = () => cancel();

  const overall   = apiProgress?.overall;
  const questPct  = overall?.total > 0
    ? Math.round((overall.done / overall.total) * 100)
    : 0;

  return (
    <div className="space-y-4 p-2">

      {/* ── Pipeline visualization ── */}
      <PipelineView
        activeStage={activeStage}
        stageStates={stageStates}
        isRunning={isRunning}
      />

      {/* ── Quest control panel ── */}
      <div className="pixel-panel-accent">
        <p className="pixel-text-sm mb-1" style={{ color: 'var(--pixel-muted)' }}>
          ▶ COMMAND CENTER
        </p>

        {/* Profile selector */}
        {!isRunning && (
          <div className="flex gap-2 mb-3">
            {[
              { key: 'default', label: 'DEFAULT', sub: 'qwen2.5:14b' },
              { key: 'premium', label: 'PREMIUM',  sub: 'gemma4:26b' },
            ].map(({ key, label, sub }) => (
              <button
                key={key}
                onClick={() => setLlmProfile(key)}
                className={`pixel-button ${key === 'premium' ? 'pixel-button-accent' : ''}`}
                style={llmProfile === key ? {
                  background: key === 'premium' ? 'var(--pixel-accent)' : 'var(--pixel-primary)',
                  color: 'var(--pixel-bg)',
                } : {}}
              >
                {label}
                <span style={{ fontSize: 5, display: 'block', color: 'inherit', opacity: 0.7 }}>{sub}</span>
              </button>
            ))}
          </div>
        )}

        <div className="flex items-center justify-between gap-4">
          <div>
            {isRunning ? (
              <p className="pixel-text" style={{ color: 'var(--pixel-accent)' }}>
                ⚔ QUEST IN PROGRESS...
              </p>
            ) : (
              <p className="pixel-text" style={{ color: 'var(--pixel-muted)' }}>
                READY FOR ADVENTURE
              </p>
            )}
            {(localError || triggerError) && (
              <p className="pixel-text-sm" style={{ color: 'var(--pixel-danger)' }}>
                ✗ {localError || triggerError}
              </p>
            )}
          </div>

          {isRunning ? (
            <button onClick={handleStop} className="pixel-button pixel-button-danger">
              ■ ABORT
            </button>
          ) : (
            <button onClick={handleStart} className="pixel-button">
              ▶ START QUEST
            </button>
          )}
        </div>

        {/* Quest progress bar */}
        {isRunning && (
          <div className="mt-3">
            <div className="flex justify-between mb-1">
              <span className="pixel-text-sm" style={{ color: 'var(--pixel-muted)' }}>
                QUEST PROGRESS
              </span>
              <span className="pixel-text-sm" style={{ color: 'var(--pixel-accent)' }}>
                {questPct}%
              </span>
            </div>
            <div
              className="w-full h-3"
              style={{ background: 'var(--pixel-muted)', border: '1px solid var(--pixel-border)' }}
            >
              <div
                className="h-full transition-all duration-500"
                style={{
                  width: `${questPct}%`,
                  background: questPct >= 100 ? 'var(--pixel-primary)' : 'var(--pixel-accent)',
                }}
              />
            </div>
            {overall?.step && (
              <p className="pixel-text-sm mt-1" style={{ color: 'var(--pixel-muted)' }}>
                {overall.step}
              </p>
            )}
          </div>
        )}
      </div>

      {/* ── Narration log terminal ── */}
      <div className="pixel-panel">
        <p className="pixel-text-sm mb-2" style={{ color: 'var(--pixel-muted)' }}>
          ▶ QUEST LOG
        </p>
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
                    style={{
                      color: isErr ? 'var(--pixel-danger)' : isOk ? 'var(--pixel-primary)' : 'var(--pixel-text)',
                    }}
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
```

**Step 2: Commit**

```bash
git add services/web-dashboard/src/components/pixel/PixelAgentWorkspace.jsx
git commit -m "feat(pixel-ui): add PixelAgentWorkspace with pipeline + persona narration"
```

---

### Task 8: PixelDocumentView component

**Files:**
- Create: `services/web-dashboard/src/components/pixel/PixelDocumentView.jsx`

**Step 1: Implement**

Renders a document in "Quest Log" pixel style — wraps any content with pixel panel.

```jsx
/**
 * PixelDocumentView — Renders document content as a pixel-mode "Quest Scroll".
 * Used in ApprovalsPage and DocumentsPage when ui_mode = "pixel".
 *
 * Props:
 *   title:    string
 *   content:  string (markdown)
 *   status:   string (PENDING | APPROVED | REJECTED)
 *   actions:  ReactNode (approve/reject buttons from parent)
 */
import { MarkdownViewer } from '../ui/MarkdownViewer';

const STATUS_COLOR = {
  PENDING:  'var(--pixel-accent)',
  APPROVED: 'var(--pixel-primary)',
  REJECTED: 'var(--pixel-danger)',
};

const STATUS_LABEL = {
  PENDING:  '[ PENDING REVIEW ]',
  APPROVED: '[ APPROVED ]',
  REJECTED: '[ REJECTED ]',
};

export default function PixelDocumentView({ title, content, status, actions }) {
  return (
    <div className="pixel-panel space-y-4">
      {/* Header */}
      <div>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <p className="pixel-heading">{title ?? 'INTEGRATION SCROLL'}</p>
          {status && (
            <span
              className="pixel-text-sm"
              style={{ color: STATUS_COLOR[status] ?? 'var(--pixel-text)' }}
            >
              {STATUS_LABEL[status] ?? status}
            </span>
          )}
        </div>
        <div
          className="mt-1"
          style={{ height: 2, background: 'var(--pixel-border)', opacity: 0.4 }}
        />
      </div>

      {/* Artifact banner */}
      <div
        className="pixel-text-sm text-center py-2"
        style={{ background: 'rgba(74, 222, 128, 0.08)', borderTop: '1px dashed var(--pixel-border)', borderBottom: '1px dashed var(--pixel-border)' }}
      >
        ✦ ARTIFACT GENERATED — INTEGRATION DESIGN SCROLL ✦
      </div>

      {/* Content (rendered as markdown, inherits prose styles) */}
      <div
        className="overflow-y-auto pixel-scroll"
        style={{ maxHeight: 500, padding: '4px 0' }}
      >
        {content ? (
          <MarkdownViewer content={content} />
        ) : (
          <p className="pixel-text-sm" style={{ color: 'var(--pixel-muted)' }}>
            No content available.
          </p>
        )}
      </div>

      {/* Action buttons */}
      {actions && (
        <div className="flex gap-3 pt-2" style={{ borderTop: '1px solid var(--pixel-border)' }}>
          {actions}
        </div>
      )}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add services/web-dashboard/src/components/pixel/PixelDocumentView.jsx
git commit -m "feat(pixel-ui): add PixelDocumentView quest-log document renderer"
```

---

### Task 9: PixelSidebar component

**Files:**
- Create: `services/web-dashboard/src/components/pixel/PixelSidebar.jsx`

**Step 1: Implement**

Dark pixel-mode sidebar with same navigation as classic but styled with pixel CSS.

```jsx
/**
 * PixelSidebar — Navigation sidebar for pixel mode.
 * Same nav structure as Sidebar.jsx but using pixel design system.
 */
import { Zap, Upload, Globe, Bot, BookOpen, Database, List, FileText, CheckSquare, RotateCcw, BookMarked, Settings, Circle } from 'lucide-react';
import { useUiMode } from '../../context/UiModeContext';
import UiModeToggle from './UiModeToggle';

const NAV_GROUPS = [
  {
    label: 'WORKFLOW',
    items: [
      { id: 'requirements', label: 'Requirements', icon: Upload },
      { id: 'apis',         label: 'API Systems',  icon: Globe },
      { id: 'agent',        label: 'Agent',        icon: Bot },
    ],
  },
  {
    label: 'KNOWLEDGE',
    items: [
      { id: 'kb',       label: 'Knowledge Base',    icon: BookOpen },
      { id: 'ingestion',label: 'Ingestion Sources', icon: Database },
    ],
  },
  {
    label: 'RESULTS',
    items: [
      { id: 'catalog',   label: 'Catalog',   icon: List },
      { id: 'documents', label: 'Documents', icon: FileText },
      { id: 'approvals', label: 'Approvals', icon: CheckSquare },
    ],
  },
  {
    label: 'ADMIN',
    items: [
      { id: 'reset',       label: 'Reset',        icon: RotateCcw },
      { id: 'projectdocs', label: 'Project Docs', icon: BookMarked },
      { id: 'llmsettings', label: 'LLM Settings', icon: Settings },
    ],
  },
];

export default function PixelSidebar({ currentPage, onNavigate, services = {} }) {
  return (
    <div
      className="flex flex-col h-full overflow-hidden"
      style={{
        width: 200, minWidth: 200,
        background: 'var(--pixel-bg)',
        borderRight: '2px solid var(--pixel-border)',
      }}
    >
      {/* Brand */}
      <div
        className="flex items-center gap-2 px-4 py-4"
        style={{ borderBottom: '1px solid var(--pixel-border)' }}
      >
        <Zap size={16} style={{ color: 'var(--pixel-accent)' }} />
        <span className="pixel-text" style={{ color: 'var(--pixel-accent)', fontSize: 7 }}>
          INT. MATE
        </span>
      </div>

      {/* Nav groups */}
      <nav className="flex-1 overflow-y-auto p-2 space-y-3">
        {NAV_GROUPS.map(group => (
          <div key={group.label}>
            <p
              className="pixel-text-sm px-2 mb-1"
              style={{ color: 'var(--pixel-muted)', fontSize: 5 }}
            >
              {group.label}
            </p>
            {group.items.map(item => {
              const Icon    = item.icon;
              const isActive = currentPage === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onNavigate(item.id)}
                  className="w-full flex items-center gap-2 px-2 py-2 text-left"
                  style={{
                    background:  isActive ? 'var(--pixel-primary)' : 'transparent',
                    color:       isActive ? 'var(--pixel-bg)' : 'var(--pixel-text)',
                    border:      isActive ? '1px solid var(--pixel-border)' : '1px solid transparent',
                    borderRadius: 0,
                    cursor: 'pointer',
                  }}
                >
                  <Icon size={11} />
                  <span className="pixel-text-sm" style={{ fontSize: 6 }}>{item.label}</span>
                </button>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Service dots */}
      <div
        className="p-3 space-y-1"
        style={{ borderTop: '1px solid var(--pixel-border)' }}
      >
        {Object.entries(services).map(([svc, up]) => (
          <div key={svc} className="flex items-center gap-1.5">
            <Circle
              size={6}
              fill={up ? 'var(--pixel-primary)' : 'var(--pixel-danger)'}
              style={{ color: up ? 'var(--pixel-primary)' : 'var(--pixel-danger)' }}
            />
            <span className="pixel-text-sm" style={{ fontSize: 5, color: 'var(--pixel-muted)' }}>
              {svc.toUpperCase()}
            </span>
          </div>
        ))}
      </div>

      {/* Mode toggle */}
      <div
        className="p-3"
        style={{ borderTop: '1px solid var(--pixel-border)' }}
      >
        <UiModeToggle />
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add services/web-dashboard/src/components/pixel/PixelSidebar.jsx
git commit -m "feat(pixel-ui): add PixelSidebar navigation component"
```

---

### Task 10: Wire App.jsx and TopBar.jsx

**Files:**
- Modify: `services/web-dashboard/src/App.jsx`
- Modify: `services/web-dashboard/src/components/layout/TopBar.jsx`

**Step 1: Update App.jsx**

1. Import `UiModeProvider` and `useUiMode`.
2. Wrap providers: add `UiModeProvider` as the outermost wrapper (after QueryClientProvider or alongside LoadingProvider).
3. In the layout: use `useUiMode` to conditionally render `PixelSidebar` vs `Sidebar`.
4. For `AgentWorkspacePage`, render `PixelAgentWorkspace` in pixel mode.

Key change in `renderPage()`:
```jsx
// Add at top of renderPage():
const { mode } = useUiMode();   // Note: must be called inside component, not in renderPage() fn

// OR: handle the pixel agent page in the App component directly:
const pageContent = currentPage === 'agent' && mode === 'pixel'
  ? <PixelAgentWorkspace />
  : renderPage(currentPage);
```

Wrap the root div with UiModeProvider:
```jsx
return (
  <QueryClientProvider client={queryClient}>
    <UiModeProvider>
      <LoadingProvider>
        ...
      </LoadingProvider>
    </UiModeProvider>
  </QueryClientProvider>
);
```

Use `useUiMode()` inside the `App` function body (not in renderPage which is outside the component):
```jsx
const { mode } = useUiMode(); // <-- Add this
```

Switch sidebar and page based on mode:
```jsx
{mode === 'pixel' ? (
  <PixelSidebar currentPage={currentPage} onNavigate={setCurrentPage} services={services} />
) : (
  <Sidebar currentPage={currentPage} onNavigate={setCurrentPage} services={services} />
)}
```

For main page content:
```jsx
{currentPage === 'agent' && mode === 'pixel' ? (
  <PixelAgentWorkspace />
) : (
  renderPage(currentPage)
)}
```

**Step 2: Update TopBar.jsx**

Add `UiModeToggle` in the right section between notification bell and user dropdown:

```jsx
import UiModeToggle from '../pixel/UiModeToggle';
// ...
// In the right section div:
<UiModeToggle />
```

The classic mode toggle appears as a styled button (Gamepad2 icon + "Pixel" text).
The pixel mode toggle appears as a `pixel-button` (Monitor icon + "Classic" text).

**Step 3: Commit**

```bash
git add services/web-dashboard/src/App.jsx \
        services/web-dashboard/src/components/layout/TopBar.jsx
git commit -m "feat(pixel-ui): wire UiModeProvider into App, conditional sidebar + agent workspace"
```

---

### Task 11: Write ADR-047

**File:** `docs/adr/ADR-047-pixel-ui-mode.md`

Document the dual UI mode decision, persona mapping, and frontend-only scope.

**Commit:**

```bash
git add docs/adr/ADR-047-pixel-ui-mode.md
git commit -m "docs(adr): ADR-047 Pixel UI Mode — 8-bit gamified dual UI system"
```

---

### Task 12: Update documentation

**Files:**
- `docs/architecture_specification.md` — add ADR-047 row
- `docs/functional-guide.md` — add Pixel UI section

**Commit:**

```bash
git add docs/architecture_specification.md docs/functional-guide.md
git commit -m "docs: document Pixel UI mode (ADR-047)"
```

---
