# Document Generation Pipeline — Step-by-Step Guide

## Functional Integration Mate PoC

| Metadata | |
|---|---|
| **Versione** | 1.0 |
| **Data** | 2026-04-21 |
| **Scope** | Integration Spec generation — dal trigger al documento in coda HITL |

---

## Panoramica

Quando l'utente carica i requisiti CSV e preme **"Start Agent"**, il sistema esegue una pipeline agentica composta da **12 step principali** che trasformano i requisiti grezzi in un Integration Design Document completo, strutturato in 16 sezioni, pronto per la revisione umana (HITL).

```
CSV Requirements → [1] Parsing → [2] Profile Resolution → [3] Hybrid Retrieval
                → [4] Context Assembly → [5] FactPack Extraction
                → [6] FactPack Validation → [7] Document Rendering
                → [8] Output Sanitization → [9] Claude Enrichment (opt.)
                → [10] Quality Assessment → [11] Report Building
                → [12] HITL Queue
```

**Due percorsi di generazione:**

| Percorso | Trigger | Vantaggi |
|---|---|---|
| **FactPack Path** | `fact_pack_enabled=True` e estrazione riuscita | Struttura dati intermedia → documenti più precisi e tracciabili |
| **Single-Pass Fallback** | FactPack disabilitato o fallito | Più veloce, nessuna dipendenza da API esterna |

---

## Step 1 — Parsing Requisiti e Avvio Task

### Descrizione
Il trigger endpoint riceve la richiesta, valida i parametri, risolve gli chunk pinned dal corpus KB in-memory, inizializza i log e avvia il task agentico asincrono.

### Tecnologia
- **FastAPI** endpoint `POST /api/v1/agent/trigger`
- **asyncio** `create_task()` per esecuzione non-bloccante
- **Pydantic** `TriggerRequest` per validazione input

### Perché viene eseguito
Il task viene separato dalla risposta HTTP (che ritorna immediatamente con `task_id`) così il client non deve attendere minuti per la risposta. Il dashboard traccia il progresso via polling `/agent/logs`.

### Parametri di input
| Campo | Tipo | Default | Significato |
|---|---|---|---|
| `llm_profile` | string | `"default"` | Profilo LLM da usare: `default` o `high_quality` |
| `pinned_doc_ids` | list[str] | `[]` | ID documenti KB da forzare nel contesto |

### Risultati possibili
| Risultato | Condizione |
|---|---|
| `{"status": "started", "task_id": "A3F9B2C1"}` | Sempre (task avviato) |
| `{"status": "error", "detail": "Agent is already running"}` | Se agente già attivo (lock acquisito) |
| `{"status": "error", "detail": "No TAG_CONFIRMED entries"}` | Nessun requisito confermato in memoria |

### Esempi log
```
Started Agent Processing Task
[PINNED] 3 chunk(s) pinned from 2 doc(s): ['KB-A1B2', 'KB-C3D4']
Processing 4 TAG_CONFIRMED integration(s)...
[STEP 1/4] HAI-BE5053 — AEM Asset → AWS S3 (3 requirement(s), tags: ['Data Sync'])
```

---

## Step 2 — Risoluzione Profilo LLM

### Descrizione
Determina quale modello e quali parametri di campionamento usare per la generazione, in base al profilo selezionato (`default` o `high_quality`). Consulta il dizionario `llm_overrides` (caricato da MongoDB) prima di usare i default da `config.py`.

### Tecnologia
- **`services/llm_service.py`** — dizionario `llm_overrides` globale
- **`config.py`** — valori default (pydantic-settings)
- **MongoDB `llm_settings` collection** — overrides persistiti

### Perché viene eseguito
Permette di cambiare modello, timeout e parametri di campionamento a runtime senza restart del container. La gerarchia di risoluzione è: **override esplicito > llm_overrides > settings default**.

### Profili disponibili
| Profilo | Chiave MongoDB | Modello default | Uso |
|---|---|---|---|
| `default` | `doc_llm` | `qwen2.5:14b` | Generazione standard |
| `high_quality` / `premium` | `premium_llm` | `gemma4:26b` | Integrazioni complesse |
| *(tagging)* | `tag_llm` | `qwen3:8b` | Suggestion tag — sempre fast-utility |

### Risultati possibili
| Risultato | Condizione |
|---|---|
| `_llm_kw` popolato con tutti i parametri premium | `llm_profile = "high_quality"` |
| `_llm_kw = {provider: "ollama"}` (legge i default da overrides) | `llm_profile = "default"` |

### Esempi log
```
[LLM] profile='default' model=qwen2.5:14b
[LLM] profile='high_quality' model=gemma4:26b
```

---

## Step 3 — Hybrid Retrieval (RAG)

### Descrizione
Recupera chunk rilevanti da tre sorgenti in parallelo usando una pipeline ibrida BM25 + ChromaDB dense:
1. **Approved Integrations** — documenti di integrazione approvati in passato
2. **Knowledge Base** — best practice, guide, documenti di riferimento
3. **URL KB** — contenuto live da URL linkati nella KB
4. **RAPTOR Summaries** — riassunti sezione-livello per contesto ad alto livello

Per ogni sorgente, la retrieval pipeline esegue 5 sotto-step: Query Expansion → ChromaDB → BM25 → Ensemble Merge → Threshold + TF-IDF Rerank + Semantic Bonus.

### Tecnologia
- **`services/retriever.py`** — `HybridRetriever` singleton
- **ChromaDB** — dense retrieval (L2 distance)
- **rank-bm25** `BM25Plus` — sparse retrieval in-memory
- **scikit-learn** `TfidfVectorizer` — re-ranking
- **Ollama** — query expansion LLM (modello `tag_llm`)

### Perché viene eseguito
Il retrieval ibrido (BM25 + dense) compensa i punti deboli di ciascun approccio: BM25 è preciso su match lessicali esatti, il dense retrieval cattura la similarità semantica. La combinazione riduce i falsi negativi e migliora la qualità del contesto iniettato nel prompt.

### Sotto-step della pipeline

#### 3a — Query Expansion
Genera 2–4 varianti della query per aumentare la copertura semantica.

| Variante | Generazione |
|---|---|
| Query originale | Copia dei requisiti concatenati |
| Template variant | `"{source} to {target} {category} integration pattern"` |
| LLM variant 1–2 | Generazione via `tag_llm` con perspective intent-aware |

**Esempi log:**
```
[RAG] Query expansion: 4 variants (2 template + 2 LLM, intent='')
[RAG] Query expansion LLM unavailable — using 2 template variants: httpx.ConnectError
```

#### 3b — ChromaDB Dense Query
Interroga la collezione con tutte le varianti, filtra per tag (whole-token match), deduplica per `doc_id`.

#### 3c — BM25 Sparse Query
Interroga l'indice BM25Plus in-memory costruito da tutti i chunk nella collezione, deduplica per indice chunk.

**Esempi log:**
```
[RAG] Retrieved: 12 Chroma + 8 BM25 chunks
```

#### 3d — Ensemble Merge
Combina i punteggi con pesi configurabili:
- `score_finale = (1 - rag_bm25_weight) * score_chroma + rag_bm25_weight * score_bm25`
- Default: 60% ChromaDB + 40% BM25

#### 3e — Threshold + TF-IDF Rerank + Semantic Bonus
1. **Threshold:** scarta chunk con `score < 1/(1 + rag_distance_threshold)` (default 0.8 → min 0.56)
2. **TF-IDF rerank:** `score_finale = 0.5 * ensemble + 0.5 * tfidf_cosine`
3. **Semantic Bonus v2:** +0.08 per chunk il cui `semantic_type` corrisponde all'intent (solo chunk con metadata v2)

**Esempi log:**
```
[RAG] Threshold (0.56): 20 → 11 chunks.
[RAG] TF-IDF re-rank failed, using score order: not enough documents
[RAG] Final: 5 chunks after ensemble+threshold+rerank+semantic_bonus (intent='')
```

### Risultati possibili
| Risultato | Condizione |
|---|---|
| 5 chunk approvati + 5 KB + 1 URL + 3 summary | Pipeline completa, KB popolata |
| 0 chunk approvati, 3 KB | Nessuna integrazione approvata simile |
| `url_raw = ""` | Nessun URL KB corrispondente ai tag |
| Fallback a 2 varianti template | Ollama non disponibile per query expansion |

---

## Step 4 — Context Assembly

### Descrizione
Combina tutti i chunk recuperati in un'unica stringa di contesto strutturata, rispettando il budget di caratteri per profilo, nell'ordine: summary chunks → approved chunks → KB chunks → URL chunks → pinned chunks.

### Tecnologia
- **`services/rag_service.py`** — `ContextAssembler.assemble()`
- Budget caratteri: `settings.ollama_rag_max_chars` (default 5000)

### Perché viene eseguito
Il modello LLM ha una finestra di contesto limitata (`num_ctx`). Il `ContextAssembler` garantisce che i chunk più rilevanti vengano inclusi per primi e che il totale non superi il budget, prevenendo il troncamento silenzioso dell'input.

### Struttura output
```
## DOCUMENT SUMMARIES
[RAPTOR summaries...]

## PAST APPROVED EXAMPLES
[approved integration chunks...]

## KNOWLEDGE BASE
[KB best-practice chunks...]

[URL content if present]

[Pinned chunks if present]
```

### Esempi log
```
[RAG] Assembled context: 4832 chars
[RAG] Assembled context: 3200 chars [with feedback: 245 chars]
```

### Risultati possibili
| Risultato | Condizione |
|---|---|
| `rag_context` con 3000–5000 chars | KB popolata, retrieval efficace |
| `rag_context = ""` | Nessun chunk supera il threshold, KB vuota |
| Contesto troncato al budget | Troppi chunk, budget superato |

---

## Step 5 — FactPack Extraction

### Descrizione
Step esclusivo del **FactPack Path**. Chiama un LLM per estrarre un oggetto JSON strutturato (FactPack) dal contesto RAG, contenente tutti i fatti chiave dell'integrazione: scope, attori, sistemi, entità, regole di business, flussi, validazioni, errori, assunzioni.

Priorità di chiamata: **Claude API** (se `ANTHROPIC_API_KEY` configurata) → **Ollama fallback** (max 2 tentativi).

### Tecnologia
- **`services/fact_pack_service.py`** — `extract_fact_pack()`
- **Anthropic SDK** `claude-sonnet-4-6` (via `ANTHROPIC_API_KEY`)
- **Ollama** modello `settings.ollama_model` come fallback
- **`prompt_builder.build_fact_extraction_prompt()`** — prompt con schema JSON + regole di confidenza

### Perché viene eseguito
Separare l'estrazione dei fatti dalla generazione del documento riduce le allucinazioni: il LLM prima "capisce" i requisiti producendo una struttura dati verificabile, poi in Step 7 usa quella struttura per riempire le sezioni del template. Ogni claim viene etichettato con un livello di confidenza (`confirmed`, `inferred`, `missing_evidence`, `to_validate`).

### Schema JSON estratto (FactPack)
```json
{
  "integration_scope": {"source": "AEM Asset", "target": "AWS S3", "description": "..."},
  "actors": [{"name": "Content Manager", "role": "..."}],
  "systems": [{"name": "AEM", "type": "source", "api": "REST"}],
  "entities": [{"name": "Asset", "fields": ["id", "title", "url"]}],
  "business_rules": ["Asset must be published before sync"],
  "flows": [{"name": "Asset Upload Flow", "steps": ["..."]}],
  "validations": ["Asset size < 100MB"],
  "errors": [{"code": "E001", "description": "S3 write failed", "handling": "retry"}],
  "assumptions": ["S3 bucket pre-exists"],
  "open_questions": ["How to handle versioning?"],
  "evidence": [
    {
      "claim_id": "C001",
      "statement": "AEM triggers on asset publish event",
      "source_chunks": ["chunk-0", "chunk-2"],
      "confidence": "confirmed"
    }
  ]
}
```

### Livelli di confidenza
| Livello | Significato | Rendering nel documento |
|---|---|---|
| `confirmed` | Evidenza diretta nei chunk | Contenuto diretto |
| `inferred` | Derivato per analogia | Contenuto diretto |
| `missing_evidence` | Non trovato nel contesto | `> Evidence gap: [descrizione]` |
| `to_validate` | Incerto, richiede verifica | Contenuto + `> Requires validation: [descrizione]` |

### Esempi log
```
[FactPack] Extracting via Claude API (AEM Asset → AWS S3, 6234 chars)...
[FactPack] Extraction OK (Claude) — 8 claims, 3 rules, 2 flows
[FactPack] Extracting via Ollama (AEM Asset → AWS S3, 6234 chars)...
[FactPack] Extraction OK (Ollama, attempt 1) — 6 claims
[FactPack] Ollama JSON parse failed (attempt 1): JSONDecodeError
[FactPack] All Ollama extraction attempts failed — graceful degradation.
[FactPack] Claude extraction failed (non-blocking): ReadTimeout: HTTPSConnectionPool
```

### Risultati possibili
| Risultato | Condizione | Conseguenza |
|---|---|---|
| FactPack con ≥5 claim | Estrazione riuscita | Procede Step 6 |
| `None` | Tutti i tentativi falliti | Fallback a Single-Pass (Step 7b) |
| `None` | `FACT_PACK_ENABLED=false` | Salta direttamente a Step 7b |

---

## Step 6 — FactPack Validation

### Descrizione
Valida la coerenza strutturale del FactPack estratto: verifica che `source`/`target` corrispondano ai sistemi attesi, che gli array obbligatori non siano vuoti, che i claim ID siano unici e i livelli di confidenza validi.

### Tecnologia
- **`services/fact_pack_service.py`** — `validate_fact_pack()` — logica Python pura, nessuna chiamata LLM

### Perché viene eseguito
Il LLM può produrre JSON leggermente non conforme (es. `target` sbagliato, claim duplicati). La validazione intercetta questi casi prima che influenzino la generazione del documento, rendendo il pipeline deterministico e sicuro.

### Controlli eseguiti
| Controllo | Azione se fallisce |
|---|---|
| `source` e `target` corrispondono ai valori attesi | Aggiunge issue alla lista |
| `flows`, `business_rules`, `systems` non vuoti | Aggiunge issue alla lista |
| Unicità dei `claim_id` | Aggiunge issue alla lista |
| Confidenza nei valori attesi | Aggiunge issue alla lista |
| Ratio `missing_evidence` < 50% | Warning (non blocca) |

### Esempi log
```
[FactPack] Validation passed — no issues.
[FactPack] Validation issues (2): ['source mismatch: expected AEM Asset, got AEM', 'empty flows array']
```

### Risultati possibili
| Risultato | Condizione |
|---|---|
| FactPack validato, pipeline continua | 0 issue critiche |
| FactPack con `validation_issues` popolato | Issue non critiche (warning) |

---

## Step 7a — Document Rendering (FactPack Path)

### Descrizione
Usa il FactPack validato come "knowledge base strutturata" per riempire il template di 16 sezioni. Il prompt include sezione per sezione istruzioni specifiche su quali campi del FactPack usare, riducendo il "content blending" tra sezioni.

### Tecnologia
- **`services/fact_pack_service.py`** — `render_document_sections()`
- **`prompt_builder.build_section_render_prompt()`** — prompt con `_SECTION_INSTRUCTIONS` per ciascuna delle 16 sezioni
- **`services/llm_service.py`** — `generate_with_retry()` (Ollama o Gemini)

### Perché viene eseguito
Separare i fatti dalla presentazione permette al LLM di concentrarsi sulla qualità redazionale invece di dover contemporaneamente "capire" i requisiti e scrivere. Le section instructions impediscono che il contenuto di una sezione invada un'altra.

### Struttura prompt
```
"You are a senior integration architect producing a formal Integration Design document.

Fill EVERY section of the template below using ONLY the facts in the FACT PACK.
Rules:
- For facts with confidence 'missing_evidence': write the section heading then:
  > Evidence gap: [state what specific information is missing]
- For facts with confidence 'to_validate': include the content then append:
  > Requires validation: [state what needs human confirmation]
- NEVER write 'n/a'. If information is absent, use an evidence gap marker instead.

SECTION GUIDANCE — for each section, prioritise only the listed FactPack fields:
[## 1. Overview → use: integration_scope, actors]
[## 2. Scope → use: integration_scope.description, assumptions]
...

Integration: AEM Asset → AWS S3

Requirements:
[concatenated requirements]

FACT PACK (JSON):
{ ...FactPack serializzato... }

TEMPLATE (use this exact section structure):
[template 16 sezioni]

Output ONLY the complete markdown document beginning with # Integration Design."
```

### Parametri LLM usati
| Parametro | Profilo default | Profilo high_quality |
|---|---|---|
| `provider` | `"ollama"` | `"ollama"` (o `"gemini"` se configurato) |
| `model` | `qwen2.5:14b` | `gemma4:26b` |
| `num_predict` | 2000 | 1800 |
| `timeout` | 900s | 900s |
| `temperature` | 0.2 | 0.0 |

### Esempi log
```
[FactPack] Rendering document from FactPack (AEM Asset → AWS S3, 8432 chars prompt)...
[LLM] → model=qwen2.5:14b prompt_chars=8432 timeout=900s num_predict=2000 num_ctx=8192
[LLM] ✓ done — prompt_tokens=1842 generated_tokens=1987 speed=4.3 tok/s total=463.2s (model_load=12.1s)
[FactPack] Render complete — 5823 chars generated.
```

```
[LLM/Gemini] → model=gemini-2.0-flash prompt_chars=8432 timeout=900s max_output_tokens=2000
[LLM/Gemini] ✓ done — response_chars=6012
```

### Risultati possibili
| Risultato | Condizione |
|---|---|
| Markdown 4000–8000 chars, 16 sezioni | LLM completato |
| Markdown troncato < 2000 chars | `num_predict` troppo basso |
| `generation_path = "fact_pack"` | Percorso riuscito |

---

## Step 7b — Document Generation (Single-Pass Fallback)

### Descrizione
Percorso alternativo: costruisce un prompt unico con tutti i requisiti, il contesto RAG e il template, e chiama il LLM una sola volta per generare l'intero documento.

Attivato quando: FactPack disabilitato, estrazione fallita, o come percorso diretto se `fact_pack_enabled=False`.

### Tecnologia
- **`prompt_builder.build_prompt()`** — prompt completo con template + RAG + feedback
- **`services/llm_service.py`** — `generate_with_retry()` con backoff esponenziale (5s, 15s)

### Struttura prompt
```
[Istruzioni sistema dal meta-prompt reusable-meta-prompt.md]

REQUIREMENTS:
{formatted_requirements}

PAST APPROVED EXAMPLES:
{rag_context}

## PREVIOUS REJECTION FEEDBACK (address these issues):
{reviewer_feedback}   ← solo se rigenerazione

TEMPLATE:
[template 16 sezioni]

# Integration Design
```

La riga finale `# Integration Design` è un "seed" di continuazione: il LLM genera direttamente il body del documento senza preamble.

### Retry policy
| Tentativo | Attesa | Errori retried |
|---|---|---|
| 1 | 0s | — |
| 2 | 5s | `TimeoutException`, `ConnectError`, HTTP 5xx |
| 3 | 15s | Come sopra |
| Fallimento | — | Rilancia l'ultima eccezione |

### Esempi log
```
[LLM] Prompt ready for HAI-BE5053 — 9241 chars. Calling qwen2.5:14b...
[LLM] → model=qwen2.5:14b prompt_chars=9241 timeout=900s num_predict=2000 num_ctx=8192
[LLM] ✓ done — prompt_tokens=2032 generated_tokens=1950 speed=3.8 tok/s total=513.2s (model_load=8.4s)
[LLM] ⚠ Attempt 1/3 failed: ReadTimeout — retrying in 5s
[LLM] ✗ All 3 attempts failed: ReadTimeout: timed out after 900s
[FactPack][WARN] Extraction unavailable — falling back to single-pass pipeline.
```

### Campi report impostati
```python
generation_path = "single_pass_fallback"   # o "single_pass_disabled"
fallback_reason = "FactPack extraction failed or returned None — see logs"
```

---

## Step 8 — Output Sanitization

### Descrizione
Valida la struttura del raw output LLM, rimuove preamble non richiesti, applica sanitizzazione XSS via bleach, tronca a `llm_max_output_chars` (50.000).

### Tecnologia
- **`output_guard.sanitize_llm_output()`**
- **bleach** — sanitizzazione HTML (strip=True, mantiene testo)

### Perché viene eseguito
Il LLM può aggiungere testo introduttivo prima del documento ("Sure! Here is the Integration Design..."). Il guard intercetta questo pattern e tronca il preamble. Se il documento non inizia né termina con la struttura attesa, lancia `LLMOutputValidationError` — il documento non prosegue.

### Strategia di ricerca heading
1. **Fast path:** raw inizia con `# Integration Design` → usato as-is
2. **Fallback 1:** `# Integration Design` trovato altrove → strip preamble
3. **Fallback 2:** H1 contenente "Integration Design" (case-insensitive, parole extra OK) → strip preamble
4. **Hard fail:** nessun heading trovato → `LLMOutputValidationError`

### Esempi log
```
[OutputGuard] Preamble detected (342 chars stripped) before 'Integration Design'.
[OutputGuard] Relaxed heading match '# My Integration Design Document' at offset 180 — preamble stripped.
[OutputGuard] Structural guard hard-fail. First 300 chars: "Certainly! Here is a detailed..."
[OutputGuard] Content truncated from 52341 to 50000 chars.
```

### Risultati possibili
| Risultato | Condizione |
|---|---|
| `sanitized` — documento pulito | Heading trovato |
| `LLMOutputValidationError` | Nessun heading → documento scartato |
| Documento troncato | Output > 50.000 chars |

---

## Step 9 — Claude API Enrichment (opzionale, solo Single-Pass)

### Descrizione
Se `ANTHROPIC_API_KEY` è configurata **e** il documento contiene sezioni con `n/a` o appare troncato (< 16 sezioni attese), chiama Claude per completare le sezioni mancanti senza rigenerare l'intero documento.

Eseguito **solo nel Single-Pass path** (nel FactPack path le sezioni incomplete usano gli evidence gap markers).

### Tecnologia
- **Anthropic SDK** `claude-sonnet-4-6`
- **`services/agent_service._enrich_with_claude()`**

### Perché viene eseguito
Ollama su CPU può produrre documenti troncati se `num_predict` è troppo basso o il modello esaurisce la quota. Claude colma le sezioni residue in 5–10 secondi, agendo come "secondo passaggio" economico senza dover rigenerare tutto.

### Esempi log
```
[Claude] Document truncated (12/16 sections) for AEM Asset → AWS S3 — completing...
[Claude] Enriching n/a sections (14 sections present) for AEM Asset → AWS S3...
[Claude] Enrichment complete — 5823 → 7241 chars
[Claude] Enrichment failed (non-blocking): ReadTimeout: connection pool timeout
```

### Risultati possibili
| Risultato | Condizione |
|---|---|
| `claude_was_applied = True`, documento completato | Enrichment riuscito |
| `claude_was_applied = False`, documento originale | `ANTHROPIC_API_KEY` assente o errore |

---

## Step 10 — Quality Assessment

### Descrizione
Analizza il documento prodotto su **9 dimensioni**: 6 segnali di volume (metriche quantitative) + 3 validatori strutturali (analisi sintattica di diagrammi, tabelle e sezioni). Calcola un `quality_score` composito 0–1 e determina se il documento supera il gate.

### Tecnologia
- **`output_guard.assess_quality()`**
- **`output_guard.enforce_quality_gate()`**
- Regex Python pura — nessuna chiamata LLM

### Perché viene eseguito
Documenti di bassa qualità (poche sezioni, troppi `n/a`, nessun diagramma) non devono raggiungere il reviewer umano — o almeno devono essere segnalati. La quality gate è configurabile: `warn` (inoltro con warning) o `block` (documento bloccato).

### 6 Segnali di Volume

| Segnale | Formula | Threshold |
|---|---|---|
| `section_score` | `min(1.0, section_count / 10)` | Min 10 sezioni `##` |
| `na_score` | `max(0.0, 1.0 - na_ratio / 0.30)` | Max 30% sezioni con n/a |
| `word_score` | `min(1.0, word_count / 300)` | Min 300 parole |
| `diagram_score` | `1.0` se presente blocco mermaid | Almeno 1 diagramma |
| `table_score` | `min(1.0, mapping_table_count / 1)` | Almeno 1 tabella pipe |
| `placeholder_score` | `max(0.0, 1.0 - n * 0.25)` | 0 placeholder `[TODO]` |

**Score composito:** `(section + na + word + diagram + table + placeholder) / 6`

### 3 Validatori Strutturali (non influenzano lo score)

| Validatore | Cosa controlla |
|---|---|
| `_validate_mermaid_blocks` | Tipo diagramma riconosciuto, ≥3 linee, nessun nodo stub, frecce presenti |
| `_validate_mapping_tables` | Tabella completa header+separator+dati, header con keyword source/target/field |
| `_validate_section_artifacts` | "High-Level Architecture" → flowchart, "Detailed Flow" → sequenceDiagram, "Data Mapping" → pipe table |

### Esempi log
```
[QUALITY] OK — score 0.83 for HAI-BE5053
[QUALITY] Issues for HAI-BE5053 (score=0.42) — Missing sections (7/10 min); No Mermaid diagram found; word count too low (187 words)
[QUALITY GATE] Document BLOCKED for HAI-BE5053: quality_score=0.42 < min_score=0.60 (issues: Missing sections; No diagram)
[QualityGate] Quality gate failed — score=0.42 (min=0.60): Missing sections; No diagram (mode=warn — document forwarded to HITL)
```

### Risultati possibili
| Risultato | Condizione |
|---|---|
| `passed=True`, `score >= 0.60` | Documento accettato |
| `passed=False`, mode=`warn` | Documento inoltrato con warning |
| `QualityGateError` (mode=`block`) | Documento bloccato, non raggiunge HITL |

---

## Step 11 — Report Building + Traceability Appendix

### Descrizione
Costruisce il `GenerationReport` con tutte le metriche di pipeline e appende al documento un **Appendice di Traceability** con le fonti usate, il percorso di generazione e le statistiche dei claim.

### Tecnologia
- **`services/agent_service._build_traceability_appendix()`**
- **`services/agent_service._build_section_reports()`** (solo FactPack path)
- **`services/agent_service._chunks_to_source_info()`**

### Perché viene eseguito
La traceability è un requisito Accenture: ogni documento deve poter essere ricondotto alle sue fonti. L'appendice permette al reviewer di verificare quali chunk KB hanno influenzato la generazione e con quale confidenza.

### Struttura Appendice (esempio)
```markdown
---
## Appendice — Traceability

**Pipeline:** FactPack Path | **Modello:** qwen2.5:14b | **Data:** 2026-04-21T14:32:11

### Fonti Recuperate
| Tipo | Documento | Score |
|---|---|---|
| Approved Integration | INT-A1B2 — SAP → Salesforce | 0.87 |
| Knowledge Base | REST API Best Practices | 0.74 |
| Summary | SAP Integration Overview | 0.62 |

### Statistiche Claim (FactPack)
- ✅ Confermati: 6 | 🔵 Inferiti: 2 | ⚠ Missing Evidence: 1 | 🔍 Da Validare: 0
```

### Campi del GenerationReport
| Campo | Significato |
|---|---|
| `model` | Modello LLM usato |
| `prompt_chars` | Dimensione prompt (chars) |
| `context_chars` | Dimensione contesto RAG (chars) |
| `quality_score` | Score 0–1 dalla quality assessment |
| `quality_issues` | Lista issue rilevate |
| `claude_enriched` | True se Claude ha completato sezioni |
| `fact_pack_used` | True se percorso FactPack |
| `generation_path` | `"fact_pack"` \| `"single_pass_fallback"` \| `"single_pass_disabled"` |
| `fallback_reason` | Motivazione fallback (se applicabile) |
| `confirmed_claim_count` | Claim con evidenza diretta |
| `missing_evidence_count` | Gap di evidenza documentati |

---

## Step 12 — HITL Queue

### Descrizione
Salva il documento generato e il suo report in MongoDB, crea un record di approvazione con status `PENDING` e lo rende disponibile nel dashboard HITL per review, modifica e approvazione/rifiuto.

### Tecnologia
- **MongoDB** `approvals` collection
- **FastAPI** `routers/approvals.py`
- **React** `HitlApprovalsPage.jsx` — dashboard review

### Perché viene eseguito
Requisito core del sistema: nessun documento raggiunge il catalogo finale senza approvazione umana (Human-In-The-Loop). Il reviewer può approvare, modificare singole sezioni con AI-assist, o rifiutare con feedback per triggerare una rigenerazione.

### Stati del documento
```
PENDING → APPROVED → PROMOTED (in catalogo ChromaDB)
        ↘ REJECTED → (trigger rigenerazione con feedback)
```

### Esempi log
```
Approval APP-A9F3 queued for HITL review.
Generation completed. Pending documents are waiting for HITL approval.
[ERROR] LLM generation failed for HAI-BE5053 — ReadTimeout: timed out after 900s
[GUARD] Output rejected for HAI-BE5053: LLMOutputValidationError: No '# Integration Design' heading
```

### Risultati finali possibili
| Risultato | Condizione |
|---|---|
| `app_id` creato, status `PENDING` | Pipeline completata con successo |
| Documento skippato, errore loggato | Eccezione non gestita (LLM timeout, validazione) |
| Documento bloccato, no approval | Quality gate in mode `block` |

---

## Esempio Log Completo (FactPack Path, Claude API)

```
Started Agent Processing Task
Processing 1 TAG_CONFIRMED integration(s)...
[STEP 1/1] HAI-BE5053 — AEM Asset → AWS S3 (3 requirement(s), tags: ['Data Sync', 'Cloud Storage'])
[LLM] profile='default' model=qwen2.5:14b
[RAG] Hybrid retrieval for HAI-BE5053 (tags=['Data Sync', 'Cloud Storage'])...
[RAG] Query expansion: 4 variants (2 template + 2 LLM, intent='')
[RAG] Retrieved: 8 Chroma + 5 BM25 chunks
[RAG] Threshold (0.56): 13 → 7 chunks.
[RAG] Final: 5 chunks after ensemble+threshold+rerank+semantic_bonus (intent='')
[RAG] Retrieved: 6 Chroma + 4 BM25 chunks
[RAG] Final: 5 chunks after ensemble+threshold+rerank+semantic_bonus (intent='')
[RAG] Assembled context: 4621 chars
[FactPack] Extracting via Claude API (AEM Asset → AWS S3, 6012 chars)...
[FactPack] Extraction OK (Claude) — 9 claims, 4 rules, 2 flows
[FactPack] Validation passed — no issues.
[FactPack] Rendering document from FactPack (AEM Asset → AWS S3, 8241 chars prompt)...
[LLM] → model=qwen2.5:14b prompt_chars=8241 timeout=900s num_predict=2000 num_ctx=8192
[LLM] ✓ done — prompt_tokens=1921 generated_tokens=1998 speed=4.1 tok/s total=487.3s (model_load=9.8s)
[FactPack] Render complete — 6234 chars generated.
[QUALITY] OK — score 0.86 for HAI-BE5053
Approval APP-C7D9 queued for HITL review.
Generation completed. Pending documents are waiting for HITL approval.
```

---

## Esempio Log Completo (Single-Pass Fallback, Gemini)

```
Started Agent Processing Task
Processing 1 TAG_CONFIRMED integration(s)...
[STEP 1/1] HAI-FF1234 — SAP ERP → Salesforce CRM (5 requirement(s), tags: ['B2B', 'CRM Sync'])
[LLM] profile='high_quality' model=gemini-2.0-flash
[RAG] Hybrid retrieval for HAI-FF1234 (tags=['B2B', 'CRM Sync'])...
[RAG] Query expansion: 2 variants (2 template + 0 LLM, intent='')
[RAG] Final: 5 chunks after ensemble+threshold+rerank+semantic_bonus (intent='')
[RAG] Assembled context: 3892 chars
[FactPack] Extracting via Ollama (SAP ERP → Salesforce CRM, 5741 chars)...
[FactPack] Ollama JSON parse failed (attempt 1): JSONDecodeError
[FactPack] All Ollama extraction attempts failed — graceful degradation.
[FactPack][WARN] Extraction unavailable — falling back to single-pass pipeline.
[LLM] Prompt ready for HAI-FF1234 — 9102 chars. Calling gemini-2.0-flash...
[LLM/Gemini] → model=gemini-2.0-flash prompt_chars=9102 timeout=900s max_output_tokens=1800
[LLM/Gemini] ✓ done — response_chars=7841
[Claude] Enriching n/a sections (15 sections present) for SAP ERP → Salesforce CRM...
[Claude] Enrichment complete — 7841 → 8932 chars
[QUALITY] OK — score 0.79 for HAI-FF1234
Approval APP-E2F8 queued for HITL review.
Generation completed. Pending documents are waiting for HITL approval.
```

---

## Riepilogo Tecnico

| Step | File principale | LLM | DB |
|---|---|---|---|
| 1 — Trigger | `routers/agent.py` | ✗ | ✗ |
| 2 — Profile Resolution | `services/llm_service.py` | ✗ | MongoDB (read) |
| 3 — Hybrid Retrieval | `services/retriever.py` | ✓ (query expansion) | ChromaDB |
| 4 — Context Assembly | `services/rag_service.py` | ✗ | ✗ |
| 5 — FactPack Extraction | `services/fact_pack_service.py` | ✓ Claude / Ollama | ✗ |
| 6 — FactPack Validation | `services/fact_pack_service.py` | ✗ | ✗ |
| 7a — Document Rendering | `services/fact_pack_service.py` | ✓ Ollama / Gemini | ✗ |
| 7b — Single-Pass Generation | `services/agent_service.py` | ✓ Ollama / Gemini | ✗ |
| 8 — Sanitization | `output_guard.py` | ✗ | ✗ |
| 9 — Claude Enrichment | `services/agent_service.py` | ✓ Claude (opt.) | ✗ |
| 10 — Quality Assessment | `output_guard.py` | ✗ | ✗ |
| 11 — Report Building | `services/agent_service.py` | ✗ | ✗ |
| 12 — HITL Queue | `routers/approvals.py` | ✗ | MongoDB (write) |
