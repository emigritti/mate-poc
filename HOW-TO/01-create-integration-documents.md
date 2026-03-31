# 01 — Creare documenti di integrazione

Genera automaticamente functional spec per le tue integrazioni partendo da un file di requisiti (CSV o Markdown).

**Flusso:** Upload CSV o Markdown → parse requirements → confirm tags → trigger agent (LLM + RAG) → HITL approve → spec nel catalog.

---

## Prerequisiti

- Almeno un documento o URL nella KB (vedi guide [02], [03], [04])
- File dei requisiti nel formato atteso (CSV o Markdown — vedi sezione Formato)
- Sistema avviato: `docker compose up -d`

---

## Formato dei requisiti

Puoi usare **CSV** (multi-integrazione in un file) oppure **Markdown** (una integrazione per file).

### Formato CSV

```csv
ReqID,Source,Target,Category,Description,Mandatory
REQ-001,PLM,PIM,Product Master,Sync product master data including SKU and EAN codes daily,true
REQ-002,PLM,PIM,Pricing,Transfer net price lists to PIM upon approval in PLM,false
REQ-003,PLM,DAM,Asset Sync,Push approved images from PLM to DAM on publish event,true
```

Colonne obbligatorie: `ReqID`, `Source`, `Target`, `Category`, `Description`.
`Mandatory` è opzionale (valori: `true`/`yes`/`1`); default `false` (non-mandatory).

### Formato Markdown (.md)

Un file `.md` = **una sola integrazione**. Usa frontmatter YAML per source/target e sezioni di heading per classificare i requisiti come mandatory o non-mandatory.

```markdown
---
source: ERP
target: Salsify
---

## Mandatory Requirements

- REQ-M01 | Product Collection | Sync daily created articles from ERP to PLM
- REQ-M02 | Image Collection | Automatically link high-res images from DAM with Salsify SKU

## Non-Mandatory Requirements

- REQ-O01 | Reporting | Generate weekly synchronization status report
```

**Regole del parser Markdown:**
- `source:` e `target:` nel frontmatter → identificano la coppia di sistemi.
  - Fallback se frontmatter assente: filename tipo `erp-to-salsify.md`.
- Heading contenente `mandatory` (ma non `non-mandatory` / `optional`) → flag `mandatory=true`.
- Formato bullet: `REQ-ID | Categoria | Descrizione` (1–3 parti separate da `|`).
  - Se REQ-ID omesso → generato automaticamente (`R-XXXXXX`).

---

## Via Dashboard (UI)

### Step 1 — Upload requisiti + compila progetto
1. Apri `http://localhost:8080`
2. Tab **Requirements** (è la pagina di default)
3. Clicca **Upload** → seleziona un file `.csv` o `.md`
4. Dopo il parsing appare automaticamente una **modal "Progetto"**:
   - **Client Name**: nome del cliente (es. `Acme Corp`)
   - **Prefix**: sigla 1-3 lettere maiuscole auto-generata (es. `ACM`) — modifica se necessario
   - **Domain**: settore (es. `Manufacturing`)
   - **Accenture Ref**: codice engagement opzionale
5. Clicca **Confirm** — il progetto viene creato e le integrazioni appaiono con status `PENDING_TAG_REVIEW`

> Se il prefix esiste già per lo stesso cliente, le integrazioni vengono aggiunte al progetto esistente.

### Step 2 — Conferma i tag
Per ogni integrazione:
1. Clicca **Suggest Tags** → il sistema propone tag via LLM
2. Rivedi/modifica i tag
3. **Confirm Tags** → status diventa `TAG_CONFIRMED`

### Step 4 — Avvia la generazione
1. Tab **Agent** → **Trigger Agent**
2. Il pannello log si aggiorna in real-time
3. Attendi `Generation completed`

> ⏱ Stima: ~90s/integrazione con `llama3.2:3b` su CPU.
> Per ridurre i timeout: imposta `OLLAMA_MODEL=llama3.2:3b` nel `.env`.

### Step 5 — HITL Review
1. Tab **Approvals** → leggi la spec generata
2. **Approve** per pubblicare nel Catalog
3. oppure **Reject** con feedback → l'agent rigenera tenendo conto del feedback

### Step 6 — Consulta il Catalog
1. Tab **Catalog** → integrazione con status `DONE`
2. Clicca → **View Functional Spec**

---

## Via API (curl)

### Step 1 — Upload requisiti (CSV o Markdown)

**CSV:**
```bash
curl -s -X POST http://localhost:4003/api/v1/requirements/upload \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@requirements.csv" \
  | python3 -m json.tool
```

**Markdown:**
```bash
curl -s -X POST http://localhost:4003/api/v1/requirements/upload \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@erp-to-salsify.md" \
  | python3 -m json.tool
```

**Risposta:**
```json
{"status": "success", "parsed": 3, "integrations_created": 2}
```

### Step 2 — Verifica integrazioni create

```bash
curl -s http://localhost:4003/api/v1/requirements | python3 -m json.tool
```

### Step 3 — Ottieni tag suggeriti

```bash
INTEGRATION_ID="INT-ABC123"

curl -s http://localhost:4003/api/v1/catalog/integrations/$INTEGRATION_ID/suggest-tags \
  | python3 -m json.tool
```

**Risposta:**
```json
{
  "integration_id": "INT-ABC123",
  "suggested_tags": ["plm", "pim", "data_sync"],
  "source": {
    "from_categories": ["data_sync"],
    "from_llm": ["plm", "pim"]
  }
}
```

### Step 4 — Conferma tag

```bash
curl -s -X POST http://localhost:4003/api/v1/catalog/integrations/$INTEGRATION_ID/confirm-tags \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tags": ["plm", "pim", "data_sync"]}' \
  | python3 -m json.tool
```

### Step 5 — Triggera la generazione

```bash
curl -s -X POST http://localhost:4003/api/v1/agent/trigger \
  -H "Authorization: Bearer YOUR_API_KEY" \
  | python3 -m json.tool
```

**Risposta immediata (asincrono):**
```json
{"status": "started", "task_id": "A1B2C3D4"}
```

### Step 6 — Polling dei log

```bash
OFFSET=0
while true; do
  RESP=$(curl -s "http://localhost:4003/api/v1/agent/logs?offset=$OFFSET")
  echo "$RESP" | python3 -m json.tool
  FINISHED=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['finished'])")
  [ "$FINISHED" = "True" ] && break
  OFFSET=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['next_offset'])")
  sleep 3
done
```

### Step 7 — Lista approvazioni pendenti

```bash
curl -s http://localhost:4003/api/v1/approvals/pending | python3 -m json.tool
```

### Step 8 — Approva

```bash
APPROVAL_ID="APP-XYZ123"

curl -s -X POST http://localhost:4003/api/v1/approvals/$APPROVAL_ID/approve \
  -H "Authorization: Bearer YOUR_API_KEY" \
  | python3 -m json.tool
```

### Step 8b — Rigetta con feedback

```bash
curl -s -X POST http://localhost:4003/api/v1/approvals/$APPROVAL_ID/reject \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"feedback": "Mancano dettagli sul formato dei dati scambiati e sulla gestione degli errori."}' \
  | python3 -m json.tool
```

### Step 9 — Recupera la spec approvata

```bash
curl -s http://localhost:4003/api/v1/catalog/integrations/$INTEGRATION_ID/functional-spec \
  | python3 -m json.tool
```

---

## Note operative

| Aspetto | Dettaglio |
|---------|-----------|
| **Auth** | `Authorization: Bearer YOUR_API_KEY`. Se `API_KEY` non è nel `.env` l'auth è bypassed (dev mode) |
| **Concorrenza** | Un solo agent run alla volta — secondo `trigger` ritorna `409 Conflict` |
| **Cancella run** | `POST /api/v1/agent/cancel` per interrompere un run in corso |
| **Timeout LLM** | Se il doc è `[LLM_UNAVAILABLE]`: modello troppo lento. Usa `llama3.2:3b` + `OLLAMA_NUM_PREDICT=500` |
| **Qualità** | Output con quality score basso viene loggato ma non bloccato — rivedi in HITL |
