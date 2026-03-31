# HOW-TO 02 — Gestire la Knowledge Base

La Knowledge Base (KB) è il corpus da cui l'agente recupera le best practice durante la generazione dei documenti. Ci sono quattro modi per alimentarla.

---

## Metodo A — Upload manuale di file (PDF / MD / TXT)

1. Vai a **Knowledge Base** nella sidebar
2. Clicca **Upload Document**
3. Seleziona il file e assegna i tag (es. `plm`, `best-practice`)
4. Clicca **Upload**

Il documento viene chunkato e indicizzato in ChromaDB automaticamente.

> I file caricati manualmente hanno ID `KB-<hash>-chunk-<n>` e sono visibili nella lista documenti KB.

---

## Metodo B — Link URL (fetch live)

Registra un URL che verrà consultato **live** durante ogni generazione (non indicizzato in ChromaDB).

1. Vai a **Knowledge Base → URL Links**
2. Clicca **Add URL**
3. Inserisci URL e descrizione
4. Salva

L'URL viene incluso nel contesto RAG ad ogni chiamata all'agente.

---

## Metodo C — Ingestion OpenAPI

Per indicizzare automaticamente le specifiche di un'API (Swagger/OpenAPI).

### Registrare la sorgente

```bash
curl -X POST http://<EC2_IP>:4006/api/v1/sources \
  -H "Content-Type: application/json" \
  -d '{
    "code": "plm_api_v1",
    "source_type": "openapi",
    "entrypoints": ["http://mate-plm-mock:3001/openapi.json"],
    "tags": ["plm", "product"],
    "refresh_cron": "0 */6 * * *"
  }'
```

### Triggerare l'ingestion manualmente

```bash
# Ottieni source_id dalla lista
curl http://<EC2_IP>:4006/api/v1/sources

# Trigger ingestion
curl -X POST http://<EC2_IP>:4006/api/v1/ingest/openapi/<source_id>
```

### Verificare il risultato

```bash
# Controlla lo stato del run
curl http://<EC2_IP>:4006/api/v1/sources/<source_id>
```

I chunk vengono scritti in ChromaDB con ID `src_plm_api_v1-chunk-<n>`.

---

## Metodo D — Scraping HTML (con Claude)

Per indicizzare pagine di documentazione web tramite estrazione semantica AI.

### Prerequisiti

- `ANTHROPIC_API_KEY` configurata nel `.env` (Claude Haiku per il filtro rilevanza, Claude Sonnet per l'estrazione)
- Sito con pagine statiche HTML (senza JS rendering obbligatorio)

### Registrare la sorgente HTML

```bash
curl -X POST http://<EC2_IP>:4006/api/v1/sources \
  -H "Content-Type: application/json" \
  -d '{
    "code": "payment_docs",
    "source_type": "html",
    "entrypoints": ["https://docs.example.com/api"],
    "tags": ["payments", "integration"],
    "refresh_cron": "0 2 * * *"
  }'
```

### Triggerare lo scraping

```bash
curl -X POST http://<EC2_IP>:4006/api/v1/ingest/html/<source_id>
```

Il crawler visita fino a `max_html_pages_per_crawl` (default: 20) pagine sullo stesso dominio.

### Modalità degradata (senza API Key)

Senza `ANTHROPIC_API_KEY` il crawler gira comunque:
- Le pagine vengono crawlate e pulite (boilerplate rimosso)
- Il filtro rilevanza e l'estrazione Claude vengono saltati
- Nessun chunk viene scritto in ChromaDB

---

## Verificare il contenuto della KB

Dalla dashboard → **Knowledge Base** → lista documenti e chunk indicizzati.

Per interrogare direttamente ChromaDB:
```bash
# Numero di chunk nella kb_collection
curl http://<EC2_IP>:8000/api/v1/collections/kb_collection/count
```
