/**
 * API Client — Communicates with the unified Integration Agent
 *
 * Service URLs are derived from the current page hostname so the same
 * build works on localhost and on any remote host (e.g. AWS EC2).
 */

const _HOST = window.location.hostname;

const API = {
    AGENT: `http://${_HOST}:4003`,
    PLM:   `http://${_HOST}:4001`,
    PIM:   `http://${_HOST}:4002`,

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
    async getCatalogEntries() {
        const resp = await fetch(`${this.AGENT}/api/v1/catalog/integrations`, { headers: this.headers() });
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

    // ── System Health ──
    async checkServices() {
        const services = [
            { name: 'Agent', url: `${this.AGENT}/health` },
            { name: 'PLM Mock', url: `${this.PLM}/health` },
            { name: 'PIM Mock', url: `${this.PIM}/health` }
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
