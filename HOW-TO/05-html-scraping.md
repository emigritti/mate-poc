# 05 — Avviare scraping HTML tramite Ingestion Platform

> ⚠️ **Work in Progress** — L'endpoint API esiste e risponde `202 Accepted`, ma il collector HTML non è ancora implementato. Questa guida documenta il **target state** per guidare l'implementazione.

---

## Scenario

Crawla uno o più siti web (documentazione, wiki, portali) ed estrai le capabilities in chunk semantici da indicizzare nella KB condivisa.

Casi d'uso tipici:
- Documentazione di API su portali Confluence o SharePoint
- Wiki interni con guide di integrazione
- Siti di vendor con reference tecnica

---

## Come funzionerà (target state)

```
Ingestion Platform (port 4006)
──────────────────────────────
POST /api/v1/sources              → registra URL di partenza + depth
POST /api/v1/ingest/html/{id}     → avvia crawler in background (202 Accepted)
  │
  ├─ Playwright (headless Chromium) crawl da entrypoint URL
  ├─ Segue link interni fino a max_html_pages_per_crawl (default: 20)
  ├─ Per ogni pagina:
  │    ├─ HTML cleaner → rimuove nav, footer, ads
  │    ├─ HTMLRelevanceFilter (Claude Haiku) → scarta pagine non rilevanti
  │    ├─ HTMLAgentExtractor (Claude Sonnet) → estrae capabilities strutturate
  │    └─ Normalize → CanonicalChunk (prefix: src_{code}-chunk-{n})
  └─ Upsert in ChromaDB kb_collection
```

**Dipendenza da Claude:** la rilevanza e l'estrazione semantica usano Claude Haiku e Sonnet (ADR-037).
Se `ANTHROPIC_API_KEY` non è configurata → include tutte le pagine senza filtro, estrazione minimale.

---

## Via Dashboard (UI)

> UI in sviluppo — usa l'API.

---

## Via API (curl) — Target state

### Step 1 — Registra la sorgente HTML

```bash
curl -s -X POST http://localhost:4006/api/v1/sources \
  -H "Content-Type: application/json" \
  -d '{
    "code": "acme_docs",
    "source_type": "html",
    "entrypoints": ["https://docs.acme.com/integration"],
    "tags": ["acme", "docs", "integration"],
    "description": "Acme Integration Documentation Portal",
    "refresh_cron": "0 2 * * *"
  }' \
  | python3 -m json.tool
```

> `entrypoints` è la lista di URL di partenza. Il crawler segue i link da ciascuno.

### Step 2 — Triggera il crawl

```bash
SOURCE_ID="src_a1b2c3d4"

curl -s -X POST http://localhost:4006/api/v1/ingest/html/$SOURCE_ID \
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
```json
{
  "run_id": "run_...",
  "status": "accepted",
  "source_id": "src_a1b2c3d4"
}
```
Il run viene creato con status `FAILED` e error `"HTML collector not yet implemented — Phase 4"`.

### Step 3 — Verifica chunk (quando implementato)

```bash
curl -s "http://localhost:4003/api/v1/kb/search?q=acme+integration+guide&n=5" \
  | python3 -m json.tool
```

---

## Stato implementazione

| Componente | File | Stato |
|-----------|------|-------|
| Endpoint trigger | `routers/ingest.py` | ✅ Placeholder (202 + error log) |
| HTML cleaner | `collectors/html/cleaner.py` | ✅ Implementato |
| Relevance filter | `collectors/html/extractor.py` | ✅ Implementato |
| Agent extractor | `collectors/html/agent_extractor.py` | ✅ Implementato |
| HTML normalizer | `collectors/html/normalizer.py` | ✅ Implementato |
| Playwright crawl loop | `collectors/html/` — mancante | ❌ Da implementare |
| Integrazione in `_run_html_ingestion()` | `routers/ingest.py` | ❌ Da implementare |

**Cosa serve per completare:**
1. Implementare la funzione `_run_html_ingestion()` in `routers/ingest.py` (analoga a `_run_openapi_ingestion()`)
2. Scrivere il Playwright crawl loop che itera le pagine
3. Collegare cleaner → filter → extractor → normalizer → IndexingService

---

## Configurazione rilevante

```bash
# In .env o docker-compose environment:
MAX_HTML_PAGES_PER_CRAWL=20       # Limite pagine per crawl (default: 20)
HTML_RELEVANCE_MIN_SCORE=0.5      # Soglia rilevanza Haiku (0.0-1.0)
ANTHROPIC_API_KEY=sk-ant-...      # Obbligatorio per filtro + estrazione semantica
```

---

## Note per l'implementazione

| Aspetto | Decisione di design |
|---------|---------------------|
| **Playwright** | Già installato nel Dockerfile (`playwright install chromium --with-deps`) |
| **Graceful degradation** | Se Claude non disponibile → include tutte le pagine (filter=True) + estrazione minimale |
| **Chunk ID** | `src_{code}-chunk-{n}` — stessa convenzione di OpenAPI |
| **Depth limit** | `MAX_HTML_PAGES_PER_CRAWL` evita crawl infiniti |
| **Stesso flow OpenAPI** | `_run_html_ingestion()` usa `IndexingService.upsert_chunks()` come OpenAPI — nessuna modifica al retriever |
