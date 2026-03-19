/**
 * App Controller — Dashboard SPA logic
 *
 * Security: all server-supplied values injected into innerHTML are HTML-escaped
 * via escapeHtml() to prevent stored XSS (ADR-017 / OWASP A03 / F-04, F-05, F-06).
 * Textarea content is set via the .value DOM property, not innerHTML interpolation.
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
        reset: '🗑️ Reset Tools',
    };
    document.getElementById('pageTitle').textContent = titles[page] || page;

    const loaders = {
        requirements: renderRequirements,
        apis: renderApis,
        agent: renderAgentWorkspace,
        catalog: renderCatalog,
        documents: renderDocuments,
        approvals: renderApprovals,
        reset: renderReset,
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
        <div id="tag-confirmation-container"></div>
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
        res.innerHTML = `<span style="color:var(--info)">✔ Parsed ${escapeHtml(String(data.total_parsed || 0))} requirements. Compila le informazioni progetto per continuare.</span>`;
        loadRequirementsList();
        // Show project modal — tag confirmation runs inside modal after finalize
        showProjectModal(data.preview || []);
    } catch (e) {
        res.innerHTML = `<span style="color:var(--error)">❌ Error: ${escapeHtml(e.message)}</span>`;
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
        // F-05: all CSV-sourced fields escaped to prevent stored XSS (ADR-017)
        list.innerHTML = `<table class="data-table">
            <thead><tr><th>ID</th><th>Source</th><th>Target</th><th>Category</th><th>Description</th></tr></thead>
            <tbody>${reqs.map(r => `<tr>
                <td><code>${escapeHtml(r.req_id)}</code></td>
                <td><span class="badge badge-primary">${escapeHtml(r.source_system)}</span></td>
                <td><span class="badge badge-info" style="background:var(--info)">${escapeHtml(r.target_system)}</span></td>
                <td>${escapeHtml(r.category)}</td>
                <td>${escapeHtml(truncate(r.description, 60))}</td>
            </tr>`).join('')}</tbody>
        </table>`;
    } catch (e) { list.innerHTML = `<div class="empty-state"><p>${escapeHtml(e.message)}</p></div>`; }
}

// ── Project Modal (ADR-025) ───────────────────────────────────────────────────

async function showProjectModal(preview) {
    document.getElementById('projectModal')?.remove();

    const integrationLines = (preview || []).map(p =>
        `<li><span class="badge badge-primary">${escapeHtml(p.source)}</span> → <span class="badge badge-info" style="background:var(--info)">${escapeHtml(p.target)}</span></li>`
    ).join('');

    const modal = document.createElement('div');
    modal.id = 'projectModal';
    modal.style.cssText = `
        position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;
        display:flex;align-items:center;justify-content:center;`;
    modal.innerHTML = `
        <div style="background:var(--bg-secondary);border-radius:12px;padding:32px;width:480px;
                    max-width:95vw;box-shadow:0 20px 60px rgba(0,0,0,.4);">
            <h3 style="margin:0 0 8px;color:var(--text-primary)">📋 Informazioni Progetto</h3>
            <p style="margin:0 0 20px;color:var(--text-secondary);font-size:14px;">
                Rilevate <strong>${escapeHtml(String((preview || []).length))}</strong> integration pair(s):
                <ul style="margin:4px 0 0 16px;padding:0;">${integrationLines}</ul>
            </p>
            <div style="display:flex;flex-direction:column;gap:14px;">
                <div>
                    <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px;">
                        Nome Cliente <span style="color:var(--error)">*</span>
                    </label>
                    <input id="pm-client" type="text" placeholder="Acme Corp"
                        style="width:100%;box-sizing:border-box;padding:8px 12px;border-radius:6px;
                               border:1px solid var(--border);background:var(--bg-primary);
                               color:var(--text-primary);font-size:14px;" />
                </div>
                <div>
                    <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px;">
                        Dominio Integrazione <span style="color:var(--error)">*</span>
                    </label>
                    <input id="pm-domain" type="text" placeholder="Fashion Retail"
                        style="width:100%;box-sizing:border-box;padding:8px 12px;border-radius:6px;
                               border:1px solid var(--border);background:var(--bg-primary);
                               color:var(--text-primary);font-size:14px;" />
                </div>
                <div>
                    <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px;">
                        Prefisso
                        <span style="color:var(--text-secondary);font-size:11px;">(auto-generato · max 3 car. · A-Z0-9)</span>
                    </label>
                    <div style="display:flex;gap:8px;align-items:center;">
                        <input id="pm-prefix" type="text" maxlength="3" placeholder="ACM"
                            style="width:80px;padding:8px 12px;border-radius:6px;
                                   border:1px solid var(--border);background:var(--bg-primary);
                                   color:var(--text-primary);font-size:14px;font-weight:700;
                                   text-transform:uppercase;" />
                        <span id="pm-prefix-status" style="font-size:13px;flex:1;"></span>
                    </div>
                </div>
                <div>
                    <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px;">
                        Descrizione <span style="font-size:11px;">(opzionale)</span>
                    </label>
                    <input id="pm-desc" type="text" placeholder="Opzionale"
                        style="width:100%;box-sizing:border-box;padding:8px 12px;border-radius:6px;
                               border:1px solid var(--border);background:var(--bg-primary);
                               color:var(--text-primary);font-size:14px;" />
                </div>
                <div>
                    <label style="font-size:13px;color:var(--text-secondary);display:block;margin-bottom:4px;">
                        Riferimento Accenture <span style="font-size:11px;">(opzionale)</span>
                    </label>
                    <input id="pm-ref" type="text" placeholder="Mario Rossi"
                        style="width:100%;box-sizing:border-box;padding:8px 12px;border-radius:6px;
                               border:1px solid var(--border);background:var(--bg-primary);
                               color:var(--text-primary);font-size:14px;" />
                </div>
            </div>
            <div style="margin-top:24px;display:flex;justify-content:flex-end;gap:12px;">
                <button id="pm-cancel" class="btn btn-secondary">Annulla</button>
                <button id="pm-confirm" class="btn btn-primary" disabled>Conferma →</button>
            </div>
        </div>`;

    document.body.appendChild(modal);
    _resolvedProjectId = null;

    const clientInput  = document.getElementById('pm-client');
    const prefixInput  = document.getElementById('pm-prefix');
    const domainInput  = document.getElementById('pm-domain');
    const prefixStatus = document.getElementById('pm-prefix-status');
    const confirmBtn   = document.getElementById('pm-confirm');

    function updateConfirmState() {
        const ok = clientInput.value.trim() && domainInput.value.trim() && prefixInput.value.trim();
        // confirmBtn.disabled is also set by checkPrefix for clash case; only enable if all fields filled
        if (!ok) confirmBtn.disabled = true;
        else if (_resolvedProjectId === false) confirmBtn.disabled = true; // clash
        else confirmBtn.disabled = false;
    }

    async function checkPrefix() {
        const prefix = prefixInput.value.toUpperCase().trim();
        if (!prefix || !/^[A-Z0-9]{1,3}$/.test(prefix)) {
            prefixStatus.innerHTML = '';
            _resolvedProjectId = null;
            updateConfirmState();
            return;
        }
        try {
            const data = await API.getProject(prefix);
            const found = data?.data;
            if (!found) throw new Error('not found');
            const clientName = clientInput.value.trim();
            if (found.client_name.toLowerCase() === clientName.toLowerCase()) {
                prefixStatus.innerHTML = `<span style="color:var(--success)">✅ <strong>${escapeHtml(found.client_name)}</strong> esiste già. I documenti saranno aggiunti al progetto <strong>${escapeHtml(prefix)}</strong>.</span>`;
                _resolvedProjectId = prefix;  // existing project, skip POST
            } else {
                prefixStatus.innerHTML = `<span style="color:var(--error)">❌ Prefisso già usato da <strong>${escapeHtml(found.client_name)}</strong>. Modifica il prefisso.</span>`;
                _resolvedProjectId = false;  // clash — block confirm
            }
        } catch (_) {
            // 404 or network error → prefix is free
            prefixStatus.innerHTML = '';
            _resolvedProjectId = null;
        }
        updateConfirmState();
    }

    clientInput.addEventListener('input', () => {
        prefixInput.value = generatePrefix(clientInput.value);
        clearTimeout(_prefixCheckTimer);
        _prefixCheckTimer = setTimeout(checkPrefix, 400);
        updateConfirmState();
    });

    prefixInput.addEventListener('input', () => {
        prefixInput.value = prefixInput.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
        clearTimeout(_prefixCheckTimer);
        _prefixCheckTimer = setTimeout(checkPrefix, 400);
        updateConfirmState();
    });

    domainInput.addEventListener('input', updateConfirmState);

    document.getElementById('pm-cancel').addEventListener('click', () => modal.remove());

    document.getElementById('pm-confirm').addEventListener('click', async () => {
        const prefix       = prefixInput.value.toUpperCase().trim();
        const clientName   = clientInput.value.trim();
        const domain       = domainInput.value.trim();
        const description  = document.getElementById('pm-desc').value.trim() || null;
        const accentureRef = document.getElementById('pm-ref').value.trim() || null;

        confirmBtn.disabled = true;
        confirmBtn.textContent = 'Salvataggio...';

        try {
            // If prefix is free (_resolvedProjectId is null), create the project
            if (_resolvedProjectId === null) {
                await API.createProject({
                    prefix,
                    client_name: clientName,
                    domain,
                    description,
                    accenture_ref: accentureRef,
                });
            }
            const finalizeData = await API.finalizeRequirements(prefix);
            modal.remove();
            const res = document.getElementById('uploadResult');
            if (res) {
                res.innerHTML = `<span style="color:var(--success)">✅ ${escapeHtml(String(finalizeData.integrations_created))} integrazione/i create sotto <strong>${escapeHtml(prefix)}</strong> · ${escapeHtml(clientName)}.</span>`;
            }
            loadRequirementsList();
            fetchAndShowTagConfirmation();
        } catch (err) {
            confirmBtn.disabled = false;
            confirmBtn.textContent = 'Conferma →';
            prefixStatus.innerHTML = `<span style="color:var(--error)">❌ ${escapeHtml(err.message)}</span>`;
        }
    });

    setTimeout(() => clientInput.focus(), 50);
}

// ── Tag Confirmation ─────────────────────────────────

async function fetchAndShowTagConfirmation() {
    const container = document.getElementById('tag-confirmation-container');
    if (!container) return;
    try {
        const response = await fetch(`${API.AGENT}/api/v1/catalog/integrations`);
        const data = await response.json();
        const pendingEntries = (data.data || []).filter(e => e.status === 'PENDING_TAG_REVIEW');
        if (pendingEntries.length === 0) { container.innerHTML = ''; return; }

        container.innerHTML = '<h3 style="margin: 16px 0 8px; color: var(--warning, #f0ad4e);">⚠️ Confirm Integration Tags Before Generating</h3>';
        for (const entry of pendingEntries) {
            const suggestResp = await fetch(`${API.AGENT}/api/v1/catalog/integrations/${encodeURIComponent(entry.id)}/suggest-tags`);
            const suggestData = await suggestResp.json();
            const panel = buildTagPanel(entry, suggestData.suggested_tags || []);
            container.appendChild(panel);
        }
    } catch (e) {
        if (container) container.innerHTML = `<p style="color:var(--error)">Could not load tag suggestions: ${escapeHtml(e.message)}</p>`;
    }
}

function buildTagPanel(entry, suggestedTags) {
    const div = document.createElement('div');
    div.className = 'tag-panel';
    div.dataset.entryId = entry.id;

    const title = document.createElement('h4');
    title.textContent = escapeHtml(entry.name);
    title.style.marginBottom = '8px';
    div.appendChild(title);

    const chipContainer = document.createElement('div');
    chipContainer.className = 'tag-chips';
    suggestedTags.forEach(tag => {
        const chip = document.createElement('span');
        chip.className = 'tag-chip selected';
        chip.textContent = escapeHtml(tag);
        chip.dataset.tag = tag;
        chip.addEventListener('click', () => chip.classList.toggle('selected'));
        chipContainer.appendChild(chip);
    });
    div.appendChild(chipContainer);

    const customContainer = document.createElement('div');
    customContainer.className = 'custom-tags';
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Add custom tag (max 3 custom)';
    input.maxLength = 50;
    input.className = 'tag-custom-input';
    const addBtn = document.createElement('button');
    addBtn.textContent = '+ Add';
    addBtn.className = 'btn btn-sm';
    addBtn.addEventListener('click', () => {
        const customChips = div.querySelectorAll('.tag-chip.custom');
        if (customChips.length >= 3) return;
        const val = input.value.trim();
        if (!val) return;
        const chip = document.createElement('span');
        chip.className = 'tag-chip selected custom';
        chip.textContent = escapeHtml(val);
        chip.dataset.tag = val;
        chip.addEventListener('click', () => chip.classList.toggle('selected'));
        chipContainer.appendChild(chip);
        input.value = '';
        if (div.querySelectorAll('.tag-chip.custom').length >= 3) {
            input.disabled = true;
            addBtn.disabled = true;
        }
    });
    customContainer.appendChild(input);
    customContainer.appendChild(addBtn);
    div.appendChild(customContainer);

    const confirmBtn = document.createElement('button');
    confirmBtn.className = 'btn btn-primary confirm-tags-btn';
    confirmBtn.textContent = 'Confirm Tags \u2192';
    confirmBtn.style.marginTop = '10px';
    confirmBtn.addEventListener('click', () => confirmTagsForEntry(div, entry.id));
    div.appendChild(confirmBtn);

    return div;
}

async function confirmTagsForEntry(panel, entryId) {
    const selected = [...panel.querySelectorAll('.tag-chip.selected')].map(c => c.dataset.tag);
    if (selected.length === 0) { alert('Select at least one tag.'); return; }
    try {
        const resp = await fetch(`${API.AGENT}/api/v1/catalog/integrations/${encodeURIComponent(entryId)}/confirm-tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tags: selected }),
        });
        if (resp.ok) {
            panel.innerHTML = `<p class="tags-confirmed">&#10003; Tags confirmed: ${selected.map(escapeHtml).join(', ')}</p>`;
        } else {
            const err = await resp.json();
            alert(`Error: ${escapeHtml(err.detail || 'Unknown error')}`);
        }
    } catch (e) {
        alert(`Network error: ${escapeHtml(e.message)}`);
    }
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
let _cachedLogs     = [];    // log lines from last successful poll — survives navigation
let _logsOffset     = 0;     // first visible index in _cachedLogs (set by clearAgentLogs)
let _isAgentRunning = false; // agent running state — survives navigation

// ── Catalog filter + project modal state (ADR-025) ───────────────────────────
let _catalogFilterProjectId = '';
let _catalogFilterDomain    = '';
let _catalogFilterAccRef    = '';
let _prefixCheckTimer       = null;
let _resolvedProjectId      = null;  // set when existing project confirmed in modal
let _catalogFilterTimer     = null;

function renderAgentWorkspace() {
    const area = document.getElementById('contentArea');
    area.innerHTML = `
        <div class="execute-form" style="margin-bottom: 20px;">
            <div class="form-group">
                <label class="form-label">🚀 Trigger Agentic Generation</label>
                <div style="font-size: 0.9em; color: var(--text-muted); margin-bottom: 12px;">
                    The agent will process all loaded requirements, query the ChromaDB vector store for similar past integrations to formulate few-shot examples, and invoke the Ollama LLM to generate functional and technical Markdown specifications.
                </div>
                <div style="display:flex; gap:12px; align-items:center;">
                    <button class="btn btn-primary" onclick="triggerAgent()" id="agentBtn">Start Agent Processing</button>
                    <button class="btn btn-error" onclick="stopAgent()" id="stopBtn" style="display:none;">⛔ Stop Agent</button>
                </div>
            </div>
        </div>
        <div class="card" style="background: var(--bg-secondary);">
            <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
                <span>Agent Logs terminal</span>
                <button onclick="clearAgentLogs()"
                        style="font-size:0.78em; padding:3px 10px; background:var(--bg-main);
                               color:var(--text-muted); border:1px solid var(--border-color);
                               border-radius:4px; cursor:pointer;">
                    🗑️ Clear Logs
                </button>
            </div>
            <div class="card-body">
                <pre id="agentLogs" style="background: #1e1e1e; color: #00ff00; padding: 16px; border-radius: 4px; height: 300px; overflow-y: auto; font-family: monospace; font-size: 13px;">Waiting for agent to start...</pre>
            </div>
        </div>
    `;
    // Restore button state immediately — no flicker when navigating back to this page
    _setAgentRunning(_isAgentRunning);
    // Restore visible log lines immediately — no blank flash before the first poll
    _renderLogLines(_cachedLogs.slice(_logsOffset));
    startAgentPolling();
}

function _setAgentRunning(running) {
    _isAgentRunning = running;              // persist across navigation
    const agentBtn = document.getElementById('agentBtn');
    const stopBtn  = document.getElementById('stopBtn');
    if (!agentBtn || !stopBtn) return;
    agentBtn.disabled    = running;
    agentBtn.textContent = running ? 'Agent Running...' : 'Start Agent Processing';
    stopBtn.style.display = running ? 'inline-block' : 'none';
}

/**
 * Render the visible slice of LogEntry objects into #agentLogs.
 * Colors are driven by the `level` field from the backend — no keyword scanning.
 * F-04: all values HTML-escaped (ADR-017 / OWASP A03).
 */
function _renderLogLines(logs) {
    const logsEl = document.getElementById('agentLogs');
    if (!logsEl || !logs || logs.length === 0) return;
    const COLORS = {
        INFO:    '#00ff00',
        LLM:     '#ffeb3b',
        RAG:     '#00bcd4',
        SUCCESS: '#69f0ae',
        WARN:    '#ff9800',
        ERROR:   '#f44336',
        CANCEL:  '#e65100',
    };
    logsEl.innerHTML = logs.map(e => {
        const color = COLORS[e.level] ?? '#00ff00';
        const ts    = new Date(e.ts).toLocaleTimeString();
        return `<div style="color:${color}">` +
            `<span style="opacity:0.5">[${escapeHtml(ts)}]</span> ` +
            `<span style="opacity:0.6;font-size:0.85em">[${escapeHtml(e.level)}]</span> ` +
            `${escapeHtml(e.message)}</div>`;
    }).join('');
    logsEl.scrollTop = logsEl.scrollHeight;
}

/**
 * Clear the log display without touching the backend.
 * Sets _logsOffset so future polls show only NEW lines arriving after this point.
 */
function clearAgentLogs() {
    _logsOffset = _cachedLogs.length;
    const logsEl = document.getElementById('agentLogs');
    if (logsEl) logsEl.innerHTML = '<span style="color:var(--text-muted)">Logs cleared.</span>';
}

async function triggerAgent() {
    _setAgentRunning(true);
    try {
        await API.triggerAgent();
    } catch (e) {
        document.getElementById('agentLogs').innerHTML += `\n<span style="color:var(--error)">Error triggering agent: ${escapeHtml(e.message)}</span>`;
        _setAgentRunning(false);
    }
}

async function stopAgent() {
    const stopBtn = document.getElementById('stopBtn');
    stopBtn.disabled = true;
    stopBtn.textContent = 'Stopping...';
    try {
        await API.cancelAgent();
    } catch (e) {
        const logsEl = document.getElementById('agentLogs');
        if (logsEl) logsEl.innerHTML += `\n<span style="color:var(--error)">Error stopping agent: ${escapeHtml(e.message)}</span>`;
    } finally {
        stopBtn.disabled = false;
    }
}

function startAgentPolling() {
    if (agentPollInterval) clearInterval(agentPollInterval);
    agentPollInterval = setInterval(async () => {
        if (document.getElementById('agentLogs')) {
            try {
                const logsData = await API.getAgentLogs();
                const logs = logsData?.logs || [];
                _cachedLogs = logs;                          // keep cache in sync with backend
                _renderLogLines(logs.slice(_logsOffset));    // honour user-initiated clear

                // Re-enable Start button when agent finishes or is cancelled
                const isDone = logs.length > 0 && logs.some(e =>
                    (e.level === 'SUCCESS' && e.message.includes('completed'))
                    || e.level === 'CANCEL'
                );
                if (isDone) {
                    _setAgentRunning(false);
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
        // Fetch projects for filter dropdown
        const projectsData = await API.listProjects();
        const allProjects  = projectsData?.data || [];

        // Fetch catalog entries with active filters
        const catalogData = await API.getCatalogEntries({
            projectId:    _catalogFilterProjectId || undefined,
            domain:       _catalogFilterDomain    || undefined,
            accentureRef: _catalogFilterAccRef    || undefined,
        });
        const items = catalogData?.data || [];

        // Build project dropdown options
        const projectOptions = [
            '<option value="">Tutti i clienti</option>',
            ...allProjects.map(p =>
                `<option value="${escapeHtml(p.prefix)}"${_catalogFilterProjectId === p.prefix ? ' selected' : ''}>
                    ${escapeHtml(p.prefix)} · ${escapeHtml(p.client_name)}
                </option>`
            )
        ].join('');

        // Filter bar
        const filterBar = `
            <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;
                        margin-bottom:20px;padding:16px;background:var(--bg-secondary);
                        border-radius:8px;border:1px solid var(--border);">
                <div>
                    <label style="font-size:12px;color:var(--text-secondary);display:block;margin-bottom:4px;">🏢 Cliente</label>
                    <select id="cf-project" onchange="onCatalogFilterChange()"
                        style="padding:6px 10px;border-radius:6px;border:1px solid var(--border);
                               background:var(--bg-primary);color:var(--text-primary);font-size:13px;">
                        ${projectOptions}
                    </select>
                </div>
                <div>
                    <label style="font-size:12px;color:var(--text-secondary);display:block;margin-bottom:4px;">🏷️ Dominio</label>
                    <input id="cf-domain" type="text" value="${escapeHtml(_catalogFilterDomain)}"
                        placeholder="Partial match..." oninput="onCatalogFilterChange()"
                        style="padding:6px 10px;border-radius:6px;border:1px solid var(--border);
                               background:var(--bg-primary);color:var(--text-primary);font-size:13px;width:150px;" />
                </div>
                <div>
                    <label style="font-size:12px;color:var(--text-secondary);display:block;margin-bottom:4px;">👤 Ref. Accenture</label>
                    <input id="cf-ref" type="text" value="${escapeHtml(_catalogFilterAccRef)}"
                        placeholder="Partial match..." oninput="onCatalogFilterChange()"
                        style="padding:6px 10px;border-radius:6px;border:1px solid var(--border);
                               background:var(--bg-primary);color:var(--text-primary);font-size:13px;width:150px;" />
                </div>
                <button class="btn btn-secondary" onclick="resetCatalogFilters()"
                    style="padding:6px 14px;font-size:13px;align-self:flex-end;">Reset filtri</button>
            </div>`;

        // Cards
        const cards = items.length === 0
            ? `<div class="empty-state"><div class="icon">📋</div><h3>Nessun risultato</h3>
               <p>Nessuna integrazione trovata con i filtri selezionati.<br>
               Carica un CSV e compila le info progetto per iniziare.</p></div>`
            : `<div class="card-grid">${items.map(i => {
                const proj = i._project || null;
                return `
                <div class="card">
                    <div class="card-header">
                        <div>
                            <div class="card-title">
                                ${i.project_id && i.project_id !== 'LEGACY'
                                    ? `<span style="background:var(--primary);color:#fff;border-radius:4px;
                                                   padding:2px 7px;font-size:11px;font-weight:700;
                                                   margin-right:6px;">${escapeHtml(i.project_id)}</span>`
                                    : ''}
                                ${escapeHtml(i.name)}
                            </div>
                            <div class="card-subtitle">${escapeHtml(i.id)} · ${escapeHtml(i.type)}</div>
                        </div>
                        <span class="badge badge-${i.status === 'generated' ? 'success' : 'info'}">${escapeHtml(i.status)}</span>
                    </div>
                    <div class="card-body">
                        ${escapeHtml(i.source?.system || '?')} → ${escapeHtml(i.target?.system || '?')}
                    </div>
                    ${proj ? `
                    <div style="padding:6px 0 4px;font-size:12px;color:var(--text-secondary);
                                border-top:1px solid var(--border);margin-top:8px;line-height:1.6;">
                        🏢 <strong>${escapeHtml(proj.client_name)}</strong> · ${escapeHtml(proj.domain)}
                        ${proj.accenture_ref ? `<br>👤 ${escapeHtml(proj.accenture_ref)}` : ''}
                    </div>` : ''}
                    <div class="card-footer">
                        ${(i.requirements || []).map(r => `<span class="badge badge-primary">${escapeHtml(r)}</span>`).join('')}
                    </div>
                </div>`;
            }).join('')}</div>`;

        area.innerHTML = filterBar + cards;

    } catch (e) {
        area.innerHTML = `<div class="empty-state"><div class="icon">⚠️</div>
            <h3>Connection Error</h3><p>${escapeHtml(e.message)}</p></div>`;
    }
}

function onCatalogFilterChange() {
    _catalogFilterProjectId = document.getElementById('cf-project')?.value || '';
    _catalogFilterDomain    = document.getElementById('cf-domain')?.value  || '';
    _catalogFilterAccRef    = document.getElementById('cf-ref')?.value     || '';
    clearTimeout(_catalogFilterTimer);
    _catalogFilterTimer = setTimeout(renderCatalog, 300);
}

function resetCatalogFilters() {
    _catalogFilterProjectId = '';
    _catalogFilterDomain    = '';
    _catalogFilterAccRef    = '';
    renderCatalog();
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
                <div class="card-title">${escapeHtml(i.name || i.id)}</div>
                <div class="card-subtitle">${escapeHtml(i.id)}</div>
                <div class="card-footer" style="margin-top:12px">
                    <button class="btn btn-sm btn-primary" onclick="viewDoc('${escapeHtml(i.id)}', 'functional')">📋 Functional Spec</button>
                    <button class="btn btn-sm btn-info" style="background:var(--info)" onclick="viewDoc('${escapeHtml(i.id)}', 'technical')">🔧 Technical Spec</button>
                </div>
            </div>`).join('')}</div><div id="docViewer" style="margin-top:20px; background:var(--bg-secondary); padding:20px; border-radius:8px; display:none;"></div>`;
    } catch (e) { area.innerHTML = `<div class="empty-state"><div class="icon">⚠️</div><p>${escapeHtml(e.message)}</p></div>`; }
}

async function viewDoc(id, type) {
    const viewer = document.getElementById('docViewer');
    viewer.style.display = 'block';
    viewer.innerHTML = '<div class="loading">Loading markdown...</div>';
    try {
        const data = type === 'functional' ? await API.getFunctionalSpec(id) : await API.getTechnicalSpec(id);
        const mdContent = data?.data?.content || '*No content available.*';
        viewer.innerHTML = `<div class="markdown-body">${marked.parse(mdContent)}</div>`;
    } catch (e) { viewer.innerHTML = `<p style="color:var(--error)">Failed to load document: ${escapeHtml(e.message)}</p>`; }
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
                        <div class="card" style="margin-bottom:12px; cursor:pointer;" onclick="loadApprovalReview('${escapeHtml(a.id)}')">
                            <div class="card-title">${escapeHtml(a.integration_id)}</div>
                            <div class="card-subtitle">Type: ${escapeHtml(a.doc_type)}</div>
                            <div class="card-body" style="font-size:12px; margin-top:8px;">Generated: ${escapeHtml(new Date(a.generated_at).toLocaleString())}</div>
                        </div>
                    `).join('')}
                </div>
                <div id="approvalEditor" style="flex:2; display:flex; flex-direction:column;">
                    <div class="empty-state"><p>Select a document to review and edit.</p></div>
                </div>
            </div>
        `;
    } catch (e) { area.innerHTML = `<div class="empty-state"><div class="icon">⚠️</div><p>${escapeHtml(e.message)}</p></div>`; }
}

async function loadApprovalReview(id) {
    const editor = document.getElementById('approvalEditor');
    editor.innerHTML = '<div class="loading">Loading document...</div>';
    try {
        const data = await API.getPendingApprovals();
        const item = (data?.data || []).find(a => a.id === id);
        if (!item) throw new Error("Approval not found");

        // F-06: textarea content set via .value (not innerHTML interpolation) to
        // prevent </textarea> injection breaking out of the element (ADR-017).
        editor.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <h3>Review: ${escapeHtml(item.integration_id)} (${escapeHtml(item.doc_type)})</h3>
                <div>
                    <button class="btn btn-sm btn-error" onclick="rejectHitl('${escapeHtml(id)}')">Reject (Retry)</button>
                    <button class="btn btn-sm btn-success" onclick="approveHitl('${escapeHtml(id)}')">Approve &amp; Save to RAG</button>
                </div>
            </div>
            <textarea id="hitlMarkdown" style="flex:1; width:100%; padding:12px; font-family:monospace; background:var(--bg-main); color:var(--text-main); border:1px solid var(--border-color); border-radius:4px; resize:none;"></textarea>
        `;
        // Set textarea content via DOM .value — immune to </textarea> injection
        document.getElementById('hitlMarkdown').value = item.content;
    } catch (e) { editor.innerHTML = `<p style="color:var(--error)">Failed to load: ${escapeHtml(e.message)}</p>`; }
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

// ── Reset Tools Page ────────────────────────────────

function renderReset() {
    const area = document.getElementById('contentArea');
    area.innerHTML = `
        <div style="max-width: 700px;">
            <div class="card" style="border: 1px solid var(--warning); margin-bottom: 20px;">
                <div class="card-title" style="color: var(--warning);">⚠️ Danger Zone — Test Reset Tools</div>
                <div class="card-body" style="color: var(--text-muted); font-size: 0.9em;">
                    These actions are irreversible. Use them to start a clean test run.
                    The agent must not be running when resetting requirements or performing a full reset.
                </div>
            </div>

            <div class="card" style="margin-bottom: 16px;">
                <div class="card-title">📋 Reset Requirements &amp; Logs</div>
                <div class="card-body">Clears the parsed CSV requirements from memory and empties the agent log history. Does not touch MongoDB or ChromaDB.</div>
                <div class="card-footer" style="margin-top: 14px;">
                    <button class="btn" style="background: var(--warning); color: #000;"
                        onclick="executeReset('requirements', 'Clear requirements and agent logs?')">
                        Reset Requirements
                    </button>
                </div>
            </div>

            <div class="card" style="margin-bottom: 16px;">
                <div class="card-title">🗄️ Reset MongoDB</div>
                <div class="card-body">Deletes all catalog entries, approvals and generated documents from MongoDB and clears the in-memory caches. ChromaDB RAG data is preserved.</div>
                <div class="card-footer" style="margin-top: 14px;">
                    <button class="btn" style="background: var(--warning); color: #000;"
                        onclick="executeReset('mongodb', 'Delete ALL catalog, approvals and documents from MongoDB?')">
                        Reset MongoDB
                    </button>
                </div>
            </div>

            <div class="card" style="margin-bottom: 16px;">
                <div class="card-title">🧠 Reset ChromaDB (RAG Store)</div>
                <div class="card-body">Wipes the vector store by deleting and recreating the <code>approved_integrations</code> collection. All learned RAG examples will be lost.</div>
                <div class="card-footer" style="margin-top: 14px;">
                    <button class="btn" style="background: var(--warning); color: #000;"
                        onclick="executeReset('chromadb', 'Wipe the ChromaDB RAG vector store?')">
                        Reset ChromaDB
                    </button>
                </div>
            </div>

            <div class="card" style="border: 1px solid var(--error);">
                <div class="card-title" style="color: var(--error);">💥 Full Reset — Start from Zero</div>
                <div class="card-body">Runs all three resets above in sequence: requirements, MongoDB and ChromaDB. The system will be completely empty.</div>
                <div class="card-footer" style="margin-top: 14px;">
                    <button class="btn btn-error"
                        onclick="executeReset('all', 'FULL RESET — this will wipe requirements, MongoDB AND ChromaDB. Are you sure?')">
                        🔴 Full Reset
                    </button>
                </div>
            </div>

            <div id="resetResult" style="margin-top: 20px;"></div>
        </div>
    `;
}

async function executeReset(scope, confirmMessage) {
    if (!confirm(confirmMessage)) return;

    const result = document.getElementById('resetResult');
    result.innerHTML = `<span style="color: var(--info);">⏳ Resetting ${escapeHtml(scope)}...</span>`;

    try {
        const resetFns = {
            requirements: () => API.resetRequirements(),
            mongodb:       () => API.resetMongoDB(),
            chromadb:      () => API.resetChromaDB(),
            all:           () => API.resetAll(),
        };
        const data = await resetFns[scope]();
        if (data?.status === 'success') {
            result.innerHTML = `<span style="color: var(--success);">✅ ${escapeHtml(data.message)}</span>`;
        } else {
            result.innerHTML = `<span style="color: var(--error);">❌ ${escapeHtml(data?.detail || data?.message || 'Unknown error')}</span>`;
        }
    } catch (e) {
        result.innerHTML = `<span style="color: var(--error);">❌ Network error: ${escapeHtml(e.message)}</span>`;
    }
}

// ── Utilities ───────────────────────────────────────

/**
 * Escape HTML special characters to prevent stored XSS when injecting
 * server-supplied data into innerHTML (ADR-017 / OWASP A03).
 */
function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function truncate(str, len) { return (str || '').length > len ? str.substring(0, len) + '...' : str || ''; }

// ── Project helpers (ADR-025) ─────────────────────────────────────────────────

/**
 * Auto-generate a 1-3 char uppercase prefix from a client name.
 * "Acme Corp" → "AC" | "Global Fashion Group" → "GFG" | "Salsify" → "SAL"
 */
function generatePrefix(clientName) {
    const clean = clientName.trim();
    if (!clean) return '';
    const words = clean.split(/\s+/).filter(Boolean);
    let prefix;
    if (words.length === 1) {
        prefix = words[0].replace(/[^A-Z0-9]/gi, '').toUpperCase().slice(0, 3);
    } else {
        prefix = words.map(w => w[0]).join('').replace(/[^A-Z0-9]/gi, '').toUpperCase().slice(0, 3);
    }
    return prefix;
}
