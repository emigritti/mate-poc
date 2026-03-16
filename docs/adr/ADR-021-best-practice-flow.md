# ADR-021 — Best Practice Flow: Knowledge Base Import & RAG Integration

| Field        | Value                              |
|--------------|------------------------------------|
| **Status**   | Accepted                           |
| **Date**     | 2026-03-16                         |
| **Deciders** | Integration Mate PoC team          |
| **Tags**     | knowledge-base, rag, document-parsing |

## Context

Il flusso di generazione documentale (Agentic RAG) utilizza come contesto solo i
documenti precedentemente approvati tramite HITL (collezione `approved_integrations`
in ChromaDB). Questo limita la qualità dell'output: senza una base di conoscenza
strutturata, il modello LLM non può applicare pattern consolidati, linee guida
aziendali o standard di settore alla generazione.

Gli utenti dispongono di documenti di best practice in formati eterogenei
(PDF, Word, Excel, PowerPoint, Markdown) che contengono informazioni preziose
per arricchire la generazione, ma non esiste un meccanismo per importarli.

## Decision

Implementare una **Knowledge Base (KB) integrata** nel servizio `integration-agent`
con le seguenti caratteristiche:

### 1. Document Parser (`document_parser.py`)

Modulo dedicato con parser per 5 formati:

| Formato | Libreria     | Estrazione                         |
|---------|-------------|------------------------------------|
| PDF     | PyMuPDF     | Testo per pagina via `get_text()`  |
| DOCX    | python-docx | Paragrafi + tabelle                |
| XLSX    | openpyxl    | Righe per foglio, read-only mode   |
| PPTX    | python-pptx | Shape text + note presenter        |
| MD/TXT  | built-in    | Decode UTF-8 con fallback latin-1  |

Chunking sentence-aware con overlap configurabile (default: 1000 chars, 200 overlap).

### 2. Storage

- **ChromaDB** — collezione `knowledge_base` per i chunk vettorializzati, con
  metadati `document_id`, `filename`, `chunk_index`, `tags_csv`.
- **MongoDB** — collezione `kb_documents` per metadati documento (filename, tipo,
  dimensione, tag, conteggio chunk, preview, timestamp). Indici su `id` e `tags`.
- **In-memory** — dizionario `kb_docs` con write-through (stesso pattern di
  `catalog`, `approvals`, `documents`).

### 3. Auto-Tagging LLM

Funzione `_suggest_kb_tags_via_llm()` che riutilizza i parametri leggeri definiti
in ADR-020 (`tag_num_predict`, `tag_timeout_seconds`, `tag_temperature`) per
suggerire fino a 3 tag per documento importato. Fallback: lista vuota se LLM non
disponibile.

### 4. RAG Integration

Nuovo step nel flusso `run_agentic_rag_flow()`:

1. Query `approved_integrations` (invariato — ADR-019)
2. **Query `knowledge_base`** via `_query_kb_context()` — tag-filtered first,
   similarity fallback — truncato a `KB_MAX_RAG_CHARS` (default 2000)
3. `build_prompt()` riceve `kb_context` → iniettato come sezione
   `BEST PRACTICES REFERENCE` nel meta-prompt

### 5. API Endpoints (7)

| Metodo   | Path                              | Auth | Descrizione              |
|----------|-----------------------------------|------|--------------------------|
| `POST`   | `/api/v1/kb/upload`               | ✓    | Upload + parse + tag     |
| `GET`    | `/api/v1/kb/documents`            | —    | Lista documenti KB       |
| `GET`    | `/api/v1/kb/documents/{id}`       | —    | Dettaglio singolo        |
| `DELETE` | `/api/v1/kb/documents/{id}`       | ✓    | Cancella doc + chunks    |
| `PUT`    | `/api/v1/kb/documents/{id}/tags`  | ✓    | Aggiorna tag             |
| `GET`    | `/api/v1/kb/search?q=...&n=...`   | —    | Ricerca semantica        |
| `GET`    | `/api/v1/kb/stats`                | —    | Statistiche KB           |

### 6. Configurazione (ADR-016 compliant)

| Setting            | Env var             | Default      |
|--------------------|---------------------|--------------|
| `kb_max_file_bytes`| `KB_MAX_FILE_BYTES` | `10_485_760` |
| `kb_chunk_size`    | `KB_CHUNK_SIZE`     | `1000`       |
| `kb_chunk_overlap` | `KB_CHUNK_OVERLAP`  | `200`        |
| `kb_max_rag_chars` | `KB_MAX_RAG_CHARS`  | `2000`       |

### 7. Frontend

Pagina `KnowledgeBasePage.jsx` con: upload drag & drop multi-formato, tabella
documenti con azioni (preview, edit tag, delete), ricerca semantica, statistiche.
Inserita nella sidebar come step 2 del workflow (tra Requirements e API Systems).

## Alternatives Considered

| Opzione                                      | Rifiutata perché                                                    |
|----------------------------------------------|---------------------------------------------------------------------|
| MCP Server separato per la KB                | Complessità infrastrutturale sproporzionata per un PoC; latenza inter-servizio aggiuntiva |
| Embedding esterno (OpenAI, Cohere)           | Dipendenza esterna; fuori scope per PoC self-hosted con Ollama      |
| Solo parsing senza chunking                  | Documenti lunghi superano il context window del modello; RAG inefficace |
| Upload senza auto-tagging                    | Degrada la qualità del RAG tag-filtered (ADR-019)                   |

## Consequences

- La generazione documentale beneficia di **contesto best-practice aggiuntivo**
  oltre agli esempi approvati, migliorando la qualità dell'output.
- **10 MB** di limite upload è sufficiente per la maggior parte dei documenti
  enterprise; configurabile via env var senza rebuild.
- Le dipendenze Python aggiuntive (~40 MB) aumentano l'immagine Docker, accettabile
  per il valore funzionale aggiunto.
- **Rollback**: rimuovere la sezione `{kb_context}` dal meta-prompt e la chiamata
  `_query_kb_context()` da `run_agentic_rag_flow()` — nessun dato perso.

## Validation

- `test_document_parser.py`: 22 test per parsing, chunking, type detection.
- `test_kb_endpoints.py`: 10 test per endpoint API (validazione input, 404/415/413/422).
- Suite completa: **152 test passed** (0 regressioni).

## References

- ADR-016: Secret Management via Pydantic Settings (env-var pattern)
- ADR-019: RAG Tag-Filtering with HITL Tag Confirmation Gate
- ADR-020: Tag LLM Tuning — Dedicated Lightweight Parameters
