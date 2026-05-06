/**
 * API Client — Communicates with the unified Integration Agent
 *
 * All requests are routed through the nginx gateway on the same origin
 * (port 8080). No hardcoded hostnames or ports are needed.
 */

// Gateway-relative: tutta la comunicazione via porta 8080 (same-origin).
// Routing: /agent/* → integration-agent:3003 | /plm/* → plm-mock:3001
const API = {
    AGENT: '/agent',
    PLM:   '/plm',

    headers() {
        return { 'Content-Type': 'application/json' };
    },

    // ── Requirements Upload ──
    async uploadRequirements(file) {
        const formData = new FormData();
        formData.append('file', file);
        const resp = await fetch(`${this.AGENT}/api/v1/requirements/upload`, { method: 'POST', body: formData });
        return resp.json();
    },

    async getRequirements() {
        const resp = await fetch(`${this.AGENT}/api/v1/requirements`, { headers: this.headers() });
        return resp.json();
    },

    // ── Agent Processing ──
    async triggerAgent() {
        const resp = await fetch(`${this.AGENT}/api/v1/agent/trigger`, { method: 'POST', headers: this.headers() });
        return resp.json();
    },

    async getAgentLogs() {
        const resp = await fetch(`${this.AGENT}/api/v1/agent/logs`, { headers: this.headers() });
        return resp.json();
    },

    // ── Catalog & Documents ──
    async getCatalogEntries({ projectId, domain, accentureRef } = {}) {
        const params = new URLSearchParams();
        if (projectId)    params.set('project_id', projectId);
        if (domain)       params.set('domain', domain);
        if (accentureRef) params.set('accenture_ref', accentureRef);
        const qs = params.toString() ? `?${params}` : '';
        const resp = await fetch(`${this.AGENT}/api/v1/catalog/integrations${qs}`, {
            headers: this.headers(),
        });
        return resp.json();
    },

    async getFunctionalSpec(id) {
        const resp = await fetch(`${this.AGENT}/api/v1/catalog/integrations/${id}/functional-spec`, { headers: this.headers() });
        return resp.json();
    },

    async getTechnicalSpec(id) {
        const resp = await fetch(`${this.AGENT}/api/v1/catalog/integrations/${id}/technical-spec`, { headers: this.headers() });
        return resp.json();
    },

    // ── HITL Approvals (RAG) ──
    async getPendingApprovals() {
        const resp = await fetch(`${this.AGENT}/api/v1/approvals/pending`, { headers: this.headers() });
        return resp.json();
    },

    async approveDocument(id, finalMarkdown) {
        const resp = await fetch(`${this.AGENT}/api/v1/approvals/${id}/approve`, {
            method: 'POST',
            headers: this.headers(),
            body: JSON.stringify({ final_markdown: finalMarkdown })
        });
        return resp.json();
    },

    async rejectDocument(id, feedback) {
        const resp = await fetch(`${this.AGENT}/api/v1/approvals/${id}/reject`, {
            method: 'POST',
            headers: this.headers(),
            body: JSON.stringify({ feedback: feedback })
        });
        return resp.json();
    },

    async triggerTechnical(integrationId) {
        const resp = await fetch(`${this.AGENT}/api/v1/agent/trigger-technical/${encodeURIComponent(integrationId)}`, {
            method: 'POST',
            headers: this.headers(),
        });
        return resp.json();
    },

    // ── Agent Control ──
    async cancelAgent() {
        const resp = await fetch(`${this.AGENT}/api/v1/agent/cancel`, { method: 'POST', headers: this.headers() });
        return resp.json();
    },

    // ── Admin Reset ──
    async resetRequirements() {
        const resp = await fetch(`${this.AGENT}/api/v1/admin/reset/requirements`, { method: 'DELETE', headers: this.headers() });
        return resp.json();
    },

    async resetMongoDB() {
        const resp = await fetch(`${this.AGENT}/api/v1/admin/reset/mongodb`, { method: 'DELETE', headers: this.headers() });
        return resp.json();
    },

    async resetChromaDB() {
        const resp = await fetch(`${this.AGENT}/api/v1/admin/reset/chromadb`, { method: 'DELETE', headers: this.headers() });
        return resp.json();
    },

    async resetAll() {
        const resp = await fetch(`${this.AGENT}/api/v1/admin/reset/all`, { method: 'DELETE', headers: this.headers() });
        return resp.json();
    },

    // ── Projects (ADR-025) ──
    async createProject(data) {
        const resp = await fetch(`${this.AGENT}/api/v1/projects`, {
            method: 'POST',
            headers: this.headers(),
            body: JSON.stringify(data),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        return resp.json();
    },

    async listProjects() {
        const resp = await fetch(`${this.AGENT}/api/v1/projects`, { headers: this.headers() });
        return resp.json();
    },

    async getProject(prefix) {
        const resp = await fetch(`${this.AGENT}/api/v1/projects/${encodeURIComponent(prefix)}`, {
            headers: this.headers(),
        });
        return resp.json();
    },

    async finalizeRequirements(projectId) {
        const resp = await fetch(`${this.AGENT}/api/v1/requirements/finalize`, {
            method: 'POST',
            headers: this.headers(),
            body: JSON.stringify({ project_id: projectId }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        return resp.json();
    },

    // ── System Health ──
    async checkServices() {
        const services = [
            { name: 'Agent', url: `${this.AGENT}/health` },
            { name: 'PLM Mock', url: `${this.PLM}/health` }
        ];

        const results = [];
        for (const svc of services) {
            try {
                const resp = await fetch(svc.url, { signal: AbortSignal.timeout(3000) });
                results.push({ ...svc, healthy: resp.ok });
            } catch {
                results.push({ ...svc, healthy: false });
            }
        }
        return results;
    }
};
