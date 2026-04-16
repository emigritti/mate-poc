/**
 * PersonaNarrator — Transforms technical agent log messages into
 * RPG-style character narrations (ADR-047 — Prompt 9).
 *
 * Usage:
 *   narrateLog(log)  → { stage, text }
 */
import { inferStageFromLog, PERSONA_TITLE } from './personas';

const PATTERNS = [
  // RAG / retrieval
  [/hybrid retrieval/i,              () => `🔍 ${t('librarian')} scours the archives for matching scrolls...`],
  [/\[RAG\].*assembled/i,            () => `📚 ${t('librarian')} assembled the context grimoire!`],
  [/query expansion/i,               () => `🔍 ${t('librarian')} expands the search with arcane queries...`],
  [/BM25|chromadb/i,                 () => `🔍 ${t('librarian')} cross-references the knowledge vault...`],

  // LLM / generation
  [/calling.*generate|generate_with_retry/i, () => `✍️ ${t('writer')} begins inscribing the integration scroll...`],
  [/\[LLM\].*done|\[LLM\].*generated/i,      () => `✍️ ${t('writer')} has completed the first draft!`],
  [/prompt ready/i,                           () => `✍️ ${t('writer')} prepares the quill...`],
  [/render.*section/i,                        () => `✍️ ${t('writer')} renders the sacred sections...`],
  [/factpack.*extract/i,                      () => `📜 ${t('archivist')} extracts structured facts from the lore...`],

  // Quality / guard
  [/quality.*OK|quality.*pass/i,  () => `✅ ${t('guardian')} seals the document — quality approved!`],
  [/quality.*low|quality.*warn/i, () => `⚔️ ${t('guardian')} flags a potential weakness in the scroll...`],
  [/\[GUARD\]/i,                   () => `🛡️ ${t('guardian')} inspects the output for threats...`],

  // Enrichment / Claude
  [/enrich.*claude|claude.*enrich/i, () => `✨ ${t('mage')} invokes the Ancient API for enrichment...`],
  [/enriched|claude.*applied/i,      () => `⭐ ${t('mage')} infuses the scroll with arcane knowledge!`],

  // Approval / HITL
  [/approval.*queued|HITL/i,           () => `📜 ${t('archivist')} archives the scroll for Council review.`],

  // Progress / general
  [/processing.*integration/i,         () => `📜 ${t('archivist')} prepares integration entry...`],
  [/generation.*complete|completed/i,  () => `🎉 Quest complete! All scrolls have been generated.`],
  [/error|failed/i,                    () => `💀 ${t('guardian')} encountered a critical failure!`],
  [/timeout/i,                         () => `⌛ The ancient model takes too long to respond...`],
  [/started.*agent|agent.*started/i,   () => `🗺️ ${t('archivist')} opens the quest log...`],
  [/TAG_CONFIRMED|processing.*requirement/i, () => `📜 ${t('archivist')} reads the requirements scroll...`],
];

function t(persona) {
  return PERSONA_TITLE[persona] ?? persona;
}

/**
 * @param {{ level?: string, message?: string }} log
 * @returns {{ stage: string|null, text: string }}
 */
export function narrateLog(log) {
  const msg   = log?.message ?? '';
  const stage = inferStageFromLog(msg);

  for (const [pattern, formatter] of PATTERNS) {
    if (pattern.test(msg)) {
      return { stage, text: formatter() };
    }
  }

  // Fallback: show shortened raw message
  const short = msg.length > 60 ? msg.slice(0, 60) + '…' : msg;
  return { stage, text: `› ${short}` };
}
