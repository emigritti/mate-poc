# 06 — Integrarsi come MCP server

> ⚠️ **Work in Progress** — L'endpoint API esiste e risponde `202 Accepted`, ma il collector MCP non è ancora implementato. Questa guida documenta il **target state** per guidare l'implementazione.

---

## Scenario

Connettiti a un server MCP (Model Context Protocol) e indicizza automaticamente tutti i suoi **tools**, **resources** e **prompts** come capabilities nella KB condivisa.

Casi d'uso tipici:
- Esporre le capabilities di un sistema legacy tramite MCP server
- Indicizzare tool di un agente Claude esistente
- Integrare servizi interni Accenture che espongono un MCP endpoint

---

## Come funzionerà (target state)

```
Ingestion Platform (port 4006)
──────────────────────────────
POST /api/v1/sources             → registra URL del server MCP (SSE endpoint)
POST /api/v1/ingest/mcp/{id}     → avvia inspector in background (202 Accepted)
  │
  ├─ MCPInspector.inspect(server_url)
  │    ├─ Connessione via SSE transport (mcp.client.sse)
  │    ├─ session.list_tools()     → lista tools con schema JSON
  │    ├─ session.list_resources() → lista resources
  │    └─ session.list_prompts()   → lista prompts
  │
  ├─ MCPNormalizer → CanonicalCapability list
  │    ├─ Ogni tool   → CapabilityKind.TOOL
  │    ├─ Ogni resource → CapabilityKind.RESOURCE
  │    └─ Ogni prompt → CapabilityKind.GUIDE_STEP
  │
  └─ CanonicalChunk (prefix: src_{code}-chunk-{n})
     → Upsert in ChromaDB kb_collection
```

**Transport supportato:** SSE (HTTP) — standard per server MCP remoti.
**Graceful degradation:** se il server non è raggiungibile → `MCPInspectionResult` vuoto, run con error log.

---

## Via Dashboard (UI)

> UI in sviluppo — usa l'API.

---

## Via API (curl) — Target state

### Step 1 — Avvia un MCP server

Per testare hai bisogno di un server MCP accessibile. Esempio con il package ufficiale:

```bash
# Installa e avvia un MCP server di esempio (filesystem server)
npx -y @modelcontextprotocol/server-filesystem /tmp/test-dir

# Il server espone l'SSE endpoint su: http://localhost:3100/sse
```

Oppure usa qualsiasi server MCP compatibile con SSE transport.

### Step 2 — Registra la sorgente MCP

```bash
curl -s -X POST http://localhost:4006/api/v1/sources \
  -H "Content-Type: application/json" \
  -d '{
    "code": "filesystem_mcp",
    "source_type": "mcp",
    "entrypoints": ["http://host.docker.internal:3100/sse"],
    "tags": ["filesystem", "mcp", "tools"],
    "description": "Filesystem MCP Server — accesso file system"
  }' \
  | python3 -m json.tool
```

> Per raggiungere un server sul host da dentro Docker usa `host.docker.internal` (Windows/Mac) o l'IP del bridge Docker (Linux).

### Step 3 — Triggera l'ingestion

```bash
SOURCE_ID="src_a1b2c3d4"

curl -s -X POST http://localhost:4006/api/v1/ingest/mcp/$SOURCE_ID \
  | python3 -m json.tool
```

**Risposta attesa (202 Accepted):**
```json
{
  "run_id": "run_20260323103045_src_a1b2",
  "status": "accepted",
  "source_id": "src_a1b2c3d4"
}
```

**Risposta attuale (placeholder):**
Il run viene creato con status `FAILED` e error `"MCP collector not yet implemented — Phase 3"`.

### Step 4 — Verifica chunk (quando implementato)

```bash
curl -s "http://localhost:4003/api/v1/kb/search?q=filesystem+read+write+tool&n=5" \
  | python3 -m json.tool
```

---

## Esporre Integration Mate stesso come MCP server

Integration Mate può anche essere **consumato** da altri agenti Claude tramite MCP.

**Endpoints da esporre come MCP tools (da implementare):**

| Tool MCP | Mappa a | Descrizione |
|----------|---------|-------------|
| `search_kb` | `GET /api/v1/kb/search` | Ricerca semantica nella KB |
| `upload_document` | `POST /api/v1/kb/upload` | Carica documento nella KB |
| `trigger_generation` | `POST /api/v1/agent/trigger` | Avvia generazione documenti |
| `get_pending_approvals` | `GET /api/v1/approvals/pending` | Lista approvazioni in attesa |
| `approve_document` | `POST /api/v1/approvals/{id}/approve` | Approva documento |

Questa funzionalità richiederebbe un layer MCP server aggiuntivo che wrappa le API REST esistenti.

---

## Stato implementazione

| Componente | File | Stato |
|-----------|------|-------|
| Endpoint trigger | `routers/ingest.py` | ✅ Placeholder (202 + error log) |
| MCPInspector | `collectors/mcp/inspector.py` | ✅ Implementato (SSE transport) |
| MCPNormalizer | `collectors/mcp/normalizer.py` | ✅ Implementato |
| Integrazione in `_run_mcp_ingestion()` | `routers/ingest.py` | ❌ Da implementare |
| MCP server wrapper per Integration Mate | — | ❌ Fuori scope attuale |

**Cosa serve per completare:**
1. Implementare `_run_mcp_ingestion()` in `routers/ingest.py` (analoga a `_run_openapi_ingestion()`)
2. Collegare `MCPInspector` → `MCPNormalizer` → `IndexingService`
3. Il test di connessione SSE è già coperto in `tests/test_mcp_collector.py`

---

## Note per l'implementazione

| Aspetto | Decisione di design |
|---------|---------------------|
| **SDK MCP** | `mcp>=1.0.0` già in `requirements.txt` dell'Ingestion Platform |
| **Lazy import** | `from mcp import ClientSession` è lazy (dentro la funzione) — `ImportError` gestito con graceful degradation |
| **Transport** | SSE (`mcp.client.sse.sse_client`) — per server HTTP remoti. stdio non supportato (no subprocess) |
| **Chunk ID** | `src_{code}-chunk-{n}` — stessa convenzione di OpenAPI e HTML |
| **Stesso flow OpenAPI** | `_run_mcp_ingestion()` usa `IndexingService.upsert_chunks()` — nessuna modifica al retriever |
| **Timeout connessione** | `MCPInspector.inspect()` ha timeout configurabile (default 30s) — gestisce server lenti |
