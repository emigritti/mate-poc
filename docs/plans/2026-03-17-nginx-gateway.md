# Nginx Gateway — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Aggiungere un container nginx gateway sulla porta 8080 che proxia tutte le chiamate API, eliminando la dipendenza del browser dalle porte non-standard (4003, 4001, 4002) bloccate da firewall aziendali.

**Architecture:** Un nuovo servizio `gateway` (nginx) occupa la porta `8080:80` ed espone path-prefix per ogni backend (`/agent/`, `/plm/`, `/pim/`). Il `web-dashboard` diventa internal-only. `src/api.js` usa path relativi → same-origin → CORS irrilevante, zero modifiche ai backend.

**Tech Stack:** nginx:alpine, Docker Compose, JavaScript (ES6 fetch)

---

### Task 1: Creare la directory e il file nginx.conf del gateway

**Files:**
- Create: `services/gateway/nginx.conf`

**Step 1: Creare la directory gateway**

```bash
mkdir -p services/gateway
```

**Step 2: Creare `services/gateway/nginx.conf`**

```nginx
# ═══════════════════════════════════════════════════════════
# Integration Mate — Nginx Gateway
# Concentra tutta la comunicazione browser→backend su porta 8080.
# Elimina il bisogno di aprire le porte 4001/4002/4003 sul firewall.
# ═══════════════════════════════════════════════════════════

server {
    listen 80;
    server_name _;

    # ── Web Dashboard (SPA React) ──────────────────────────
    location / {
        proxy_pass         http://mate-web-dashboard:80/;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    }

    # ── Integration Agent  /agent/... → /... ──────────────
    # proxy_read_timeout esteso: Ollama può richiedere minuti su CPU
    location /agent/ {
        proxy_pass         http://mate-integration-agent:3003/;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        client_max_body_size 20m;
    }

    # ── PLM Mock  /plm/... → /... ─────────────────────────
    location /plm/ {
        proxy_pass         http://mate-plm-mock:3001/;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    }

    # ── PIM Mock  /pim/... → /... ─────────────────────────
    location /pim/ {
        proxy_pass         http://mate-pim-mock:3002/;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    }
}
```

**Step 3: Verificare la struttura**

```bash
ls services/gateway/
```
Expected: `nginx.conf`

---

### Task 2: Creare il Dockerfile del gateway

**Files:**
- Create: `services/gateway/Dockerfile`

**Step 1: Creare `services/gateway/Dockerfile`**

```dockerfile
# Nginx gateway — routing centralizzato su porta 8080
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

Nota: l'immagine base `nginx:alpine` include già la config globale `/etc/nginx/nginx.conf` che include tutti i file in `conf.d/`. Sovrascriviamo solo `default.conf`.

**Step 2: Verificare**

```bash
ls services/gateway/
```
Expected: `Dockerfile  nginx.conf`

---

### Task 3: Aggiornare docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Aggiungere il servizio `gateway` in fondo alla sezione services, PRIMA di `web-dashboard`**

Aggiungere dopo il commento `# ── Frontend Layer ─────────────────────────`:

```yaml
  # ── Gateway Layer ─────────────────────────────────────
  # Reverse proxy unico su porta 8080: elimina la necessità di
  # aprire le porte 4001/4002/4003 sul firewall aziendale.
  gateway:
    build:
      context: ./services/gateway
      dockerfile: Dockerfile
    container_name: mate-gateway
    ports:
      - "8080:80"
    depends_on:
      - web-dashboard
      - integration-agent
      - plm-mock
      - pim-mock
    networks:
      - integration-mate-net
    healthcheck:
      test: curl -f http://localhost:80/ || exit 1
      interval: 30s
      timeout: 5s
      retries: 3
    logging: *default-logging
```

**Step 2: Modificare `web-dashboard` — rimuovere il port binding esterno**

Trovare:
```yaml
  web-dashboard:
    build:
      context: ./services/web-dashboard
      dockerfile: Dockerfile
    container_name: mate-web-dashboard
    ports:
      - "8080:80"
```

Sostituire con (rimuovere `ports`, aggiungere commento esplicativo):
```yaml
  web-dashboard:
    build:
      context: ./services/web-dashboard
      dockerfile: Dockerfile
    container_name: mate-web-dashboard
    # Porta non esposta all'esterno: il traffico arriva tramite il gateway
    expose:
      - "80"
```

**Step 3: Verificare la sintassi YAML**

```bash
docker compose config --quiet && echo "YAML OK"
```
Expected: `YAML OK`

---

### Task 4: Aggiornare `src/api.js` — path relativi

**Files:**
- Modify: `services/web-dashboard/src/api.js`

**Problema:** `getBase()` restituisce `http://18.197.235.56:4003` — porta bloccata.
**Soluzione:** usare path relativi (`/agent`) — same-origin, nessun CORS.

**Step 1: Sostituire `getBase()` e `health.check`**

Trovare e sostituire l'intero blocco iniziale + health:

```js
// PRIMA
const getBase = () => `http://${window.location.hostname}:4003`;
```

```js
// DOPO
// Gateway-relative paths: tutta la comunicazione passa per /agent/, /plm/, /pim/
// su porta 8080 (stessa origine del dashboard) → nessuna configurazione CORS necessaria.
const AGENT = '/agent';
const PLM   = '/plm';
const PIM   = '/pim';
```

Poi aggiornare ogni `${getBase()}` → `${AGENT}`:

```js
// Tutto ciò che era ${getBase()} diventa ${AGENT}
// Esempio:
requirements: {
  upload: (file) => {
    const fd = new FormData();
    fd.append('file', file);
    return fetch(`${AGENT}/api/v1/requirements/upload`, { method: 'POST', body: fd });
  },
  list: () => fetch(`${AGENT}/api/v1/requirements`),
},
```

Aggiornare anche `health.check` che usava una porta raw:

```js
// PRIMA
health: {
  check: (port) => fetch(`http://${window.location.hostname}:${port}/health`),
},

// DOPO
health: {
  // service: 'agent' | 'plm' | 'pim'
  check: (service) => {
    const paths = { agent: AGENT, plm: PLM, pim: PIM };
    const base = paths[service] ?? `/${service}`;
    return fetch(`${base}/health`);
  },
},
```

**Step 2: Applicare la sostituzione completa** (vedi codice finale nella sezione Appendice A)

**Step 3: Verificare che non rimanga nessuna stringa con porta hardcoded**

```bash
grep -n ":[0-9]\{4,5\}" services/web-dashboard/src/api.js
```
Expected: nessun output (0 righe)

---

### Task 5: Aggiornare `js/api.js` — path relativi (legacy)

**Files:**
- Modify: `services/web-dashboard/js/api.js`

Questo file non è incluso nel build React ma è nel contesto Docker → aggiornarlo per coerenza ed evitare confusione futura.

**Step 1: Sostituire le costanti URL**

```js
// PRIMA
const _HOST = window.location.hostname;
const API = {
    AGENT: `http://${_HOST}:4003`,
    PLM:   `http://${_HOST}:4001`,
    PIM:   `http://${_HOST}:4002`,
```

```js
// DOPO
// Gateway-relative: tutta la comunicazione via porta 8080 (same-origin).
const API = {
    AGENT: '/agent',
    PLM:   '/plm',
    PIM:   '/pim',
```

**Step 2: Aggiornare `checkServices`**

```js
// PRIMA
async checkServices() {
    const services = [
        { name: 'Agent',    url: `${this.AGENT}/health` },
        { name: 'PLM Mock', url: `${this.PLM}/health` },
        { name: 'PIM Mock', url: `${this.PIM}/health` }
    ];
```

Rimane invariato — usa già `${this.AGENT}/health` che ora è `/agent/health`. ✓

**Step 3: Verificare**

```bash
grep -n ":[0-9]\{4,5\}" services/web-dashboard/js/api.js
```
Expected: nessun output

---

### Task 6: Build, deploy, e smoke test

**Step 1: Build solo dei servizi modificati**

```bash
cd C:\Project\Agentic\my-functional-integration-mate-poc
docker compose build gateway web-dashboard
```
Expected: `Successfully built` per entrambi, nessun errore.

**Step 2: Riavviare i servizi impattati**

```bash
docker compose up -d gateway web-dashboard
```
Expected: `Started` o `Recreated` per entrambi.

**Step 3: Smoke test — gateway health**

```bash
curl -s http://localhost:8080/ | head -5
```
Expected: HTML del dashboard React (tag `<html>` o `<!doctype html>`)

**Step 4: Smoke test — agent via gateway**

```bash
curl -s http://localhost:8080/agent/health
```
Expected: `{"status":"ok",...}` (o simile JSON dal FastAPI health endpoint)

**Step 5: Smoke test — PLM e PIM via gateway**

```bash
curl -s http://localhost:8080/plm/health
curl -s http://localhost:8080/pim/health
```
Expected: `{"status":"ok"}` per entrambi

**Step 6: Verificare che le porte dirette NON siano più necessarie**

```bash
curl -s http://localhost:4003/health
```
Expected: risposta OK (la porta è ancora esposta internamente, ma non è richiesta dal browser).
Opzionalmente, per massima sicurezza, rimuovere i port binding 4001/4002/4003 da docker-compose.yml in un task separato.

**Step 7: Commit**

```bash
git add services/gateway/ docker-compose.yml services/web-dashboard/src/api.js services/web-dashboard/js/api.js
git commit -m "feat: add nginx gateway on port 8080 — fix firewall-blocked API ports"
```

---

## Appendice A — `src/api.js` completo post-modifica

```js
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
```
