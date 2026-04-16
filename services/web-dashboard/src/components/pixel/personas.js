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
  return 'ingestion';
}

/** Get the persona name for a given pipeline stage. */
export function getPersona(stage) {
  return AGENT_PERSONAS[stage] || 'archivist';
}
