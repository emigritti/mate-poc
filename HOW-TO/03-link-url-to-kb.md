# 03 — Linkare un sito per scanning on the fly

Registra URL esterni (documentazione, wiki, API reference) nella Knowledge Base.
Il contenuto **non viene scaricato all'upload** — viene **fetchato in tempo reale** al momento della generazione del documento (ADR-024).

---

## Come funziona

```
Registrazione URL                     Generazione documento
─────────────────                     ──────────────────────
POST /api/v1/kb/add-url               Agent trigger
→ Salva metadata in MongoDB           → RAG retrieval per integrazione
→ NO download del contenuto           → Per ogni URL in KB con tag compatibili:
→ tags assegnati manualmente            HTTP GET → estrai testo → tronca
                                      → Incluso nel contesto LLM
                                      → LLM genera con info aggiornate
```

**Vantaggio:** la documentazione esterna è sempre aggiornata al momento della generazione — non si "stantia" come un file caricato mesi fa.

**Limite:** l'URL deve essere raggiungibile dal container `mate-integration-agent` durante la generazione. URL privati e indirizzi interni sono bloccati.

---

## Prerequisiti

- URL pubblico (http:// o https://)
- URL privati/loopback **bloccati per sicurezza**: `localhost`, `127.*`, `10.*`, `192.168.*`, `172.16-31.*`

---

## Via Dashboard (UI)

1. Apri `http://localhost:8080`
2. Tab **Knowledge Base** → **Add URL**
3. Compila il form:
   - **URL**: `https://docs.example.com/api-guide`
   - **Title**: `Acme API Guide v3` (opzionale — usato come nome nella lista)
   - **Tags**: `acme`, `api`, `rest` (almeno uno obbligatorio)
4. **Save**
5. L'URL appare nella lista con `file_type: url` e `chunks: 0`

> `chunks: 0` è normale — il contenuto viene estratto on-demand durante la generazione, non indicizzato in anticipo.

---

## Via API (curl)

### Registra un URL

```bash
curl -s -X POST http://localhost:4003/api/v1/kb/add-url \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://docs.acme.com/integration-guide",
    "title": "Acme Integration Guide",
    "tags": ["acme", "integration", "rest_api"]
  }' \
  | python3 -m json.tool
```

**Risposta:**
```json
{
  "status": "success",
  "data": {
    "id": "KB-3f9a1bc2",
    "filename": "Acme Integration Guide",
    "file_type": "url",
    "source_type": "url",
    "url": "https://docs.acme.com/integration-guide",
    "tags": ["acme", "integration", "rest_api"],
    "chunk_count": 0,
    "uploaded_at": "2026-03-23T10:00:00"
  }
}
```

### Esempi di URL utili

```bash
# Swagger UI / OpenAPI Spec JSON
curl -s -X POST http://localhost:4003/api/v1/kb/add-url \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://petstore.swagger.io/v2/swagger.json",
    "title": "Petstore OpenAPI Spec",
    "tags": ["openapi", "example"]
  }' | python3 -m json.tool

# Pagina Confluence / Wiki
curl -s -X POST http://localhost:4003/api/v1/kb/add-url \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://confluence.example.com/display/ARCH/Integration+Standards",
    "title": "Integration Standards Wiki",
    "tags": ["architecture", "standards", "accenture"]
  }' | python3 -m json.tool

# GitHub README raw
curl -s -X POST http://localhost:4003/api/v1/kb/add-url \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://raw.githubusercontent.com/org/repo/main/README.md",
    "title": "Repo README",
    "tags": ["repo", "docs"]
  }' | python3 -m json.tool
```

### Lista soli gli URL nella KB

```bash
curl -s http://localhost:4003/api/v1/kb/documents \
  | python3 -c "
import sys, json
docs = json.load(sys.stdin)['data']
urls = [d for d in docs if d.get('source_type') == 'url']
print(f'URL entries: {len(urls)}')
for u in urls:
    print(f\"  {u['id']}: {u['filename']} -> {u['url']}\")
"
```

### Rimuovi un URL

```bash
curl -s -X DELETE http://localhost:4003/api/v1/kb/documents/KB-3f9a1bc2 \
  -H "Authorization: Bearer YOUR_API_KEY" \
  | python3 -m json.tool
```

---

## Comportamento durante la generazione

Per ogni URL in KB con tag compatibili con l'integrazione in lavorazione:

1. HTTP GET sull'URL (timeout: 10s default, `KB_URL_FETCH_TIMEOUT_SECONDS`)
2. Strip HTML → testo puro
3. Troncamento a max 1000 chars (`KB_URL_MAX_CHARS_PER_SOURCE`)
4. Aggiunto al contesto RAG insieme ai chunk ChromaDB

---

## Differenza con l'Ingestion Platform (guide [04]-[05])

| | Link URL (questa guida) | Ingestion Platform |
|--|------------------------|--------------------|
| **Quando** | Fetch on-demand al momento della generazione | Indicizzazione in anticipo (batch) |
| **Dove finisce** | Contesto LLM diretto | ChromaDB come chunk vettoriali |
| **Aggiornamento** | Sempre live, mai stantio | Richiede re-trigger dell'ingestion |
| **Searchable** | No (non indicizzato) | Sì (ricerca semantica via `/kb/search`) |
| **Ideale per** | Doc esterna che cambia spesso, reference veloci | API spec grandi, siti con molte pagine |

---

## Note operative

| Aspetto | Dettaglio |
|---------|-----------|
| **URL bloccati** | `localhost`, `127.*`, `10.*`, `192.168.*`, `172.16-31.*` → HTTP 400 |
| **Timeout fetch** | Default 10s — URL lenti vengono saltati silenziosamente nel contesto |
| **Max chars** | Default 1000 chars/URL — contenuti lunghi vengono troncati |
| **Tags obbligatori** | Almeno 1 tag — usato dal RAG per filtrare il contesto per integrazione |
| **Nessuna cache** | L'URL viene fetchato ogni volta — nessuna persistenza del contenuto |
