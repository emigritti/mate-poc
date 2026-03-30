# 07 — Generare il Technical Design Document

Dopo l'approvazione della functional spec, genera il documento tecnico dell'integrazione.

**Flusso:** Approve Functional → click "Genera Technical Design" → HITL approve → Technical Spec nel Catalog.

---

## Prerequisiti

- Functional spec approvata (status `DONE` in Catalog)
- Sistema avviato: `docker compose up -d`

---

## Via Dashboard (UI)

### Step 1 — Approva la functional spec

1. Tab **Approvals** → revisiona la functional spec
2. Clicca **Approve** → status diventa `DONE`
3. Nel Catalog compare il bottone **Genera Technical Design** sulla riga dell'integrazione

### Step 2 — Avvia la generazione tecnica

1. Tab **Catalog** → individua l'integrazione con status `DONE`
2. Clicca **Genera Technical Design**
3. Attendi il completamento (badge `⏳ Technical...`)

> Stima: ~90s/integrazione con `llama3.2:3b` su CPU.

### Step 3 — HITL Review del documento tecnico

1. Tab **Approvals** → cerca l'approval con `doc_type: technical`
2. Revisiona il documento tecnico generato
3. **Approve** per finalizzare → `technical_status: TECH_DONE`
4. oppure **Reject** con feedback → clicca **Regenerate** per una nuova versione

### Step 4 — Consulta il Technical Spec

1. Tab **Catalog** → clicca **View Technical Spec** sulla riga

---

## Via API (curl)

### Verifica technical_status dopo approvazione funzionale

```bash
INTEGRATION_ID="INT-ABC123"

curl -s http://localhost:4003/api/v1/catalog/integrations | \
  python3 -c "import sys,json; [print(i['id'], i.get('technical_status')) for i in json.load(sys.stdin)['data']]"
```

### Trigger generazione tecnica

```bash
curl -s -X POST http://localhost:4003/api/v1/agent/trigger-technical/$INTEGRATION_ID \
  -H "Authorization: Bearer YOUR_API_KEY" \
  | python3 -m json.tool
```

**Risposta:**
```json
{"status": "success", "approval_id": "APP-XYZ123"}
```

### Lista approvazioni pendenti (include tecniche)

```bash
curl -s http://localhost:4003/api/v1/approvals/pending | \
  python3 -c "import sys,json; [print(a['id'], a['doc_type'], a['status']) for a in json.load(sys.stdin)['data']]"
```

### Approva il technical design

```bash
APPROVAL_ID="APP-XYZ123"

curl -s -X POST http://localhost:4003/api/v1/approvals/$APPROVAL_ID/approve \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"final_markdown\": \"$(curl -s http://localhost:4003/api/v1/approvals/pending | python3 -c \"import sys,json; [print(a['content']) for a in json.load(sys.stdin)['data'] if a['id']=='$APPROVAL_ID']\" | head -c 200)...\"}" \
  | python3 -m json.tool
```

### Recupera il technical spec approvato

```bash
curl -s http://localhost:4003/api/v1/catalog/integrations/$INTEGRATION_ID/technical-spec \
  | python3 -m json.tool
```

---

## Note operative

| Aspetto | Dettaglio |
|---------|-----------|
| **Trigger** | Solo dopo approvazione functional spec (`technical_status: TECH_PENDING`) |
| **Concorrenza** | Nessun lock globale — ogni integrazione genera il tecnico in modo indipendente |
| **Feedback loop** | Stesso meccanismo del funzionale: Reject → feedback → Regenerate |
| **Timeout LLM** | Se generazione fallisce, `technical_status` ritorna a `TECH_PENDING` automaticamente |
