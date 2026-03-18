/**
 * API Client — Gateway-relative paths
 *
 * Tutte le chiamate passano per il nginx gateway su porta 8080 (same-origin).
 * Non è necessario aprire porte separate (4003, 4001, 4002) sul firewall.
 *
 * Routing gateway:
 *   /agent/* → integration-agent:3003
 *   /plm/*   → plm-mock:3001
 *   /pim/*   → pim-mock:3002
 */

const AGENT = '/agent';
const PLM   = '/plm';
const PIM   = '/pim';

export const API = {
  requirements: {
    upload: (file) => {
      const fd = new FormData();
      fd.append('file', file);
      return fetch(`${AGENT}/api/v1/requirements/upload`, { method: 'POST', body: fd });
    },
    list: () => fetch(`${AGENT}/api/v1/requirements`),
  },

  agent: {
    trigger: () => fetch(`${AGENT}/api/v1/agent/trigger`, { method: 'POST' }),
    logs: (offset = 0) => fetch(`${AGENT}/api/v1/agent/logs?offset=${offset}`),
    cancel: () => fetch(`${AGENT}/api/v1/agent/cancel`, { method: 'POST' }),
  },

  catalog: {
    list: () => fetch(`${AGENT}/api/v1/catalog/integrations`),
    functionalSpec: (id) => fetch(`${AGENT}/api/v1/catalog/integrations/${id}/functional-spec`),
    technicalSpec: (id) => fetch(`${AGENT}/api/v1/catalog/integrations/${id}/technical-spec`),
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
  },

  documents: {
    list: () =>
      fetch(`${AGENT}/api/v1/documents`).then(r => r.json()),
    promoteToKB: (docId) =>
      fetch(`${AGENT}/api/v1/documents/${encodeURIComponent(docId)}/promote-to-kb`, {
        method: 'POST',
      }).then(r => r.json()),
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
    search: (q, n = 5) => fetch(`${AGENT}/api/v1/kb/search?q=${encodeURIComponent(q)}&n=${n}`),
    stats: () => fetch(`${AGENT}/api/v1/kb/stats`),
  },

  health: {
    // service: 'agent' | 'plm' | 'pim'
    check: (service) => {
      const paths = { agent: AGENT, plm: PLM, pim: PIM };
      const base = paths[service] ?? `/${service}`;
      return fetch(`${base}/health`);
    },
  },
};
