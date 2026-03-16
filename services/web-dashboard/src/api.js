const getBase = () => `http://${window.location.hostname}:4003`;

export const API = {
  requirements: {
    upload: (file) => {
      const fd = new FormData();
      fd.append('file', file);
      return fetch(`${getBase()}/api/v1/requirements/upload`, { method: 'POST', body: fd });
    },
    list: () => fetch(`${getBase()}/api/v1/requirements`),
  },

  agent: {
    trigger: () => fetch(`${getBase()}/api/v1/agent/trigger`, { method: 'POST' }),
    logs: (offset = 0) => fetch(`${getBase()}/api/v1/agent/logs?offset=${offset}`),
    cancel: () => fetch(`${getBase()}/api/v1/agent/cancel`, { method: 'POST' }),
  },

  catalog: {
    list: () => fetch(`${getBase()}/api/v1/catalog/integrations`),
    functionalSpec: (id) => fetch(`${getBase()}/api/v1/catalog/integrations/${id}/functional-spec`),
    technicalSpec: (id) => fetch(`${getBase()}/api/v1/catalog/integrations/${id}/technical-spec`),
    suggestTags: (id) => fetch(`${getBase()}/api/v1/catalog/integrations/${id}/suggest-tags`),
    confirmTags: (id, tags) =>
      fetch(`${getBase()}/api/v1/catalog/integrations/${id}/confirm-tags`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tags }),
      }),
  },

  approvals: {
    pending: () => fetch(`${getBase()}/api/v1/approvals/pending`),
    approve: (id, content) =>
      fetch(`${getBase()}/api/v1/approvals/${id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Backend ApproveRequest expects final_markdown, not content
        body: JSON.stringify({ final_markdown: content }),
      }),
    reject: (id, feedback) =>
      fetch(`${getBase()}/api/v1/approvals/${id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback }),
      }),
  },

  admin: {
    reset: (target) =>
      fetch(`${getBase()}/api/v1/admin/reset/${target}`, { method: 'DELETE' }),
  },

  projectDocs: {
    list: () => fetch(`${getBase()}/api/v1/admin/docs`),
    content: (path) => fetch(`${getBase()}/api/v1/admin/docs/${path}`),
  },

  kb: {
    upload: (file) => {
      const fd = new FormData();
      fd.append('file', file);
      return fetch(`${getBase()}/api/v1/kb/upload`, { method: 'POST', body: fd });
    },
    list: () => fetch(`${getBase()}/api/v1/kb/documents`),
    get: (id) => fetch(`${getBase()}/api/v1/kb/documents/${id}`),
    delete: (id) => fetch(`${getBase()}/api/v1/kb/documents/${id}`, { method: 'DELETE' }),
    updateTags: (id, tags) => fetch(`${getBase()}/api/v1/kb/documents/${id}/tags`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tags }),
    }),
    search: (q, n = 5) => fetch(`${getBase()}/api/v1/kb/search?q=${encodeURIComponent(q)}&n=${n}`),
    stats: () => fetch(`${getBase()}/api/v1/kb/stats`),
  },

  health: {
    check: (port) => fetch(`http://${window.location.hostname}:${port}/health`),
  },
};
