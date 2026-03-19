# ADR-024 — KB URL Links: HTTP/HTTPS Live Fetch at Generation Time

| Field        | Value                                                   |
|--------------|---------------------------------------------------------|
| **Status**   | Accepted                                                |
| **Date**     | 2026-03-19                                              |
| **Deciders** | Integration Mate PoC team                               |
| **Tags**     | knowledge-base, rag, ssrf, security, url-fetch          |

## Context

La Knowledge Base (KB) introdotta in ADR-021 supporta l'importazione di documenti
di best practice in formati file (PDF, DOCX, XLSX, PPTX, MD). Tuttavia, molte
fonti di conoscenza rilevanti sono disponibili direttamente come URL HTTP/HTTPS:
documentazione API di tool terzi (es. Salsify, Akeneo), specifiche di integrazione
pubblicate online, guide ufficiali di piattaforme target.

L'utente ha la necessità di registrare questi URL nella KB e fare in modo che
il loro contenuto venga consultato durante la generazione del documento —
esattamente come i file caricati contribuiscono al `kb_context`.

Due approcci di fetch sono stati considerati:
1. **Al momento della registrazione** (fetch immediato → chunk → ChromaDB): il contenuto diventa uno snapshot statico.
2. **Al momento della generazione** (fetch live): il contenuto è sempre aggiornato, ma crea una dipendenza di rete al runtime.

Il secondo approccio è stato preferito perché garantisce che la documentazione
referenziata (es. specifiche API di un tool) sia sempre la versione corrente,
senza richiedere una re-indicizzazione manuale quando il contenuto cambia.

## Decision

Estendere il modello `KBDocument` e il flusso di generazione per supportare
**voci KB di tipo URL**, con le seguenti caratteristiche:

### 1. Schema Extension (`schemas.py`)

Aggiunta di due campi opzionali a `KBDocument`:

```python
source_type: Literal["file", "url"] = "file"
url: Optional[str] = None  # popolato solo per source_type="url"
```

Aggiunta del modello di request `KBAddUrlRequest`:

```python
class KBAddUrlRequest(BaseModel):
    url: str            # HTTP/HTTPS validato nell'endpoint
    title: Optional[str] = None
    tags: List[str]     # 1-10 tag, stesso pattern di KBUpdateTagsRequest
```

Le voci URL hanno `file_type="url"`, `chunk_count=0`, `file_size_bytes=0`,
`content_preview=""`. Non hanno chunk in ChromaDB.

### 2. Nuovo Endpoint (`POST /api/v1/kb/add-url`)

Auth-guarded via `_require_token`. Flusso:

1. **Validazione schema** → `http://` o `https://` obbligatorio.
2. **SSRF guard** → blocco di range IP privati/loopback prima della persistenza:
   - `127.x`, `10.x`, `192.168.x`, `0.0.0.0`, `localhost`, `::1`
   - `172.16.x` – `172.31.x` (RFC 1918)
   - Usa `urllib.parse.urlparse` per estrarre l'hostname; nessuna risoluzione DNS.
3. **Validazione tag** → 1-10 tag, max 50 chars ciascuno.
4. **Persistenza** → `KBDocument(source_type="url")` salvato in MongoDB `kb_documents`
   e in-memory `kb_docs`. Nessuna scrittura su ChromaDB.
5. Ritorna `KBDocument` serializzato.

### 3. Fetch Live a Generation Time (`main.py`)

Due nuovi helper:

```python
def _extract_text_from_html(html: str) -> str:
    """Strip HTML tags + whitespace collapse via bleach (zero-tag allowlist)."""

async def _fetch_url_kb_context(tags: list[str]) -> str:
    """Fetch live content from KB URL entries matching at least one tag."""
```

Il secondo helper:
- Filtra le voci `source_type="url"` per tag overlap (intersezione con `entry.tags`).
- Usa `httpx.AsyncClient` (già dipendenza) con `timeout=kb_url_fetch_timeout_seconds`.
- Per ogni URL corrisposto: fetch → strip HTML → truncate a `kb_url_max_chars_per_source`.
- **Failure handling**: se il fetch fallisce (timeout, 4xx/5xx, eccezione), inietta
  `"[URL unavailable: <url>]"` nel contesto — il LLM è consapevole della sorgente mancante.

In `run_agentic_rag_flow()`, dopo la chiamata a `_query_kb_context()`:

```python
url_context = await _fetch_url_kb_context(entry.tags)
if url_context:
    kb_context = (kb_context + "\n\n" + url_context).strip() if kb_context else url_context
```

Il `url_context` combinato viene iniettato nella sezione `BEST PRACTICES REFERENCE`
del meta-prompt insieme al `kb_context` dei file.

### 4. Configurazione (ADR-016 compliant)

| Setting                      | Env var                          | Default |
|------------------------------|----------------------------------|---------|
| `kb_url_fetch_timeout_seconds` | `KB_URL_FETCH_TIMEOUT_SECONDS` | `10`    |
| `kb_url_max_chars_per_source`  | `KB_URL_MAX_CHARS_PER_SOURCE`  | `1000`  |

### 5. DELETE Guard Update

Il guard ChromaDB nell'endpoint `DELETE /api/v1/kb/documents/{id}` è aggiornato
per saltare la cancellazione dei chunk (che non esistono) per le voci URL:

```python
if kb_collection is not None and kb_doc.source_type == "file" and kb_doc.chunk_count > 0:
    # cancella chunk ChromaDB
```

### 6. Frontend (`KnowledgeBasePage.jsx`)

- La zona di upload è sostituita da un pannello a due tab:
  - **Upload File** — zona drag-drop esistente (invariata)
  - **Add URL** — form con campo URL (required), titolo (opzionale), tag (comma-separated)
- `normalizeKBDocs()` mappa le voci `file_type === "url"` su `source: "url"`.
- La tabella KB mostra il badge `🔗 Link` per le voci URL; il nome è un link cliccabile
  verso l'URL originale (apertura in nuova tab).
- Le azioni tag-edit e delete sono abilitate anche per le voci URL (i tag sono
  fondamentali per il filtro a generation time).

### 7. API client (`api.js`)

```javascript
API.kb.addUrl({ url, title, tags }) → POST /api/v1/kb/add-url
```

## Alternatives Considered

| Opzione | Rifiutata perché |
|---------|-----------------|
| Fetch al momento della registrazione (chunk + ChromaDB) | Crea snapshot statici; richiede re-registrazione manuale quando il contenuto cambia; doppia ChromaDB complexity |
| Fetch con TTL cache in MongoDB | Più complesso (gestione scadenza, invalidazione); overkill per PoC |
| Allowlist URL esplicita | Troppo restrittiva per un PoC; il SSRF guard per IP privati è sufficiente |
| Tag auto-suggeriti via LLM per URL | Richiederebbe un fetch al momento della registrazione; contraddice la decisione di non fetchare subito |

## Consequences

- La generation può ora consumare documentazione esterna aggiornata (es. Salsify API docs)
  direttamente dal link ufficiale, senza convertirla in file.
- **SSRF**: il guard blocca l'accesso a reti interne, ma non protegge da DNS rebinding
  in ambienti produzione — documentato come limitazione; accettabile per PoC.
- **Latenza**: ogni URL corrisposto aggiunge fino a `kb_url_fetch_timeout_seconds` alla
  durata della generation. Con pochi URL (PoC scale) l'impatto è trascurabile.
- **Resilienza**: un URL non raggiungibile non blocca la generation — inietta un
  placeholder trasparente invece di fallire.
- **Rollback**: rimuovere la chiamata `_fetch_url_kb_context()` da
  `run_agentic_rag_flow()` — nessun dato perso (le voci URL rimangono in MongoDB).

## Validation

- `test_kb_endpoints.py`: i test esistenti continuano a passare (DELETE guard verificato).
- Test manuale: aggiungere un URL con tag `salsify` → trigger generation con integrazione
  tagged `salsify` → verificare che il contenuto dell'URL appaia nel log `[KB-URL]`.
- Suite completa: **171 test passed** (0 regressioni).

## Security Checklist (OWASP)

| Threat | Mitigation | OWASP |
|--------|-----------|-------|
| SSRF — accesso a reti interne | Block private/loopback IP ranges pre-fetch | A10 |
| Scheme injection (`file://`, `ftp://`) | Solo `http://` e `https://` accettati | A10 |
| XSS via contenuto URL | `bleach.clean(tags=[], strip=True)` prima dell'iniezione nel prompt | A03 |
| DoS via fetch lento | Hard timeout `kb_url_fetch_timeout_seconds` (default 10s) | A04 |
| Credential forwarding | `httpx` default — nessun cookie, nessun header auth | A02 |

## References

- ADR-016: Secret Management via Pydantic Settings (env-var pattern)
- ADR-019: RAG Tag-Filtering with HITL Tag Confirmation Gate
- ADR-021: Best Practice Flow: Knowledge Base Import & RAG Integration
- OWASP A10: Server-Side Request Forgery (SSRF)
