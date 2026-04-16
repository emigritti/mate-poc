/**
 * Sprite — Renders a pixel character using emoji + CSS animation (ADR-047 — Prompt 5).
 *
 * Props:
 *   persona  "archivist" | "librarian" | "writer" | "guardian" | "mage"
 *   state    "idle" | "working" | "success" | "error"
 *   size     font-size in px (default 28)
 *   label    show persona name below (default false)
 */
import { PERSONA_EMOJI, PERSONA_TITLE } from './personas';

const STATE_CLASS = {
  idle:    '',
  working: 'pixel-working',
  success: 'pixel-success',
  error:   'pixel-error',
};

export default function Sprite({ persona = 'archivist', state = 'idle', size = 28, label = false }) {
  const emojiMap = PERSONA_EMOJI[persona] ?? PERSONA_EMOJI.archivist;
  const emoji    = emojiMap[state] ?? emojiMap.idle;
  const cls      = STATE_CLASS[state] ?? '';

  return (
    <div className="flex flex-col items-center gap-0.5">
      <span
        className={cls}
        style={{ fontSize: size, lineHeight: 1, display: 'block', userSelect: 'none' }}
        role="img"
        aria-label={`${PERSONA_TITLE[persona] ?? persona} — ${state}`}
      >
        {emoji}
      </span>
      {label && (
        <span
          className="pixel-text-sm"
          style={{ color: 'var(--pixel-muted)', fontSize: '5px' }}
        >
          {PERSONA_TITLE[persona] ?? persona}
        </span>
      )}
    </div>
  );
}
