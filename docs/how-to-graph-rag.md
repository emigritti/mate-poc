# How-To: LLM Wiki e Graph RAG (ADR-052)

> **Audience:** Analisti, sviluppatori e operatori che vogliono capire come funziona il Graph RAG, come navigare la LLM Wiki e come gestire migrazione o import della Knowledge Base.

---

## Panoramica

La **LLM Wiki** trasforma la Knowledge Base (KB) da un flat vector store in un **knowledge graph navigabile**. Ogni documento caricato in KB genera automaticamente entità (sistemi, API, regole, stati, campi…) e relazioni tipizzate tra di esse. Queste strutture sono poi usate in due modi:

1. **Graph RAG** — il retriever, dopo la ricerca BM25+dense classica, percorre il grafo per trovare chunk *correlati per relazione* ma non necessariamente simili per embedding. Questo migliora la qualità delle risposte dell'agente su query che coinvolgono flussi multi-documento.
2. **LLM Wiki UI** — un'interfaccia a tre tab per esplorare entità, relazioni e il grafo visivo (React Flow), accessibile dalla voce **LLM Wiki** nella sidebar.

Il layer grafo è **completamente additivo**: ChromaDB, BM25 e tutto il retrieval esistente rimangono invariati. Se il grafo non è stato ancora costruito, il sistema si comporta esattamente come prima.

---

## Come funziona il Graph RAG — schema concettuale

```
Upload KB doc
      │
      ▼
[wiki_extractor]  ←─── chunk metadata v2 (entity_names, system_names,
      │                state_transitions, semantic_type, …)
      ▼
[WikiGraphBuilder]
  ├── upsert wiki_entities    (MongoDB)
  └── upsert wiki_relationships (MongoDB)
                    │
                    ▼
         Grafo persistente
                    │
     ┌──────────────┘
     │  Al momento del retrieval:
     ▼
[retriever.py — step 8]
  1. top-5 chunk primari → raccoglie chunk_ids (seed)
  2. trova entità in wiki_entities con quei chunk_ids
  3. $graphLookup su wiki_relationships (profondità max 2)
  4. raccoglie chunk_ids delle entità raggiungibili
  5. fetch da ChromaDB → ScoredChunk con score=0.05
  6. merge + re-sort con risultati primari
     │
     ▼
[ContextAssembler]
  aggiunge sezione "## KNOWLEDGE GRAPH CONTEXT"
  con label entità + tipo relazione + testo chunk
```

### Tipi di entità estratti automaticamente

| Tipo | Estratto da |
|---|---|
| `system` | `system_names` nel metadata chunk |
| `api_entity` | `entity_names` con `semantic_type = entity_definition` |
| `business_term` | `business_terms` |
| `state` | Nodi di `state_transitions` (formato "A -> B") |
| `rule` | `entity_names` con `semantic_type = business_rule` |
| `field` | `field_names` (quando ≥3 campi nello stesso chunk) |
| `process` | `entity_names` con `semantic_type = integration_flow` |
| `generic` | Fallback per entità non classificate |

### Tipi di relazione estratti automaticamente

| Relazione | Quando viene creata |
|---|---|
| `TRANSITIONS_TO` | Coppie "A → B" in `state_transitions` |
| `MAPS_TO` | `semantic_type = data_mapping_candidate` + ≥2 entità |
| `CALLS` | `semantic_type = api_contract` + ≥2 system_names |
| `GOVERNS` | `semantic_type = business_rule` + entity_name |
| `TRIGGERS` | `semantic_type = event_definition` + entity_name |
| `HANDLES_ERROR` | `semantic_type = error_handling` + entity_name |
| `DEFINED_BY` | `semantic_type = field_definition` + entity + system |
| `RELATED_TO` | Co-occorrenza di ≥2 entità nello stesso chunk (fallback) |

---

## Step 1 — Primo utilizzo: caricare un documento in KB

Il grafo si costruisce **automaticamente** ad ogni upload di file in KB, senza nessuna azione aggiuntiva.

1. Naviga su **Knowledge Base** nella sidebar.
2. Carica un file PDF, DOCX o Markdown tramite il pulsante **Upload**.
3. Il sistema esegue in background (in ordine):
   - Docling parsing + chunking semantico
   - Embedding ChromaDB
   - Arricchimento metadata v2
   - **Costruzione grafo wiki** (WikiGraphBuilder per quel documento)
4. Dopo qualche secondo, vai su **LLM Wiki** — dovresti vedere le prime entità nella tab Entities.

> **Nota:** La build automatica può richiedere qualche secondo per documenti grandi. Se le entità non compaiono subito, attendi e ricarica la pagina.

---

## Step 2 — Esplorare la LLM Wiki

Naviga su **LLM Wiki** nella sidebar (gruppo Knowledge Base).

### Tab Entities — lista entità

- Usa la **barra di ricerca** in alto per cercare entità per nome (ricerca live full-text).
- Filtra per **tipo** con il dropdown `entity_type`.
- Filtra per **tag** con il campo tag (corrispondenza parziale).
- Ogni riga mostra: nome, badge tipo colorato, numero di chunk sorgente, tag.
- **Clicca su un'entità** per aprire il dettaglio nella tab Entity Detail.

### Tab Entity Detail — dettaglio entità

La pagina dettaglio mostra:

- **Header**: nome entità, badge tipo, numero chunk, documenti sorgente (doc_ids)
- **Outgoing edges**: relazioni uscenti — tipo badge, entità destinazione (cliccabile per navigare), barra peso, link al chunk di evidenza
- **Incoming edges**: stessa struttura per le relazioni in entrata
- **Source chunks**: fino a 3 preview del testo originale con label `semantic_type`

### Tab Graph View — grafo visivo

- Il canvas React Flow mostra il grafo centrato sull'entità selezionata (o un subset del grafo completo, max 50 nodi).
- **Nodi** colorati per `entity_type`; **archi** etichettati con `rel_type`.
- Gli archi `TRANSITIONS_TO` sono animati.
- Usa il **filtro rel_type** nella sidebar del canvas per nascondere tipi di relazione non rilevanti.
- **Clicca su un nodo** per aprire il suo Entity Detail.
- Usa zoom, pan e minimap per navigare grafi grandi.

---

## Step 3 — Usare il Graph RAG nell'agente

Il Graph RAG è attivo per default. Non richiede configurazione aggiuntiva: dopo aver costruito il grafo, le risposte dell'agente migliorano automaticamente.

**Come verificare che funzioni:**

1. Avvia una generazione dalla pagina **Agent Workspace**.
2. Osserva i log in tempo reale — cerca la riga:
   ```
   [RAG] wiki_graph chunks injected: N
   ```
   Se `N > 0`, il grafo ha contribuito al contesto.
3. Nel documento generato, la sezione LLM riceve un contesto aggiuntivo:
   ```
   ## KNOWLEDGE GRAPH CONTEXT (related concepts from LLM Wiki):
   ### Source: wiki_graph · entity: OrderStatus · type: state_model
   [testo del chunk correlato]
   ```

**Se vuoi disabilitare temporaneamente il Graph RAG** (ad esempio per confrontare la qualità delle risposte), imposta la variabile d'ambiente:
```
WIKI_GRAPH_RETRIEVAL_ENABLED=false
```
e riavvia il container integration-agent. Non è necessario eliminare il grafo.

---

## Step 4 — Ricostruire il grafo manualmente

Può essere necessario ricostruire il grafo in questi casi:
- Dopo un import massivo della KB (vedi Step 6)
- Dopo aver modificato `WIKI_LLM_RELATION_EXTRACTION` o altre impostazioni di estrazione
- Se sospetti che il grafo non sia allineato con i documenti correnti

### Via UI (bottone Rebuild)

1. Vai su **LLM Wiki**.
2. Clicca il bottone **Rebuild** nell'header.
3. Un job asincrono parte — il bottone mostra lo stato ("rebuilding…").
4. Al termine le statistiche si aggiornano automaticamente.

Il Rebuild via UI usa le stesse impostazioni del server (incluso `WIKI_LLM_RELATION_EXTRACTION`).

### Via CLI (dentro il container)

```bash
# Rebuild completo (force — sostituisce entità/relazioni esistenti)
docker compose run --rm integration-agent python build_wiki_graph.py --force

# Rebuild incrementale (merge — aggiunge senza cancellare)
docker compose run --rm integration-agent python build_wiki_graph.py

# Rebuild per un singolo documento
docker compose run --rm integration-agent python build_wiki_graph.py --doc-id KB-ABCD1234

# Rebuild con enrichment LLM (usa qwen3:8b per classificare edge RELATED_TO)
docker compose run --rm integration-agent python build_wiki_graph.py --force --llm-assist
```

> **`--force` vs incrementale:** Con `--force` ogni entità viene riscritta da zero (replace_one). Senza `--force`, le liste `doc_ids` e `chunk_ids` vengono solo ampliate con i nuovi valori ($addToSet). Usa `--force` dopo un import o una modifica ai documenti; usa l'incrementale per aggiungere nuovi upload senza toccare il grafo esistente.

### Via API REST

```http
POST /agent/api/v1/wiki/rebuild?force=true&llm_assist=false
Authorization: Bearer <API_KEY>
```

Risposta:
```json
{ "job_id": "uuid-...", "status": "queued" }
```

Polling:
```http
GET /agent/api/v1/wiki/rebuild/{job_id}
```

---

## Step 5 — Migrazione da un ambiente precedente (KB già popolata)

Se hai già una KB con documenti caricati ma il grafo non è ancora stato costruito (ad esempio dopo un upgrade da una versione precedente all'ADR-052), segui questi passaggi:

### 5.1 Verifica lo stato attuale

```bash
# Controlla quante entità esistono
curl http://localhost:8080/agent/api/v1/wiki/stats
```

Se `total_entities = 0` con una KB popolata, il grafo non è ancora stato costruito.

### 5.2 Controlla quanti chunk ci sono in KB

```bash
curl http://localhost:8080/agent/api/v1/kb/stats
```

Prendi nota del campo `total_chunks`.

### 5.3 Esegui il build iniziale

```bash
docker compose run --rm integration-agent python build_wiki_graph.py --force
```

L'output mostra:
```
12:00:00  INFO  build_wiki_graph — ChromaDB knowledge_base: 1247 chunks
12:00:05  INFO  build_wiki_graph — Build complete — entities: 142, relationships: 318
```

### 5.4 Verifica il risultato

```bash
curl http://localhost:8080/agent/api/v1/wiki/stats
```

```json
{
  "total_entities": 142,
  "total_relationships": 318,
  "entity_type_breakdown": {
    "system": 12,
    "api_entity": 45,
    "state": 28,
    ...
  },
  "top_entities": [...]
}
```

### 5.5 Controllo idempotenza

Esegui il build una seconda volta per verificare che i contatori non cambino:

```bash
docker compose run --rm integration-agent python build_wiki_graph.py --force
```

Se `entities` e `relationships` sono uguali al run precedente, il build è idempotente e il grafo è stabile.

---

## Step 6 — Dopo un import della KB (ADR-051)

Quando usi la funzione **Import KB** (da file JSON bundle), i nuovi documenti vengono inseriti in ChromaDB ma il grafo **non viene aggiornato automaticamente** durante l'import. Devi ricostruirlo manualmente dopo.

### Procedura completa

1. **Esegui l'import della KB** (via UI o API — vedi ADR-051 how-to).
   ```http
   POST /agent/api/v1/kb/import
   Authorization: Bearer <API_KEY>
   Content-Type: multipart/form-data

   bundle_file=<kb_export.json>
   ```

2. **Attendi il completamento** — l'import risponde con un `KBImportResult`:
   ```json
   { "documents_imported": 8, "chunks_imported": 412, ... }
   ```

3. **Ricostruisci il grafo** con `--force` per includere i nuovi documenti:
   ```bash
   docker compose run --rm integration-agent python build_wiki_graph.py --force
   ```
   Oppure via UI: bottone **Rebuild** nella pagina LLM Wiki.

4. **Verifica** che `total_entities` sia aumentato rispetto al valore pre-import.

> **Perché `--force` e non incrementale?**
> L'import può sovrascrivere documenti esistenti (`overwrite=true`). Un rebuild incrementale non rimuoverebbe le entità orfane di documenti rimpiazzati. Con `--force` il grafo rispecchia esattamente lo stato corrente della KB.

---

## Step 7 — Configurazione avanzata

Tutte le impostazioni possono essere passate come variabili d'ambiente nel file `.env` o nel `docker-compose.yml`.

| Variabile | Default | Effetto |
|---|---|---|
| `WIKI_GRAPH_RETRIEVAL_ENABLED` | `true` | Abilita/disabilita lo step 8 nel retriever. `false` = no-op immediato, nessun riavvio necessario se cambiata a runtime tramite env |
| `WIKI_GRAPH_MAX_DEPTH` | `2` | Profondità massima del `$graphLookup` (hops). Aumentare a `3` per grafi sparsi; abbassare a `1` per risposte più veloci |
| `WIKI_GRAPH_MAX_NEIGHBOURS` | `10` | Numero massimo di entità vicine considerate per query |
| `WIKI_GRAPH_SCORE_BONUS` | `0.05` | Score assegnato ai chunk wiki-graph. Tenerlo < il minimo score primario per non far scalare i chunk wiki sopra quelli diretti |
| `WIKI_LLM_RELATION_EXTRACTION` | `false` | Se `true`, usa qwen3:8b per classificare gli edge `RELATED_TO` in tipi più specifici. Rallenta il build ma migliora la qualità del grafo |
| `WIKI_RAG_MAX_CHARS` | `1500` | Limite caratteri per la sezione `## KNOWLEDGE GRAPH CONTEXT` nel prompt. Aumentare se i documenti sono molto tecnici |
| `WIKI_GRAPH_TYPED_EDGES_ONLY` | `true` | Se `true`, sopprime gli edge `RELATED_TO` quando esiste già un edge tipizzato tra le stesse due entità |
| `WIKI_AUTO_BUILD_ON_UPLOAD` | `true` | Build automatica del grafo ad ogni upload KB. Disabilitare solo se si preferisce il controllo manuale |

**Esempio `.env`:**
```
WIKI_GRAPH_MAX_DEPTH=3
WIKI_LLM_RELATION_EXTRACTION=true
WIKI_RAG_MAX_CHARS=2000
```

---

## Step 8 — Rollback / disabilitazione completa

Il layer graph è additivo e non tocca ChromaDB. Il rollback è reversibile a qualsiasi livello:

### Disabilitare solo il Graph RAG (mantieni il grafo)

```
WIKI_GRAPH_RETRIEVAL_ENABLED=false
```
Il retrieval torna al comportamento pre-ADR-052. Il grafo è ancora navigabile dalla UI.

### Disabilitare la build automatica su upload

```
WIKI_AUTO_BUILD_ON_UPLOAD=false
```
I nuovi upload non aggiornano più il grafo. Utile durante import massivi.

### Eliminare il grafo (senza toccare la KB)

```bash
# Connettiti a MongoDB e droppa le collection wiki
docker compose exec mongodb mongosh mate_rag --eval "
  db.wiki_entities.drop();
  db.wiki_relationships.drop();
  print('Wiki graph dropped.')
"
```

Il retriever legge `wiki_entities_col is None` e salta silenziosamente lo step 8. La KB e tutti i documenti generati rimangono intatti.

### Rimuovere la voce dalla sidebar (frontend)

In `services/web-dashboard/src/components/layout/Sidebar.jsx`, rimuovi la riga:
```javascript
{ id: 'wiki', label: 'LLM Wiki', icon: Network },
```
e ricompila il frontend.

---

## Riferimenti

| Documento | Contenuto |
|---|---|
| [ADR-052](adr/ADR-052-llm-wiki-graph-rag.md) | Decisioni architetturali, alternative valutate, rollback strategy |
| [Functional Guide §18](functional-guide.md#18-llm-wiki--graph-rag-adr-052) | Descrizione funzionale per utenti finali |
| [Architecture Specification](architecture_specification.md) | Endpoints API, data model, ADR table |
| [How-To: KB Export/Import](how-to-html-ingestion.md) | Import/export della Knowledge Base (ADR-051) |
