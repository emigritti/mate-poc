# 04 — Avviare ingestion OpenAPI tramite Ingestion Platform

Registra una sorgente OpenAPI nell'Ingestion Platform e indicizza automaticamente tutti gli endpoint come chunk nella KB condivisa (ChromaDB `kb_collection`).

**Flusso:** Registra sorgente → triggera → fetch spec → parse → normalize → chunk → diff → index in ChromaDB.

---

## Come funziona

```
Ingestion Platform (port 4006)
──────────────────────────────
POST /api/v1/sources             → registra URL della spec OpenAPI
POST /api/v1/ingest/openapi/{id} → avvia pipeline in background (202 Accepted)
  │
  ├─ Fetch spec (JSON/YAML) con ETag support
  ├─ Parse e validazione (OpenAPIParser)
  ├─ Diff con snapshot precedente → salta se non cambiato (hash SHA-256)
  ├─ Normalize → CanonicalCapability list (endpoint, schema, auth, overview)
  ├─ Chunk → CanonicalChunk (chunk ID: src_{code}-chunk-{n})
  ├─ Upsert in ChromaDB kb_collection (sostituisce vecchi chunk della sorgente)
  └─ Diff summary opzionale via Claude Haiku (se ANTHROPIC_API_KEY configurata)

Integration Agent (port 4003)
─────────────────────────────
GET /api/v1/kb/search  → trova i chunk indicizzati via RAG ibrido
```

---

## Prerequisiti

- Ingestion Platform in esecuzione: `docker ps | grep ingestion-platform`
- URL della spec OpenAPI (JSON o YAML) accessibile dal container (http/https)
- I mock API interni sono disponibili come sorgente di test

---

## Via Dashboard (UI)

> La UI dell'Ingestion Platform è in sviluppo — usa l'API o n8n.

**Via n8n (già configurato):**
1. Apri `http://localhost:5678` (login: admin/admin)
2. Workflow **WF-05 — Manual Ingest Trigger**
3. Configura il `source_id` nel nodo webhook
4. **Execute Workflow**

---

## Via API (curl)

### Step 1 — Registra la sorgente OpenAPI

```bash
curl -s -X POST http://localhost:4006/api/v1/sources \
  -H "Content-Type: application/json" \
  -d '{
    "code": "plm_api_v1",
    "source_type": "openapi",
    "entrypoints": ["http://mate-plm-mock:3001/openapi.json"],
    "tags": ["plm", "product", "lifecycle"],
    "description": "PLM Mock API — gestione ciclo vita prodotto",
    "refresh_cron": "0 */6 * * *"
  }' \
  | python3 -m json.tool
```

**Risposta:**
```json
{
  "id": "src_a1b2c3d4",
  "code": "plm_api_v1",
  "source_type": "openapi",
  "entrypoints": ["http://mate-plm-mock:3001/openapi.json"],
  "tags": ["plm", "product", "lifecycle"],
  "status": {"state": "active", "last_run_at": null},
  "refresh_cron": "0 */6 * * *"
}
```

> Annota `"id"` — serve per triggerare l'ingestion.

### Step 2 — Triggera l'ingestion

```bash
SOURCE_ID="src_a1b2c3d4"

curl -s -X POST http://localhost:4006/api/v1/ingest/openapi/$SOURCE_ID \
  | python3 -m json.tool
```

**Risposta immediata (async — 202 Accepted):**
```json
{
  "run_id": "run_20260323103045_src_a1b2",
  "status": "accepted",
  "source_id": "src_a1b2c3d4"
}
```

### Step 3 — Verifica chunk in ChromaDB

```bash
# Ricerca semantica — i chunk PLM appaiono tra i risultati
curl -s "http://localhost:4003/api/v1/kb/search?q=product+lifecycle+endpoint&n=5" \
  | python3 -m json.tool

# Lista tutti i documenti KB
curl -s http://localhost:4003/api/v1/kb/documents | python3 -m json.tool
```

### Registra anche il PIM mock

```bash
curl -s -X POST http://localhost:4006/api/v1/sources \
  -H "Content-Type: application/json" \
  -d '{
    "code": "pim_api_v1",
    "source_type": "openapi",
    "entrypoints": ["http://mate-pim-mock:3002/openapi.json"],
    "tags": ["pim", "product", "catalog"],
    "description": "PIM Mock API — informazioni prodotto"
  }' | python3 -m json.tool
```

### Lista sorgenti registrate

```bash
curl -s http://localhost:4006/api/v1/sources | python3 -m json.tool
```

### Triggera più sorgenti in sequenza

```bash
for SOURCE_ID in src_a1b2c3d4 src_b2c3d4e5; do
  echo "Triggering $SOURCE_ID..."
  curl -s -X POST http://localhost:4006/api/v1/ingest/openapi/$SOURCE_ID | python3 -m json.tool
  sleep 2
done
```

### Elimina una sorgente

```bash
curl -s -X DELETE http://localhost:4006/api/v1/sources/src_a1b2c3d4 \
  | python3 -m json.tool
```

---

## Chunk ID — coesistenza nella KB condivisa

| Origine | Chunk ID prefix | Esempio |
|---------|----------------|---------|
| Upload manuale (guida 02) | `KB-{uuid}-chunk-{n}` | `KB-A1B2C3D4-chunk-0` |
| Ingestion Platform | `src_{code}-chunk-{n}` | `src_plm_api_v1-chunk-0` |

Entrambi finiscono nella stessa `kb_collection` ChromaDB e vengono recuperati dal RAG ibrido senza modifiche al retriever.

---

## Schedulazione automatica con n8n

| Workflow | Comportamento |
|----------|--------------|
| **WF-01** — Scheduler | Triggera ogni sorgente attiva secondo `refresh_cron` |
| **WF-02** — OpenAPI Collector | Pipeline dedicata OpenAPI |
| **WF-05** — Manual Trigger | Trigger manuale via webhook |
| **WF-06** — Breaking Change Notify | Alert daily se rileva breaking changes |

Per attivare WF-01: `http://localhost:5678` → workflow → **Activate**.

---

## Note operative

| Aspetto | Dettaglio |
|---------|-----------|
| **Diff detection** | Se hash SHA-256 della spec non cambia → ingestion salta senza riscrivere chunk |
| **ETag support** | Il fetcher usa `If-None-Match` se il server supporta ETag |
| **Claude diff summary** | Se `ANTHROPIC_API_KEY` è configurata → summary leggibile dei cambiamenti |
| **Low confidence** | Capabilities con confidence < 0.7 incluse con `low_confidence=true` nei metadati |
| **Re-index** | Prima dell'upsert vengono eliminati tutti i chunk precedenti della stessa sorgente |
| **URL interno** | Per i mock usa nome container Docker: `http://mate-plm-mock:3001` non `localhost:3001` |
