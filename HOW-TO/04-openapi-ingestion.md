# 04 — Gestire le sorgenti OpenAPI (Ingestion Platform)

Registra una specifica OpenAPI/Swagger, indicizzala automaticamente nella KB e tienila aggiornata. Tutto gestibile dalla dashboard senza toccare terminale o n8n.

**Flusso:** Registra sorgente → triggera → fetch spec → parse → diff → chunk → index in ChromaDB → disponibile al RAG.

---

## Dove si trova

Sidebar → **Ingestion Sources** (gruppo *Knowledge Base*).

---

## Registrare una nuova sorgente OpenAPI

1. Clicca **+ Add Source** in alto a destra
2. Compila il form:

   | Campo | Cosa inserire | Esempio |
   |-------|--------------|---------|
   | **Source code** | Identificativo univoco (solo minuscolo, cifre, `_`) | `plm_api_v1` |
   | **Source type** | Scegli **OpenAPI** | — |
   | **URL spec** | URL diretto al file JSON o YAML della spec | `http://mate-plm-mock:3001/openapi.json` |
   | **Tags** | Uno o più tag per il RAG (Enter per aggiungere) | `plm`, `product` |
   | **Refresh schedule** | Ogni quanto rieseguire l'ingestion automatica | *Every 6 hours* |
   | **Description** | Opzionale — appare nella lista | `PLM Mock API` |

   > Per le API interne usa il nome container Docker come hostname, non `localhost`:
   > ✅ `http://mate-plm-mock:3001/openapi.json`
   > ❌ `http://localhost:3001/openapi.json`

3. Clicca **Register Source**

La sorgente appare nella tabella con stato **active**.

---

## Avviare l'ingestion manualmente

Nella riga della sorgente, clicca il tasto ▶ (**Play**).

- Il bottone mostra uno spinner mentre l'ingestion è in corso
- Arriva una notifica in alto a destra con l'esito:
  - ✅ *"plm_api_v1 ingested successfully (14 chunks)"*
  - ⚠️ *"ingested with warnings"* — alcuni chunk hanno avuto errori ma l'indicizzazione è parzialmente riuscita
  - ❌ *"ingestion failed"* — vedi Run History per i dettagli

> L'ingestion funziona in background: la pagina resta usabile durante l'elaborazione.

---

## Verificare il risultato

Clicca sulla riga (o la freccia ▼) per espandere il pannello di dettaglio.

### Run History

Mostra gli ultimi 20 run con:

| Colonna | Significato |
|---------|-------------|
| Status | `success` / `failed` / `partial` / `running` |
| Trigger | `manual` (tu) · `scheduler` (automatico) · `webhook` (n8n) |
| Started | Data e ora di avvio |
| Duration | Tempo impiegato |
| Chunks | Numero di chunk indicizzati in ChromaDB |
| 🔴 | Clicca per espandere i messaggi di errore |

### Snapshots

Mostra le ultime versioni indicizzate della spec con:
- **Hash** abbreviato — identifica univocamente il contenuto
- Badge **current** — indica lo snapshot attivo
- **Diff summary** — descrizione testuale delle modifiche rispetto alla versione precedente (generata via Claude se `ANTHROPIC_API_KEY` è configurata)

---

## Mettere in pausa / riattivare

Nella riga della sorgente, clicca il tasto ⏸ (**Pause**) o ▶ (**Activate**).

- **Paused** → lo scheduler n8n salta questa sorgente; i chunk esistenti rimangono in ChromaDB
- **Active** → la sorgente torna nel ciclo automatico

---

## Eliminare una sorgente

1. Clicca 🗑 nella riga della sorgente
2. Clicca **Confirm** per confermare

> I chunk indicizzati in ChromaDB vengono eliminati al prossimo run di questa sorgente o manualmente via KB management. La sorgente scompare dalla lista immediatamente.

---

## Monitorare la salute del servizio

In fondo alla sidebar trovi il dot **Ingestion (4006)**:

- 🟢 Verde — servizio raggiungibile
- 🔴 Rosso — servizio non risponde (controlla `docker ps | grep ingestion`)

---

## Schedulazione automatica con n8n

Una volta registrata, la sorgente viene triggerata automaticamente da n8n secondo il `refresh_cron` impostato. Non serve configurazione aggiuntiva.

| Workflow | Comportamento |
|----------|--------------|
| **WF-01** — Scheduler | Triggera ogni sorgente *active* secondo `refresh_cron` ogni ora |
| **WF-06** — Breaking Change Notify | Alert giornaliero se rileva endpoint rimossi |

Per attivare WF-01: apri `http://<EC2_IP>:8080/n8n/` → workflow WF-01 → **Activate**.

---

## Registrare anche il PIM mock (esempio pratico)

Ripeti i passi di registrazione con questi valori:

| Campo | Valore |
|-------|--------|
| Source code | `pim_api_v1` |
| Source type | OpenAPI |
| URL spec | `http://mate-pim-mock:3002/openapi.json` |
| Tags | `pim`, `product`, `catalog` |

---

## Domande frequenti

**I chunk rimangono se metto in pausa la sorgente?**
Sì. La pausa blocca solo i run automatici. I chunk restano in ChromaDB e continuano ad essere usati dal RAG.

**Cosa succede se la spec non è cambiata?**
L'ingestion confronta l'hash SHA-256 del contenuto. Se non è cambiato, il run termina immediatamente senza riscrivere nulla (vedi colonna *Chunks = 0* nella Run History).

**Il diff summary non compare — perché?**
Richiede `ANTHROPIC_API_KEY` configurata nel `.env`. Senza chiave il summary è assente ma l'ingestion funziona normalmente.

**Posso avere più URL per la stessa sorgente?**
Sì — nella modal clicca **+ Add URL** per aggiungere entrypoint aggiuntivi.

**Come verifico che i chunk siano effettivamente cercabili?**
Vai a **Knowledge Base → Search** e cerca un termine relativo all'API (es. `product lifecycle endpoint`).

---

## Via API (alternativa avanzata)

Se preferisci curl o stai automatizzando da script:

```bash
# Registra sorgente
curl -s -X POST http://localhost:4006/api/v1/sources \
  -H "Content-Type: application/json" \
  -d '{
    "code": "plm_api_v1",
    "source_type": "openapi",
    "entrypoints": ["http://mate-plm-mock:3001/openapi.json"],
    "tags": ["plm", "product"],
    "refresh_cron": "0 */6 * * *"
  }' | python3 -m json.tool

# Triggera ingestion (sostituisci src_a1b2c3d4 con l'id ricevuto)
curl -s -X POST http://localhost:4006/api/v1/ingest/openapi/src_a1b2c3d4 \
  | python3 -m json.tool

# Controlla stato del run (run_id dalla risposta precedente)
curl -s http://localhost:4006/api/v1/runs/run_20260331103045_src_a1b2 \
  | python3 -m json.tool

# Lista run di una sorgente
curl -s http://localhost:4006/api/v1/sources/src_a1b2c3d4/runs \
  | python3 -m json.tool

# Lista snapshot di una sorgente
curl -s http://localhost:4006/api/v1/sources/src_a1b2c3d4/snapshots \
  | python3 -m json.tool
```

---

## Note tecniche

| Aspetto | Dettaglio |
|---------|-----------|
| **Chunk ID** | `src_{code}-chunk-{n}` — non collide mai con upload manuali (`KB-…`) |
| **ETag support** | Il fetcher usa `If-None-Match` se il server supporta HTTP ETag |
| **Low confidence** | Capabilities con confidence < 0.7 incluse con metadato `low_confidence=true` |
| **Re-index** | Prima dell'upsert vengono eliminati tutti i chunk precedenti della stessa sorgente |
