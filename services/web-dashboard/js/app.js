/**
 * App Controller — Dashboard SPA logic
 */

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    loadPage('requirements');
    checkServicesLoop();
    updateClock();
    setInterval(updateClock, 1000);
});

// ── Navigation ──────────────────────────────────────

function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            document.querySelector('.nav-item.active')?.classList.remove('active');
            item.classList.add('active');
            loadPage(item.dataset.page);
        });
    });
}

function loadPage(page) {
    const titles = {
        requirements: 'Upload Requirements',
        apis: 'API Systems',
        agent: 'Agent Workspace',
        catalog: 'Integration Catalog',
        documents: 'Generated Docs',
        approvals: 'HITL Approvals (RAG)',
    };
    document.getElementById('pageTitle').textContent = titles[page] || page;

    const loaders = {
        requirements: renderRequirements,
        apis: renderApis,
        agent: renderAgentWorkspace,
        catalog: renderCatalog,
        documents: renderDocuments,
        approvals: renderApprovals,
    };
    (loaders[page] || renderRequirements)();
}

// ── Requirements Page ───────────────────────────────

async function renderRequirements() {
    const area = document.getElementById('contentArea');
    area.innerHTML = `
        <div class="card" style="margin-bottom: 20px;">
            <div class="card-title">Upload New Requirements</div>
            <div class="card-body" style="margin-top:12px;">
                <input type="file" id="csvFile" accept=".csv" class="btn" style="background:var(--bg-secondary);color:var(--text-main); margin-right: 12px;"/>
                <button class="btn btn-primary" onclick="uploadCsv()">Upload CSV</button>
            </div>
            <div id="uploadResult" style="margin-top:12px;"></div>
        </div>
        <div id="requirementsList"><div class="loading">Loading current requirements...</div></div>
    `;
    loadRequirementsList();
}

async function uploadCsv() {
    const fileInput = document.getElementById('csvFile');
    const res = document.getElementById('uploadResult');
    if (!fileInput.files[0]) {
        res.innerHTML = '<span style="color:var(--error)">Please select a file.</span>';
        return;
    }
    res.innerHTML = '<span style="color:var(--info)">Uploading and parsing...</span>';
    try {
        const data = await API.uploadRequirements(fileInput.files[0]);
        res.innerHTML = `<span style="color:var(--success)">✅ Successfully parsed ${data.total_parsed || 0} requirements.</span>`;
        loadRequirementsList();
    } catch (e) {
        res.innerHTML = `<span style="color:var(--error)">❌ Error: ${e.message}</span>`;
    }
}

async function loadRequirementsList() {
    const list = document.getElementById('requirementsList');
    try {
        const data = await API.getRequirements();
        const reqs = data?.data || [];
        if (reqs.length === 0) {
            list.innerHTML = `<div class="empty-state"><div class="icon">📤</div><h3>No pending requirements</h3><p>Upload a CSV file to begin.</p></div>`;
            return;
        }
        list.innerHTML = `<table class="data-table">
            <thead><tr><th>ID</th><th>Source</th><th>Target</th><th>Category</th><th>Description</th></tr></thead>
            <tbody>${reqs.map(r => `<tr>
                <td><code>${r.req_id}</code></td>
                <td><span class="badge badge-primary">${r.source_system}</span></td>
                <td><span class="badge badge-info" style="background:var(--info)">${r.target_system}</span></td>
                <td>${r.category}</td>
                <td>${truncate(r.description, 60)}</td>
            </tr>`).join('')}</tbody>
        </table>`;
    } catch (e) { list.innerHTML = `<div class="empty-state"><p>${e.message}</p></div>`; }
}

// ── APIs Page ───────────────────────────────────────

function renderApis() {
    const area = document.getElementById('contentArea');
    area.innerHTML = `
        <div class="card-grid">
            <div class="card">
                <div class="card-title">PLM Mock API</div>
                <div class="card-body">Source system for Product Lifecycle Management data, including core product attributes and technical specs.</div>
                <div class="card-footer" style="margin-top:16px;">
                    <a href="http://${location.hostname}:4001/docs" target="_blank" class="btn btn-sm btn-primary">📖 View Swagger</a>
                </div>
            </div>
            <div class="card">
                <div class="card-title">PIM Mock API</div>
                <div class="card-body">Target system for Product Information Management. Receives enriched product data for marketing and sales channels.</div>
                <div class="card-footer" style="margin-top:16px;">
                    <a href="http://${location.hostname}:4002/docs" target="_blank" class="btn btn-sm btn-info" style="background:var(--info)">📖 View Swagger</a>
                </div>
            </div>
        </div>
    `;
}

// ── Agent Workspace Page ────────────────────────────

let agentPollInterval = null;

function renderAgentWorkspace() {
    const area = document.getElementById('contentArea');
    area.innerHTML = `
        <div class="execute-form" style="margin-bottom: 20px;">
            <div class="form-group">
                <label class="form-label">🚀 Trigger Agentic Generation</label>
                <div style="font-size: 0.9em; color: var(--text-muted); margin-bottom: 12px;">
                    The agent will process all loaded requirements, query the ChromaDB vector store for similar past integrations to formulate few-shot examples, and invoke the Ollama LLM to generate functional and technical Markdown specifications.
                </div>
                <button class="btn btn-primary" onclick="triggerAgent()" id="agentBtn">Start Agent Processing</button>
            </div>
        </div>
        <div class="card" style="background: var(--bg-secondary);">
            <div class="card-title">Agent Logs terminal</div>
            <div class="card-body">
                <pre id="agentLogs" style="background: #1e1e1e; color: #00ff00; padding: 16px; border-radius: 4px; height: 300px; overflow-y: auto; font-family: monospace; font-size: 13px;">Waiting for agent to start...</pre>
            </div>
        </div>
    `;
    startAgentPolling();
}

async function triggerAgent() {
    const btn = document.getElementById('agentBtn');
    btn.disabled = true;
    btn.textContent = 'Agent Running...';
    try {
        await API.triggerAgent();
    } catch (e) {
        document.getElementById('agentLogs').innerHTML += `\n<span style="color:var(--error)">Error triggering agent: ${e.message}</span>`;
        btn.disabled = false;
        btn.textContent = 'Start Agent Processing';
    }
}

function startAgentPolling() {
    if (agentPollInterval) clearInterval(agentPollInterval);
    agentPollInterval = setInterval(async () => {
        if (document.getElementById('agentLogs')) {
            try {
                const logsData = await API.getAgentLogs();
                const logs = logsData?.logs || [];
                const logsEl = document.getElementById('agentLogs');
                if (logs.length > 0) {
                    logsEl.innerHTML = logs.map(l => {
                        let color = '#00ff00'; // Default line color
                        if (l.includes('[RAG]') || l.includes('Vector')) color = '#00bcd4';
                        if (l.includes('[LLM]') || l.includes('Ollama')) color = '#ffeb3b';
                        if (l.includes('ERROR')) color = '#f44336';
                        return `<div style="color:${color}">${l}</div>`;
                    }).join('');
                    logsEl.scrollTop = logsEl.scrollHeight;
                }

                // If the last log indicates completion, reset button
                if (logs.length > 0 && (logs[logs.length - 1].includes('Generation completed') || logs[logs.length - 1].includes('All tasks finished'))) {
                    const btn = document.getElementById('agentBtn');
                    if (btn) {
                        btn.disabled = false;
                        btn.textContent = 'Start Agent Processing';
                    }
                }
            } catch (e) {
                // Ignore poll errors
            }
        } else {
            clearInterval(agentPollInterval);
        }
    }, 2000);
}

// ── Catalog Page ────────────────────────────────────

async function renderCatalog() {
    const area = document.getElementById('contentArea');
    area.innerHTML = '<div class="loading">Loading catalog integrations...</div>';

    try {
        const data = await API.getCatalogEntries();
        const items = data?.data || [];

        if (items.length === 0) {
            area.innerHTML = `<div class="empty-state"><div class="icon">📋</div><h3>No Catalog Entries Yet</h3><p>Trigger the agent to generate the catalog from the requirements.</p></div>`;
            return;
        }

        area.innerHTML = `<div class="card-grid">${items.map(i => `
            <div class="card">
                <div class="card-header">
                    <div>
                        <div class="card-title">${i.name}</div>
                        <div class="card-subtitle">${i.id} · ${i.type}</div>
                    </div>
                    <span class="badge badge-${i.status === 'generated' ? 'success' : 'info'}">${i.status}</span>
                </div>
                <div class="card-body">
                    ${i.source?.system || '?'} → ${i.target?.system || '?'}
                </div>
                <div class="card-footer">
                    ${(i.requirements || []).map(r => `<span class="badge badge-primary">${r}</span>`).join('')}
                </div>
            </div>
        `).join('')}</div>`;
    } catch (e) {
        area.innerHTML = `<div class="empty-state"><div class="icon">⚠️</div><h3>Connection Error</h3><p>${e.message}</p></div>`;
    }
}

// ── Documents Page ──────────────────────────────────

async function renderDocuments() {
    const area = document.getElementById('contentArea');
    area.innerHTML = '<div class="loading">Loading generated documents...</div>';
    try {
        const data = await API.getCatalogEntries();
        const items = data?.data || [];
        if (items.length === 0) {
            area.innerHTML = `<div class="empty-state"><div class="icon">📄</div><h3>No Documents</h3><p>Trigger the agent to generate integration documents.</p></div>`;
            return;
        }
        area.innerHTML = `<div class="card-grid">${items.map(i => `
            <div class="card">
                <div class="card-title">${i.name || i.id}</div>
                <div class="card-subtitle">${i.id}</div>
                <div class="card-footer" style="margin-top:12px">
                    <button class="btn btn-sm btn-primary" onclick="viewDoc('${i.id}', 'functional')">📋 Functional Spec</button>
                    <button class="btn btn-sm btn-info" style="background:var(--info)" onclick="viewDoc('${i.id}', 'technical')">🔧 Technical Spec</button>
                </div>
            </div>`).join('')}</div><div id="docViewer" style="margin-top:20px; background:var(--bg-secondary); padding:20px; border-radius:8px; display:none;"></div>`;
    } catch (e) { area.innerHTML = `<div class="empty-state"><div class="icon">⚠️</div><p>${e.message}</p></div>`; }
}

async function viewDoc(id, type) {
    const viewer = document.getElementById('docViewer');
    viewer.style.display = 'block';
    viewer.innerHTML = '<div class="loading">Loading markdown...</div>';
    try {
        const data = type === 'functional' ? await API.getFunctionalSpec(id) : await API.getTechnicalSpec(id);
        const mdContent = data?.data?.content || '*No content available.*';
        viewer.innerHTML = `<div class="markdown-body">${marked.parse(mdContent)}</div>`;
    } catch (e) { viewer.innerHTML = `<p style="color:var(--error)">Failed to load document: ${e.message}</p>`; }
}


// ── Approvals Page (HITL) ───────────────────────────

async function renderApprovals() {
    const area = document.getElementById('contentArea');
    area.innerHTML = '<div class="loading">Loading pending approvals...</div>';
    try {
        const data = await API.getPendingApprovals();
        const items = data?.data || [];
        if (items.length === 0) {
            area.innerHTML = `<div class="empty-state"><div class="icon">✅</div><h3>No Pending Approvals</h3><p>When the LLM generates a document, it pauses here for human review before saving to the RAG Vector DB.</p></div>`;
            return;
        }
        area.innerHTML = `
            <div style="display:flex; gap:20px; height: 75vh;">
                <div style="flex:1; overflow-y:auto; border-right: 1px solid var(--border-color); padding-right: 20px;">
                    <h3 style="margin-bottom:16px;">Pending Reviews</h3>
                    ${items.map(a => `
                        <div class="card" style="margin-bottom:12px; cursor:pointer;" onclick="loadApprovalReview('${a.id}')">
                            <div class="card-title">${a.integration_id}</div>
                            <div class="card-subtitle">Type: ${a.doc_type}</div>
                            <div class="card-body" style="font-size:12px; margin-top:8px;">Generated: ${new Date(a.generated_at).toLocaleString()}</div>
                        </div>
                    `).join('')}
                </div>
                <div id="approvalEditor" style="flex:2; display:flex; flex-direction:column;">
                    <div class="empty-state"><p>Select a document to review and edit.</p></div>
                </div>
            </div>
        `;
    } catch (e) { area.innerHTML = `<div class="empty-state"><div class="icon">⚠️</div><p>${e.message}</p></div>`; }
}

async function loadApprovalReview(id) {
    const editor = document.getElementById('approvalEditor');
    editor.innerHTML = '<div class="loading">Loading document...</div>';
    try {
        // Fetch approval item details from API to populate textarea
        const data = await API.getPendingApprovals();
        const item = (data?.data || []).find(a => a.id === id);
        if (!item) throw new Error("Approval not found");

        editor.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <h3>Review: ${item.integration_id} (${item.doc_type})</h3>
                <div>
                    <button class="btn btn-sm btn-error" onclick="rejectHitl('${id}')">Reject (Retry)</button>
                    <button class="btn btn-sm btn-success" onclick="approveHitl('${id}')">Approve & Save to RAG</button>
                </div>
            </div>
            <textarea id="hitlMarkdown" style="flex:1; width:100%; padding:12px; font-family:monospace; background:var(--bg-main); color:var(--text-main); border:1px solid var(--border-color); border-radius:4px; resize:none;">${item.content}</textarea>
        `;
    } catch (e) { editor.innerHTML = `<p style="color:var(--error)">Failed to load: ${e.message}</p>`; }
}

async function approveHitl(id) {
    const md = document.getElementById('hitlMarkdown').value;
    try {
        await API.approveDocument(id, md);
        renderApprovals();
    } catch (e) { alert("Error approving: " + e.message); }
}

async function rejectHitl(id) {
    const feedback = prompt("Please provide feedback for the agent to retry the generation:");
    if (feedback === null) return;
    try {
        await API.rejectDocument(id, feedback);
        renderApprovals();
    } catch (e) { alert("Error rejecting: " + e.message); }
}

// ── Service Health Check ────────────────────────────

async function checkServicesLoop() {
    try {
        const services = await API.checkServices();
        const healthy = services.filter(s => s.healthy).length;
        const total = services.length;
        const dot = document.querySelector('.status-dot');
        const statusText = document.querySelector('.service-status span:last-child');
        dot.className = `status-dot ${healthy === total ? 'healthy' : healthy > 0 ? '' : 'error'}`;
        statusText.textContent = `${healthy}/${total} services`;
        document.getElementById('statusServices').textContent = `Services: ${healthy}/${total} healthy`;
    } catch { /* ignore */ }
    setTimeout(checkServicesLoop, 15000);
}

function updateClock() {
    document.getElementById('statusTime').textContent = new Date().toLocaleTimeString();
}

// ── Utilities ───────────────────────────────────────
function truncate(str, len) { return (str || '').length > len ? str.substring(0, len) + '...' : str || ''; }
