# HOW-TO — Integration Mate PoC

Guida operativa per tutti i macro-scenari del sistema.
Ogni guida ha una sezione **via Dashboard (UI)** e una **via API (curl)**.

---

## Flusso end-to-end

```
┌──────────────────────────────────────────────────────────────────┐
│  KNOWLEDGE BASE                                                  │
│  Alimenta il RAG con best practice, documenti e sorgenti esterne │
│                                                                  │
│  [02] Upload file  ──→ ChromaDB (chunks indicizzati)            │
│  [03] Link URL     ──→ Live fetch at generation time             │
│  [04] OpenAPI      ──→ Ingestion Platform → ChromaDB            │
│  [05] HTML scrape  ──→ Ingestion Platform → ChromaDB  ⚠️ WIP    │
│  [06] MCP server   ──→ Ingestion Platform → ChromaDB  ⚠️ WIP    │
└──────────────────────────┬───────────────────────────────────────┘
                           │ RAG context (BM25 + dense hybrid)
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  DOCUMENT GENERATION                                             │
│                                                                  │
│  [01] Upload CSV requirements                                    │
│       → Confirm tags per integration                             │
│       → Trigger Agent (Ollama LLM + RAG)                        │
│       → HITL: Approve / Reject con feedback                      │
│       → Functional Spec pubblicata nel Catalog                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Guide disponibili

| # | Scenario | Stato | Link |
|---|----------|-------|------|
| 01 | Creare documenti di integrazione | ✅ Implementato | [→](./01-create-integration-documents.md) |
| 02 | Uploadare un documento nella KB | ✅ Implementato | [→](./02-upload-kb-document.md) |
| 03 | Linkare un sito per scanning on the fly | ✅ Implementato | [→](./03-link-url-to-kb.md) |
| 04 | Avviare ingestion OpenAPI da web | ✅ Implementato | [→](./04-openapi-ingestion.md) |
| 05 | Avviare scraping HTML | ⚠️ Work in Progress | [→](./05-html-scraping.md) |
| 06 | Integrarsi come MCP server | ⚠️ Work in Progress | [→](./06-mcp-server-integration.md) |

---

## Porte di accesso

| Servizio | URL esterno | Note |
|----------|-------------|------|
| Web Dashboard + Gateway | `http://localhost:8080` | Punto di accesso principale |
| Integration Agent (direct) | `http://localhost:4003` | Usato negli esempi curl |
| Ingestion Platform | `http://localhost:4006` | Gestione sorgenti esterne |
| n8n Orchestrator | `http://localhost:5678` | Workflow automatici (admin/admin) |
| Ollama | `http://localhost:11434` | LLM locale |

---

## Dipendenze tra guide

- **[01]** richiede almeno un documento in KB — popola prima con **[02]**, **[03]**, o **[04]**
- **[04]**, **[05]**, **[06]** usano tutte la stessa Ingestion Platform (port 4006) — stessa API di registrazione sorgente, collector diverso
- **[05]** e **[06]** documentano il target state: l'endpoint API esiste e ritorna 202, ma il collector sottostante non è ancora implementato
