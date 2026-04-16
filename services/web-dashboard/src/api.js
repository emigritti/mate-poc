/**
 * API Client — Gateway-relative paths
 *
 * Tutte le chiamate passano per il nginx gateway su porta 8080 (same-origin).
 * Non è necessario aprire porte separate (4003, 4001, 4002) sul firewall.
 *
 * Routing gateway:
 *   /agent/*      → integration-agent:3003
 *   /plm/*        → plm-mock:3001
 *   /pim/*        → pim-mock:3002
 *   /ingestion/*  → ingestion-platform:4006
 */

const AGENT     = '/agent';
const PLM       = '/plm';
const PIM       = '/pim';
const INGESTION = '/ingestion';

export const API = {
  requirements: {
    upload: (file) => {
      const fd = new FormData();
      fd.append('file', file);
      return fetch(`${AGENT}/api/v1/requirements/upload`, { method: 'POST', body: fd });
    },
    list: () => fetch(`${AGENT}/api/v1/requirements`),
    patch: (reqId, mandatory) =>
      fetch(`${AGENT}/api/v1/requirements/${encodeURIComponent(reqId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mandatory }),
      }),
    finalize: (projectId, fieldOverrides = null) =>
      fetch(`${AGENT}/api/v1/requirements/finalize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          ...(fieldOverrides && Object.keys(fieldOverrides).length > 0
            ? { field_overrides: fieldOverrides }
            : {}),
        }),
      }),
  },

  projects: {
    create: (body) =>
      fetch(`${AGENT}/api/v1/projects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    list: () => fetch(`${AGENT}/api/v1/projects`),
    get: (prefix) => fetch(`${AGENT}/api/v1/projects/${encodeURIComponent(prefix)}`),
  },

  agent: {
    trigger: (pinnedDocIds = [], llmProfile = 'default') => fetch(`${AGENT}/api/v1/agent/trigger`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pinned_doc_ids: pinnedDocIds, llm_profile: llmProfile }),
    }),
    logs: (offset = 0) => fetch(`${AGENT}/api/v1/agent/logs?offset=${offset}`),
    cancel: () => fetch(`${AGENT}/api/v1/agent/cancel`, { method: 'POST' }),
  },

  catalog: {
    list: () => fetch(`${AGENT}/api/v1/catalog/integrations`),
    integrationSpec: (id) => fetch(`${AGENT}/api/v1/catalog/integrations/${encodeURIComponent(id)}/integration-spec`),
    suggestTags: (id) => fetch(`${AGENT}/api/v1/catalog/integrations/${id}/suggest-tags`),
    confirmTags: (id, tags) =>
      fetch(`${AGENT}/api/v1/catalog/integrations/${id}/confirm-tags`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tags }),
      }),
  },

  approvals: {
    pending: () => fetch(`${AGENT}/api/v1/approvals/pending`),
    approve: (id, content) =>
      fetch(`${AGENT}/api/v1/approvals/${id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ final_markdown: content }),
      }),
    reject: (id, feedback) =>
      fetch(`${AGENT}/api/v1/approvals/${id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback }),
      }),
    regenerate: (id) =>
      fetch(`${AGENT}/api/v1/approvals/${id}/regenerate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      }),
    buildImprovementPrompt: (sectionTitle, sectionContent) =>
      fetch(`${AGENT}/api/v1/approvals/build-improvement-prompt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ section_title: sectionTitle, section_content: sectionContent }),
      }),
    runImprovement: (sectionTitle, sectionContent, improvementPrompt) =>
      fetch(`${AGENT}/api/v1/approvals/run-improvement`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          section_title: sectionTitle,
          section_content: sectionContent,
          improvement_prompt: improvementPrompt,
        }),
      }),
  },

  documents: {
    list: () =>
      fetch(`${AGENT}/api/v1/documents`),
    promoteToKB: (docId) =>
      fetch(`${AGENT}/api/v1/documents/${encodeURIComponent(docId)}/promote-to-kb`, {
        method: 'POST',
      }),
    removeFromKB: (docId) =>
      fetch(`${AGENT}/api/v1/documents/${encodeURIComponent(docId)}/from-kb`, {
        method: 'DELETE',
      }),
  },

  admin: {
    reset: (target) =>
      fetch(`${AGENT}/api/v1/admin/reset/${target}`, { method: 'DELETE' }),
  },

  projectDocs: {
    list: () => fetch(`${AGENT}/api/v1/admin/docs`),
    content: (path) => fetch(`${AGENT}/api/v1/admin/docs/${path}`),
  },

  llmSettings: {
    get:   ()     => fetch(`${AGENT}/api/v1/admin/llm-settings`),
    patch: (body) => fetch(`${AGENT}/api/v1/admin/llm-settings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    reset: ()     => fetch(`${AGENT}/api/v1/admin/llm-settings/reset`, { method: 'POST' }),
  },

  kb: {
    upload: (file) => {
      const fd = new FormData();
      fd.append('file', file);
      return fetch(`${AGENT}/api/v1/kb/upload`, { method: 'POST', body: fd });
    },
    list: () => fetch(`${AGENT}/api/v1/kb/documents`),
    get: (id) => fetch(`${AGENT}/api/v1/kb/documents/${id}`),
    delete: (id) => fetch(`${AGENT}/api/v1/kb/documents/${id}`, { method: 'DELETE' }),
    updateTags: (id, tags) => fetch(`${AGENT}/api/v1/kb/documents/${id}/tags`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tags }),
    }),
    addUrl: ({ url, title, tags }) => fetch(`${AGENT}/api/v1/kb/add-url`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, title, tags }),
    }),
    search: (q, n = 5) => fetch(`${AGENT}/api/v1/kb/search?q=${encodeURIComponent(q)}&n=${n}`),
    stats: () => fetch(`${AGENT}/api/v1/kb/stats`),
  },

  ingestion: {
    listSources:        ()         => fetch(`${INGESTION}/api/v1/sources`),
    createSource:       (body)     => fetch(`${INGESTION}/api/v1/sources`, {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify(body),
                                      }),
    deleteSource:       (id)       => fetch(`${INGESTION}/api/v1/sources/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    pauseSource:        (id)       => fetch(`${INGESTION}/api/v1/sources/${encodeURIComponent(id)}/pause`, { method: 'PUT' }),
    activateSource:     (id)       => fetch(`${INGESTION}/api/v1/sources/${encodeURIComponent(id)}/activate`, { method: 'PUT' }),
    triggerIngest:      (id, type) => fetch(`${INGESTION}/api/v1/ingest/${type}/${encodeURIComponent(id)}`, { method: 'POST' }),
    getRun:             (runId)    => fetch(`${INGESTION}/api/v1/runs/${encodeURIComponent(runId)}`),
    getSourceRuns:      (id)       => fetch(`${INGESTION}/api/v1/sources/${encodeURIComponent(id)}/runs`),
    getSourceSnapshots: (id)       => fetch(`${INGESTION}/api/v1/sources/${encodeURIComponent(id)}/snapshots`),
    getSourceChunks:    (id)       => fetch(`${INGESTION}/api/v1/sources/${encodeURIComponent(id)}/chunks`),
    health:             ()         => fetch(`${INGESTION}/health`),
  },

  health: {
    // service: 'agent' | 'plm' | 'pim' | 'ingestion'
    check: (service) => {
      const paths = { agent: AGENT, plm: PLM, pim: PIM, ingestion: INGESTION };
      const base = paths[service] ?? `/${service}`;
      return fetch(`${base}/health`);
    },
  },
};
