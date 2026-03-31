# HOW-TO 03 — Generare documenti di integrazione

Il flusso end-to-end produce due documenti per ogni integrazione: il **Functional Design** (approvato da un umano) e il **Technical Design** (generato dopo l'approvazione).

---

## Panoramica del flusso

```
1. Carica CSV requisiti
       ↓
2. Configura tag e conferma
       ↓
3. Trigger agente AI
       ↓
4. HITL Review — approva o rigetta il Functional Design
       ↓
5. [Automatico] Genera Technical Design
       ↓
6. Scarica o visualizza i documenti
```

---

## Step 1 — Caricare i requisiti (CSV)

1. Vai a **Requirements** nella sidebar
2. Clicca **Upload CSV**
3. Il file deve avere almeno le colonne: `source_system`, `target_system`, `description`
4. Dopo l'upload i requisiti appaiono nella lista

> Formato di esempio:
> ```csv
> source_system,target_system,description
> PLM,PIM,Sync product catalog on publish
> PIM,DAM,Transfer approved media assets
> ```

---

## Step 2 — Configurare i tag

I tag guidano il retrieval RAG: l'agente cerca solo i chunk KB con tag corrispondenti.

1. Nella schermata Requirements seleziona una riga
2. I tag vengono suggeriti automaticamente dall'LLM (es. `plm`, `product`, `sync`)
3. Modifica se necessario
4. Clicca **Confirm Tags**

---

## Step 3 — Trigger agente

1. Vai a **Agent Workspace**
2. Seleziona il progetto e i requisiti da processare
3. Clicca **Generate Documents**
4. Segui i log in tempo reale nel pannello destro

L'agente:
- Espande la query in 4 varianti (2 template + 2 LLM)
- Recupera chunk KB rilevanti (BM25 + ChromaDB dense retrieval)
- Genera il Functional Design con il meta-prompt

La generazione termina con stato `PENDING` — il documento è in attesa di revisione umana.

---

## Step 4 — HITL Review (Functional Design)

1. Vai a **HITL Approvals**
2. Seleziona il documento in coda
3. Leggi il Functional Design nel pannello destro
4. **Opzioni disponibili:**
   - **Approve & Save to RAG** — approva e salva in ChromaDB come esempio futuro
   - **Reject (Retry)** — rigetta con feedback; l'agente rigenera tenendo conto dei commenti
5. Dopo l'approvazione il documento passa a stato `generated` e viene avviata automaticamente la generazione del Technical Design (`TECH_PENDING`)

---

## Step 5 — Technical Design

Il Technical Design viene generato dopo l'approvazione del Functional Design.

1. Vai a **Integration Catalog**
2. Trova la card dell'integrazione — se `TECH_PENDING` compare il bottone **Genera Technical Design**
3. Clicca il bottone
4. Attendi la generazione (stato: `TECH_GENERATING` → `TECH_REVIEW` → `TECH_DONE`)

> Il Technical Design usa il Functional Design approvato come contesto primario, più la KB per le best practice tecniche.

---

## Step 6 — Visualizzare e scaricare

### Dalla pagina Generated Docs
1. Vai a **Generated Docs**
2. Seleziona l'integrazione nella lista sinistra
3. Clicca **Functional** o **Technical** per visualizzare
4. Clicca **⬇ Functional** / **⬇ Technical** per scaricare il `.md`

### Dalla pagina Integration Catalog
- Ogni card mostra i bottoni **📋 Functional Spec** e **View Technical Spec**
- Accanto a ciascuno c'è il bottone **⬇ Download**

---

## Rigenerare un documento

Se il documento non è soddisfacente dopo l'approvazione:

1. Vai a **Integration Catalog** → trova la card
2. Clicca i tre puntini o il bottone **Regenerate** (se disponibile)
3. Il documento torna in stato `PENDING` e riparte il ciclo HITL

Per il Technical Design: se è in stato `TECH_DONE`, non è possibile rigenerare direttamente — contatta l'admin per un reset manuale dello stato.
