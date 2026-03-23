# 02 — Uploadare un documento nella Knowledge Base

Carica file di best practice, guide tecniche o template nel vector store (ChromaDB).
Il sistema esegue parsing layout-aware (Docling), chunking semantico, auto-tagging LLM e indicizzazione BM25+dense in automatico.

---

## Formati supportati

| Formato | Estensione | Note |
|---------|-----------|------|
| PDF | `.pdf` | Layout-aware: testo, tabelle e figure (con caption LLaVA) |
| Word | `.docx` | Testo strutturato per sezioni |
| PowerPoint | `.pptx` | Slide come chunk separati |
| Excel | `.xlsx` | Fogli come chunk tabulari |
| Markdown | `.md` | Chunking semantico ricorsivo |
| Testo | `.txt` | Chunking semantico |
| HTML | `.html` | Testo estratto, tag rimossi |

**Limite dimensione:** 10 MB per file (configurabile via `KB_MAX_FILE_BYTES`).

---

## Via Dashboard (UI)

### Upload singolo
1. Apri `http://localhost:8080`
2. Tab **Knowledge Base** → **Upload Document**
3. Seleziona il file → **Upload**
4. Al termine appare nella lista con:
   - `doc_id` assegnato (es. `KB-A1B2C3D4`)
   - tag auto-generati dall'LLM
   - numero di chunk creati

### Upload batch (fino a 10 file)
1. Tab **Knowledge Base** → **Batch Upload**
2. Seleziona più file (Ctrl+click o Shift+click) — max 10
3. **Upload All**
4. Per ogni file viene mostrato lo stato individuale: `success` / `error` con dettaglio

> Un file che fallisce non blocca gli altri — ogni file è processato indipendentemente.

### Modificare i tag dopo l'upload
1. Clicca sul documento nella lista KB
2. Sezione **Tags** → modifica → **Save Tags**

### Eliminare un documento
1. Clicca 🗑️ accanto al documento → conferma
2. I chunk vengono rimossi da ChromaDB e l'indice BM25 viene ricostruito

---

## Via API (curl)

### Upload singolo

```bash
curl -s -X POST http://localhost:4003/api/v1/kb/upload \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@best_practices_integration.pdf" \
  | python3 -m json.tool
```

**Risposta:**
```json
{
  "id": "KB-A1B2C3D4",
  "filename": "best_practices_integration.pdf",
  "file_type": "pdf",
  "chunks_created": 24,
  "auto_tags": ["integration", "best_practice", "api"]
}
```

### Upload batch (fino a 10 file)

```bash
curl -s -X POST http://localhost:4003/api/v1/kb/batch-upload \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "files=@doc1.pdf" \
  -F "files=@doc2.md" \
  -F "files=@doc3.docx" \
  | python3 -m json.tool
```

**Risposta con partial success:**
```json
{
  "results": [
    {"filename": "doc1.pdf",  "status": "success", "chunks_created": 18, "error": null},
    {"filename": "doc2.md",   "status": "success", "chunks_created": 6,  "error": null},
    {"filename": "doc3.docx", "status": "error",   "chunks_created": 0,  "error": "No text could be extracted."}
  ]
}
```

### Lista documenti KB

```bash
curl -s http://localhost:4003/api/v1/kb/documents | python3 -m json.tool
```

### Dettaglio documento

```bash
curl -s http://localhost:4003/api/v1/kb/documents/KB-A1B2C3D4 | python3 -m json.tool
```

### Aggiorna tag

```bash
curl -s -X PUT http://localhost:4003/api/v1/kb/documents/KB-A1B2C3D4/tags \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tags": ["integration", "rest_api", "accenture"]}' \
  | python3 -m json.tool
```

### Ricerca semantica nella KB

```bash
curl -s "http://localhost:4003/api/v1/kb/search?q=best+practices+API+versioning&n=5" \
  | python3 -m json.tool
```

**Risposta:**
```json
{
  "results": [
    {
      "chunk_text": "API versioning should use URL path versioning (/v1, /v2)...",
      "document_id": "KB-A1B2C3D4",
      "filename": "best_practices_integration.pdf",
      "score": 0.87
    }
  ],
  "query": "best practices API versioning",
  "total_results": 5
}
```

### Statistiche KB

```bash
curl -s http://localhost:4003/api/v1/kb/stats | python3 -m json.tool
```

**Risposta:**
```json
{
  "total_documents": 12,
  "total_chunks": 187,
  "file_types": {"pdf": 8, "md": 3, "docx": 1},
  "all_tags": ["api", "best_practice", "integration", "rest"]
}
```

### Elimina documento

```bash
curl -s -X DELETE http://localhost:4003/api/v1/kb/documents/KB-A1B2C3D4 \
  -H "Authorization: Bearer YOUR_API_KEY" \
  | python3 -m json.tool
```

---

## Note operative

| Aspetto | Dettaglio |
|---------|-----------|
| **Auto-tagging** | Usa Ollama sui primi 1000 chars — modificabili dopo con `PUT /kb/documents/{id}/tags` |
| **RAPTOR summaries** | Sezioni con ≥3 chunk generano un summary (ADR-032) — migliora il RAG su documenti lunghi |
| **BM25 rebuild** | Dopo ogni upload/delete l'indice BM25 viene ricostruito automaticamente |
| **Chunk ID convention** | `KB-{docid}-chunk-{n}` — non collide con i chunk dell'Ingestion Platform (`src_{code}-chunk-{n}`) |
| **RAG ibrido** | Ogni upload popola sia ChromaDB (dense) che BM25 (sparse) — entrambi usati durante il RAG |
| **Figure** | I chunk di tipo `figure` vengono inclusi nell'indice BM25 con la caption generata da LLaVA:7b |
