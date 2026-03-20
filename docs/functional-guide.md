# Functional Integration Mate — Functional Guide

> **Purpose:** Explain how the system works, why each technology was chosen, and how tools are used in practice.
> **Audience:** Developers joining the project, architects evaluating the PoC, stakeholders reviewing the AI governance model.

---

## Table of Contents

1. [What Is This Project?](#1-what-is-this-project)
2. [The Problem It Solves](#2-the-problem-it-solves)
3. [How It Works — End to End](#3-how-it-works--end-to-end)
4. [The Agentic RAG Pattern Explained](#4-the-agentic-rag-pattern-explained)
5. [Human-in-the-Loop (HITL) — Why and How](#5-human-in-the-loop-hitl--why-and-how)
6. [Tool Choices — Why Each Technology Was Selected](#6-tool-choices--why-each-technology-was-selected)
7. [How Each Tool Is Used in Practice](#7-how-each-tool-is-used-in-practice)
8. [The Document Template System](#8-the-document-template-system)
9. [The RAG Learning Loop](#9-the-rag-learning-loop)
10. [Security Model — Why and How](#10-security-model--why-and-how)
11. [Running the System](#11-running-the-system)
12. [Admin Tools](#12-admin-tools)

---

## 1. What Is This Project?

**Functional Integration Mate** is a Proof of Concept (PoC) for AI-assisted enterprise integration documentation. It demonstrates how a locally-hosted LLM, combined with a RAG (Retrieval Augmented Generation) pipeline and mandatory human oversight, can accelerate the creation of Functional Design documents for system integrations (e.g., PLM → PIM, PLM → DAM).

**What it is NOT:**
- It is not an integration middleware (no message routing, no runtime execution).
- It is not a fully automated documentation tool (HITL approval is mandatory by design).
- It is not a cloud-dependent system (all inference runs locally via Ollama).

---

## 2. The Problem It Solves

In enterprise integration projects, writing Functional and Technical Specifications is:

- **Time-consuming:** A single Functional Design document can take 1–3 days to author.
- **Repetitive:** Many integrations follow known patterns (e.g., all PLM→PIM integrations share a similar structure).
- **Expert-dependent:** Writing quality specs requires deep knowledge of both the business domain and integration patterns.
- **Inconsistent:** Different architects produce documents with different structures and depths.

**Integration Mate addresses this by:**

1. Ingesting raw requirements from a CSV (the analyst's starting point).
2. Automatically retrieving past, human-approved integration patterns from a vector database.
3. Using a locally-hosted LLM to draft a structured Functional Design document.
4. Enforcing a human review gate before the document is persisted — preserving quality and governance.
5. Learning from each approved document, so future generations improve over time.

---

## 3. How It Works — End to End

### Step 1 — Upload Requirements

The analyst uploads a CSV file via the Web Dashboard. The file contains rows like:

```csv
req_id,source_system,target_system,category,description
REQ-001,PLM,PIM,Product Master,Sync product master data including SKU and EAN codes daily
REQ-002,PLM,PIM,Pricing,Transfer net price lists to PIM upon approval in PLM
```

The Integration Agent:
- Validates the file (MIME type, max 1 MB, UTF-8 encoding).
- Parses each row into a `Requirement` object.
- Returns a preview `[{source, target}, …]` **without yet creating CatalogEntries** (ADR-025).

**Step 1a — Project Modal (mandatory)**

After the CSV is parsed, the dashboard automatically opens the **Project Modal**. The analyst fills in:

| Field | Type | Notes |
|-------|------|-------|
| Nome Cliente | Required | e.g. "Acme Corp" |
| Dominio | Required | e.g. "Fashion Retail" (free text) |
| Prefisso | Required, max 3 chars | Auto-generated from client initials; must be unique per client |
| Descrizione | Optional | Free text, max 500 chars |
| Riferimento Accenture | Optional | Free text, max 100 chars |

The prefix is auto-generated as the analyst types the client name (e.g., "Acme Corp" → `AC`, "Global Fashion Group" → `GFG`, "Salsify" → `SAL`). A debounced uniqueness check (`GET /api/v1/projects/{prefix}`) fires 400 ms after the last keystroke:

- **Green banner**: "Acme Corp esiste già. I documenti saranno aggiunti al progetto AC." → reuse existing project.
- **Red banner + Confirm disabled**: Prefix is taken by a different client → analyst must change the prefix.

On confirm:
1. If the project is new: `POST /api/v1/projects` creates it.
2. `POST /api/v1/requirements/finalize` creates CatalogEntries with IDs in the format `{PREFIX}-{6hex}` (e.g., `ACM-4F2A1B`).

The catalog entry ID prefix makes every integration immediately identifiable by client.

**Step 1b — Enrich the Knowledge Base (optional but recommended)**

Before triggering the agent, architects can populate the **Knowledge Base** via the dedicated section in the sidebar. Two input types are supported:

1. **File Upload** — Upload existing integration design documents (PDF, DOCX, XLSX, PPTX, or Markdown). Files are chunked, embedded, and stored in the ChromaDB `knowledge_base` collection. The auto-tagger suggests up to 3 tags via LLM.

2. **URL Link** — Register any HTTP/HTTPS URL (e.g., a Salsify API reference, an Akeneo integration guide). The URL is stored as a KB entry with user-assigned tags. At generation time, the agent fetches the URL content live and injects it alongside file-based KB context.

When the agent generates a new integration document, it queries the knowledge base alongside the approved-examples RAG store — injecting the most relevant best-practice content into the prompt as a `BEST PRACTICES REFERENCE` section.

**Tag matching controls injection**: only KB entries (file or URL) whose tags overlap with the integration's confirmed tags are retrieved. This ensures that a Salsify URL is only injected when generating a Salsify integration, not for unrelated integrations.

This step is optional: if the Knowledge Base is empty, the agent relies solely on past approved documents from the `approved_integrations` ChromaDB collection.

### Step 2 — Trigger the Agent

The analyst clicks **"Start Agent Processing"** on the Agent Workspace page. This calls `POST /api/v1/agent/trigger`, which:
- Checks that requirements have been uploaded.
- Acquires an `asyncio.Lock` to prevent concurrent runs.
- Starts `run_agentic_rag_flow()` as a background async task.

The dashboard begins polling `/api/v1/agent/logs` every 2 seconds to display real-time progress in the terminal panel.

### Step 3 — The Agentic RAG Flow

For each `(source, target)` pair, the agent executes:

```
1. Create CatalogEntry → MongoDB
2. Query ChromaDB "approved_integrations" for similar past approved examples (RAG retrieval)
   → tag-filtered first, similarity fallback
3. Query ChromaDB "knowledge_base" for relevant best-practice file chunks (KB retrieval)
   → tag-filtered first, similarity fallback
4. Fetch live content from tag-matched KB URL entries (URL KB retrieval)
   → HTTP GET per URL; timeout 10s; failed URLs inject "[URL unavailable: ...]"
5. Build the LLM prompt:
      meta-prompt instructions
    + functional design template (injected as structure)
    + past approved examples (if found)       → "PAST APPROVED EXAMPLES"
    + KB file chunks + URL content (if found) → "BEST PRACTICES REFERENCE"
    + current requirements
6. Call Ollama → generate Markdown document
7. Validate output (structural guard + XSS sanitization)
8. Store document as PENDING in MongoDB → awaits human review
```

### Step 4 — Human Review (HITL)

The analyst navigates to **"HITL Approvals (RAG)"** and sees the generated document in a side-by-side editor. They can:
- Read and edit the document directly in the Markdown textarea.
- Click **"Approve & Save to RAG"** → document is persisted to MongoDB and fed into ChromaDB.
- Click **"Reject (Retry)"** → provide feedback; the document is marked REJECTED (future: agent retry with feedback).

### Step 5 — Catalog & Document Access

After approval, the document is accessible via:
- `GET /api/v1/catalog/integrations` → lists all integration entries. Supports filter params `?project_id=`, `?domain=`, `?accenture_ref=` for case-insensitive partial matching.
- `GET /api/v1/catalog/integrations/{id}/functional-spec` → returns the approved Markdown.
- The **"Integration Catalog"** page in the dashboard shows a filter bar above the grid (client dropdown, domain/Accenture text inputs with debounce). Each catalog card shows a prefix badge (e.g., `[ACM]`), the client name, domain, and optionally the Accenture reference.
- The **"Generated Docs"** page renders the approved Markdown as formatted HTML via `marked.js`.

---

## 4. The Agentic RAG Pattern Explained

### What is RAG?

**Retrieval Augmented Generation** is a technique where, before asking the LLM to generate content, you first retrieve relevant reference material from a knowledge base and include it in the prompt. This allows the LLM to produce output that is grounded in specific, curated examples rather than relying solely on its training data.

### Why "Agentic" RAG?

In standard RAG, retrieval and generation are a fixed two-step pipeline. In *Agentic* RAG, the agent evaluates whether retrieved results are relevant before deciding to use them. In this PoC, the evaluation is simple (non-empty results → use them), but the architecture is designed to accommodate more sophisticated re-ranking and grading in the future.

### The Concrete Flow in This System

```
New Requirements (PLM → PIM, 3 reqs)
        │
        ▼
ChromaDB Query: "find similar past PLM→PIM integrations"
        │
        ├─ Results found → inject as PAST APPROVED EXAMPLES in prompt
        │                   (few-shot learning: LLM mimics approved style)
        │
        └─ No results   → zero-shot generation
                           (LLM uses only the template + requirements)
        │
        ▼
LLM generates document structured on template
        │
        ▼
Human approves → document upserted to ChromaDB
                 (next time, this becomes a retrieved example)
```

**The key insight:** Each approval makes the next generation better. Over time, the vector store accumulates domain-specific approved examples, and the LLM output increasingly reflects the organisation's preferred style and depth.

---

## 5. Human-in-the-Loop (HITL) — Why and How

### Why HITL Is Mandatory

The HITL gate is not optional — it is a **governance control** aligned with Accenture's Responsible AI principles:

1. **LLMs hallucinate.** An LLM can generate plausible-sounding but factually wrong integration rules (e.g., wrong field names, incorrect transformation logic). A human expert must validate before the document becomes a reference artifact.
2. **Only approved documents enter the RAG store.** If AI-generated errors were automatically persisted, they would be retrieved as "examples" in future generations, compounding quality degradation.
3. **Human accountability.** Enterprise integration specs have real downstream consequences (dev work, testing, legal compliance). A named human approver creates clear accountability.
4. **Transparency.** The Accenture AI Standard requires that AI-assisted outputs be clearly identifiable and subject to human review.

### How HITL Works Technically

```
LLM generates document
        │
        ▼
Stored as Approval { status: "PENDING" }
        │                    in MongoDB + in-memory cache
        ▼
Dashboard polls /api/v1/approvals/pending every N seconds
        │
        ▼
Analyst opens editor → reads + edits document
        │
        ├─ POST /api/v1/approvals/{id}/approve { final_markdown }
        │       → sanitize_human_content() (bleach, no structural guard)
        │       → Approval status = "APPROVED"
        │       → Document persisted to MongoDB
        │       → Document upserted to ChromaDB (RAG learning)
        │
        └─ POST /api/v1/approvals/{id}/reject { feedback }
                → Approval status = "REJECTED"
                → Feedback stored (available for retry context)
```

**Security note:** Even the analyst's edited Markdown goes through `sanitize_human_content()` (bleach HTML sanitization) before persistence — protecting the system from XSS stored via clipboard paste.

---

## 6. Tool Choices — Why Each Technology Was Selected

### FastAPI (Python)

**Why:** FastAPI is async-first by design, using Python's `asyncio` and `await` natively. Since the most expensive operation in this system (LLM call via Ollama) is a long-running I/O task, async is not a nice-to-have — it is essential to avoid blocking the entire server during generation.

Additional reasons:
- **Pydantic integration:** Request/response validation is built in. Malformed inputs are rejected automatically with clear error messages.
- **OpenAPI auto-generation:** Every endpoint is self-documented via Swagger UI.
- **Thin:** No ORM, no framework overhead — the codebase stays small and auditable.

### Ollama (Local LLM)

**Why:** The primary driver is **data privacy and compliance**. Integration requirements often contain confidential product data, pricing logic, and system architecture details. Sending this data to a cloud LLM API (OpenAI, Claude, Gemini) would create data residency and confidentiality risks incompatible with Accenture project standards.

Ollama provides:
- **Local inference:** Model runs on the same host, data never leaves the network.
- **Model flexibility:** `OLLAMA_MODEL` env var allows switching between `llama3.2:1b` (fastest), `llama3.2:3b` (balanced), or `llama3.1:8b` (best quality) without code changes.
- **Docker-friendly:** Official `ollama/ollama` image with model storage in a named volume.

### ChromaDB (Vector Database)

**Why:** RAG requires a vector database to perform semantic similarity search on past documents. ChromaDB was chosen because:
- **Local-first:** Like Ollama, it runs fully on-premise (Docker container with persistent volume).
- **No cloud dependency:** No API keys, no rate limits, no egress costs.
- **Simple Python client:** `chromadb.AsyncHttpClient` integrates naturally into the async FastAPI flow.
- **Persistent storage:** Data survives container restarts via the `chroma-data` Docker volume.
- **Appropriate for PoC scale:** For production, this could be swapped for Weaviate, Pinecone, or pgvector without changing the business logic.

### MongoDB + Motor (Document Store)

**Why MongoDB:**
- Integration specs are structured but evolving — a document store with flexible schema is more natural than a relational DB for this use case.
- The `CatalogEntry`, `Approval`, and `Document` models need no joins — each is a self-contained document.
- MongoDB 7 with the official Docker image is zero-configuration for PoC deployment.

**Why Motor (async driver):**
- Motor is the official async MongoDB driver for Python. Using a synchronous driver (e.g., PyMongo directly) inside a FastAPI async route would block the event loop during database I/O — negating the benefit of async.
- The write-through cache pattern (`in-memory dict → MongoDB upsert`) ensures sub-millisecond reads (from memory) while maintaining persistence.

### bleach (HTML Sanitization)

**Why:** LLM output can contain arbitrary text including HTML tags. If this content is stored and later rendered in a browser, unsanitized tags like `<script>` or `<iframe>` would execute as JavaScript — a stored XSS vulnerability (OWASP A03).

bleach is used in two modes:
- **Strict mode (`sanitize_llm_output`):** Structural check + allowlist of safe markdown-rendering tags (headings, lists, tables, code, etc.).
- **Lenient mode (`sanitize_human_content`):** No structural guard (reviewer may restructure headings) but still strips dangerous tags.

### Pydantic Settings (Configuration Management)

**Why:** In a Docker Compose environment, configuration comes from environment variables. Pydantic Settings:
- Reads env vars and `.env` files automatically.
- Validates types and required fields at startup — if `OLLAMA_HOST` is missing, the app crashes immediately with a clear error rather than failing silently at runtime.
- Prevents hardcoded secrets (OWASP A02).

### Vanilla JS SPA (No Framework)

**Why no React, Vue, Angular:**
- **Auditability:** A PoC that runs security reviews benefits from zero framework complexity. Reviewers can read every line without knowing framework internals.
- **Zero build step:** HTML + JS files are served directly by Nginx. No `npm build`, no webpack, no bundle optimization.

**Gateway routing:** All browser API calls are routed through the nginx gateway container (`mate-gateway`) on port 8080. Path prefixes map to internal services: `/agent/*` → integration-agent, `/plm/*` → PLM mock, `/pim/*` → PIM mock. This eliminates the need to open ports 4001, 4002, or 4003 on firewalls or security groups.

- **Minimal attack surface:** No npm dependency tree = no supply chain risk.
- **Simplicity:** The dashboard is a relatively simple CRUD UI — a framework would add complexity without value.

### MinIO (Object Storage)

**Why:** The mock systems (PLM, PIM, DAM) need to serve files (product data, assets) via an S3-compatible API. MinIO provides a local S3 replacement without requiring AWS credentials. In production, the same code would work against a real S3 bucket by changing the endpoint URL.

---

## 7. How Each Tool Is Used in Practice

### Ollama — LLM Inference

LLM calls live in `services/llm_service.py` (extracted from `main.py` during Phase 1). The core function is `generate_with_ollama`, wrapped by `generate_with_retry` (R13):

```python
# services/integration-agent/services/llm_service.py

async def generate_with_ollama(prompt: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.ollama_host}/api/generate",
            json={
                "model": settings.ollama_model,   # llama3.2:3b or llama3.1:8b
                "prompt": prompt,
                "stream": False,                   # wait for full response
            },
            timeout=settings.ollama_timeout_seconds,  # 600s default
        )
        data = resp.json()
        return data["response"]

async def generate_with_retry(prompt: str) -> str:
    """R13 — 3 attempts, 5s then 15s backoff before raising."""
    for attempt in range(3):
        try:
            return await generate_with_ollama(prompt)
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(5 if attempt == 0 else 15)
```

The call is fully async. If Ollama returns a 404, the model is not pulled — run `docker exec mate-ollama ollama pull llama3.2:3b`. If it returns a timeout, increase `OLLAMA_TIMEOUT_SECONDS` (large models on CPU can take 5–7 minutes). Transient Ollama hiccups (network blip, model loading) are handled automatically by the retry wrapper without surfacing an error to the analyst.

### ChromaDB — RAG Retrieval and Storage

Phase 2 replaced the original single-query `collection.query(n_results=2)` call with a multi-stage hybrid pipeline implemented in `services/retriever.py` and `services/rag_service.py`.

**Retrieval pipeline (per agent run):**

```
1. Multi-query expansion (R8)
      Original query → 4 variants:
        - 2 deterministic templates ("technical: ...", "business: ...")
        - 2 LLM-generated rephrasings (technical + business focus)
      LLM variants degrade gracefully if Ollama is unavailable.

2. BM25 + Dense hybrid retrieval (ADR-027)
      Each variant queries both:
        - ChromaDB dense embeddings (cosine similarity)
        - In-memory BM25Plus index (rank_bm25)
      Results from both are merged with 0.6 / 0.4 (dense/BM25) weights.
      BM25 index is rebuilt at startup and on every KB upload or delete.

3. Relevance threshold filter (R9)
      Scores below the threshold are dropped:
        score = 1 / (1 + distance)   # converts ChromaDB distance to similarity
        config key: rag_distance_threshold = 0.8

4. TF-IDF re-rank (R9)
      Surviving chunks are re-ranked by TF-IDF cosine similarity
      (scikit-learn TfidfVectorizer) against the original query.
      Top rag_top_k_chunks (default: 5) are kept.

5. ContextAssembler (R10)
      Fuses the ranked chunks from both collections into structured
      prompt sections with a token budget:
        ## PAST APPROVED EXAMPLES    ← from approved_integrations
        ## BEST PRACTICE PATTERNS    ← from knowledge_base
```

Storage after HITL approval is unchanged:

```python
# After approval, the document is upserted into ChromaDB
collection.upsert(
    documents=[approved_markdown],
    metadatas=[{"integration_id": entry_id, "type": "functional"}],
    ids=[f"{entry_id}-functional"]
)
```

ChromaDB uses its default embedding model to vectorise the text. The BM25 index complements dense search particularly well for short, keyword-rich requirement descriptions.

### MongoDB — Persistence with Write-Through Cache

```python
# db.py — Motor async client initialised at startup
catalog_col    = db["catalog_entries"]
approvals_col  = db["approvals"]
documents_col  = db["documents"]

# main.py — write-through pattern
catalog[entry_id] = entry                                     # 1. update in-memory
await db.catalog_col.replace_one(                            # 2. persist to MongoDB
    {"id": entry_id},
    entry.model_dump(),
    upsert=True
)

# Startup seeding — restores state after container restart
async for doc in db.catalog_col.find():
    catalog[doc["id"]] = CatalogEntry(**doc)
```

### bleach — Output Sanitization

```python
# output_guard.py
_ALLOWED_TAGS = ["h1", "h2", ..., "table", "tr", "td", "code", "a", ...]

def sanitize_llm_output(raw: str) -> str:
    # 1. Structural guard
    if not raw or not isinstance(raw, str):
        raise LLMOutputValidationError("empty output")
    if not raw.startswith(_REQUIRED_PREFIX):
        idx = raw.find(_REQUIRED_PREFIX)
        if idx == -1:
            raise LLMOutputValidationError("heading absent")
        raw = raw[idx:]           # strip preamble (small models add intros)

    # 2. HTML sanitization
    cleaned = bleach.clean(raw, tags=_ALLOWED_TAGS, strip=True)

    # 3. Truncation
    return cleaned[:_MAX_CHARS]
```

### Prompt Builder — Template Injection

```python
# prompt_builder.py
_TEMPLATE           = _load_template()             # reusable-meta-prompt.md
_FUNCTIONAL_TEMPLATE = _load_functional_template() # template/functional/...

def build_prompt(source, target, requirements, rag_context="") -> str:
    rag_block = f"PAST APPROVED EXAMPLES:\n{rag_context}" if rag_context.strip() else ""

    # Sequential str.replace() — not str.format() (prevents KeyError if
    # user-supplied system names contain brace patterns like '{PLM}')
    result = _TEMPLATE
    result = result.replace("{source_system}",          source)
    result = result.replace("{target_system}",          target)
    result = result.replace("{formatted_requirements}", requirements)
    result = result.replace("{rag_context}",            rag_block)
    result = result.replace("{document_template}",      _FUNCTIONAL_TEMPLATE)
    return result
```

### 7.x ChromaDB — Two Collections

The system uses two distinct ChromaDB collections:

| Collection | Purpose | Populated by |
|---|---|---|
| `approved_integrations` | Past HITL-approved integration documents used as RAG examples | Approval workflow |
| `knowledge_base` | Uploaded best-practice documents (chunked and embedded) | KB upload endpoint |

Both collections are queried during document generation and their results are injected into the LLM prompt. The `approved_integrations` results are weighted as "PAST APPROVED EXAMPLES" while the `knowledge_base` results provide broader context.

### 7.x MongoDB — `llm_settings` Collection

A single MongoDB document (`_id: "current"`) persists any admin-configured LLM parameter overrides. At startup, the integration agent loads this document into an in-memory `_llm_overrides` dict that is consulted before the pydantic-settings defaults.

When a full system reset is triggered, this document is deleted and `_llm_overrides` is cleared — restoring all LLM parameters to their design-time defaults.

### 7.5 Backend Architecture (Phase 1 — R15, ADR-026)

The original `main.py` (2065-line monolith) was decomposed into a 3-layer architecture to improve testability, maintainability, and domain isolation.

**Layer 1 — Routers (`routers/`)**

Eight `APIRouter` modules, one per domain. Each router owns only its HTTP surface — no cross-imports between routers.

| Module | Responsibility |
|--------|---------------|
| `agent.py` | `/agent/trigger`, `/agent/logs`, `/agent/status` |
| `requirements.py` | CSV upload, parse, finalize |
| `projects.py` | Project CRUD, prefix uniqueness check |
| `catalog.py` | Catalog listing and spec retrieval |
| `approvals.py` | HITL approve / reject |
| `documents.py` | Generated docs access |
| `kb.py` | Knowledge base upload, URL registration, delete |
| `admin.py` | Reset, LLM settings, project-docs browser |

**Layer 2 — Services (`services/`)**

Three independently unit-testable modules with no FastAPI dependency:

| Module | Responsibility |
|--------|---------------|
| `llm_service.py` | `generate_with_ollama` + `generate_with_retry` (R13) |
| `rag_service.py` | ChromaDB queries, `ContextAssembler`, KB retrieval |
| `tag_service.py` | LLM-based tag extraction and suggestion |

**Layer 3 — Shared State (`state.py`)**

Centralised in-memory globals (`catalog`, `approvals`, `parsed_requirements`, `_agent_lock`, `_llm_overrides`, etc.). All routers and services import from `state` directly — no singleton pattern, no dependency injection container. Simple and explicit for a PoC.

Cross-cutting utilities (`auth.py`, `utils.py`, `log_helpers.py`) are imported where needed without layer restrictions.

---

## 8. The Document Template System

### Architecture

The system uses two layers of external files to control document structure:

```
reusable-meta-prompt.md          ← instructions for the LLM (HOW to write)
        │
        │  contains slot: {document_template}
        │
        ▼
template/functional/             ← the document structure (WHAT to write)
    integration-functional-design.md
```

Both files live at the project root and are mounted as read-only volumes into the Integration Agent container:

```yaml
volumes:
  - ./reusable-meta-prompt.md:/reusable-meta-prompt.md:ro
  - ./template:/template:ro
```

### Why External Files Instead of Hardcoded Strings?

**ADR-014 decision:** Externalising the prompt decouples prompt evolution from code changes. Key benefits:

1. **Version control:** The prompt and template are tracked in git. Changes are visible in `git diff` and peer-reviewed like code.
2. **Editability without redeployment:** Business stakeholders or domain experts can refine the template without touching Python code.
3. **Separation of concerns:** The prompt describes agent behaviour; the template describes document structure. They evolve at different rates.
4. **Testability:** `test_prompt_builder.py` verifies that specific template sections appear in the built prompt, catching regressions if a file is moved or corrupted.

### The Functional Design Template Sections

The template (`template/functional/integration-functional-design.md`) defines 10 sections:

| Section | What the LLM Must Generate |
|---------|--------------------------|
| `## 1. Overview` | Purpose, business value, intended audience |
| `## 2. Scope & Context` | In/out of scope, assumptions, constraints |
| `## 3. Actors & Systems` | Source, target, middleware roles |
| `## 4. Business Process Across Systems` | End-to-end flow, triggers, happy path, exceptions |
| `## 5. Functional Scenarios` | ID-tagged scenario table |
| `## 6. Data Objects` | Business entities, CRUD responsibility |
| `## 7. Integration Rules` | Business rules, idempotency |
| `## 8. Error Scenarios` | Error types and expected handling |
| `## 9. Non-Functional Considerations` | Volumes, SLA, data classification |
| `## 10. Dependencies, Risks & Open Points` | External deps, risk table, open items |

The LLM is instructed to populate every section, writing `n/a` only if information is genuinely unavailable.

---

## 9. The RAG Learning Loop

```
First run (no past examples):
  Requirements → zero-shot prompt → LLM generates basic document
  Analyst improves + approves → document enters ChromaDB

Second run (1 approved example):
  Requirements → RAG retrieves example → LLM mimics style → better document
  Analyst approves with minimal edits

Nth run (N approved examples):
  Requirements → RAG retrieves 2 best matches → LLM generates
  document closely matching the organisation's house style
  Analyst approves quickly (minimal edits needed)
```

**The learning loop compounds quality.** Over time:
- The vector store builds a domain-specific library of approved integration patterns.
- The LLM output increasingly reflects the team's preferred terminology, level of detail, and formatting conventions.
- Human review time decreases as output quality improves.

**Why ChromaDB upsert (not insert)?**
If the same integration is re-generated (e.g., after a reject + re-run), the upsert ensures only the latest approved version exists in the vector store, preventing duplicates that would degrade retrieval quality.

### 9.1 RAG Quality Pipeline (Phase 2 — R8–R12, ADR-027..030)

Phase 2 replaced the single-query retrieval call with a multi-stage pipeline that improves recall and precision at every step.

**Multi-query expansion (R8)**
Instead of one query string, `services/retriever.py` generates 4 variants: two deterministic rephrases (technical focus, business focus) plus two LLM-generated rephrasings. Running all variants against ChromaDB and BM25 widens recall — surface-form variations of the same concept are more likely to match relevant chunks.

**BM25 + dense hybrid retrieval (ADR-027)**
A `BM25Plus` index (`rank_bm25`) runs in memory alongside ChromaDB's dense embeddings. Results from both are merged with a 0.6 / 0.4 (dense/BM25) ensemble weight. BM25 is particularly effective for short, keyword-rich requirement descriptions where exact-term matches matter more than semantic proximity.

**Relevance threshold + TF-IDF re-rank (R9)**
Chunks below the distance threshold (`rag_distance_threshold = 0.8`, using `score = 1 / (1 + distance)`) are discarded before ranking. The survivors are re-ranked by TF-IDF cosine similarity (scikit-learn) against the original query, and only the top `rag_top_k_chunks` (default 5) are passed forward. This combination raises precision without sacrificing recall.

**ContextAssembler (R10)**
`services/rag_service.py` fuses the ranked chunks from both ChromaDB collections into a structured prompt contribution with a token budget. The output is two labelled sections injected into the LLM prompt: `## PAST APPROVED EXAMPLES` (from `approved_integrations`) and `## BEST PRACTICE PATTERNS` (from `knowledge_base`). Token budgeting prevents prompt truncation on large knowledge bases.

**Semantic chunking for uploads (R11)**
When a new document is uploaded to the KB, `document_parser.py::semantic_chunk()` uses LangChain's `RecursiveCharacterTextSplitter` with separator priority `["\n## ", "\n### ", "\n\n", "\n", ". ", " "]`. This keeps semantically coherent blocks (sections, paragraphs) together rather than splitting at fixed byte offsets, producing higher-quality embeddings.

**Multi-dimensional tag filter (R12)**
ChromaDB metadata filters now use `$or` across all confirmed tags for the integration (not just the first tag). A document tagged `[salsify, pim, product-master]` will be retrieved for any of those three tags — significantly improving recall for multi-tag integrations.

New configuration keys added in `config.py`:

| Key | Default | Purpose |
|-----|---------|---------|
| `rag_distance_threshold` | `0.8` | Minimum similarity score to keep a chunk |
| `rag_bm25_weight` | `0.4` | BM25 share in dense/BM25 ensemble |
| `rag_n_results_per_query` | `3` | ChromaDB results per query variant |
| `rag_top_k_chunks` | `5` | Final chunks passed to ContextAssembler |

New dependencies: `langchain-text-splitters==0.3.8`, `rank-bm25==0.2.2`, `scikit-learn==1.6.1`.

---

## 10. Security Model — Why and How

### Why Security Is First-Class in a PoC

Even in a PoC, security controls serve two purposes:
1. **Prevent real harm:** The system stores and renders markdown that could contain executable content if unsanitized.
2. **Establish the right patterns:** PoC code often gets promoted to production faster than expected. Security-by-default from day one prevents retrofitting.

### Key Controls and Their Rationale

**HMAC constant-time comparison (OWASP A07 — Identification and Authentication Failures)**
```python
# main.py
if not hmac.compare_digest(token.encode(), settings.api_key.encode()):
    raise HTTPException(401)
```
Standard string equality (`==`) is vulnerable to timing attacks — an attacker can measure response time differences to guess the key character by character. `hmac.compare_digest()` always takes the same time regardless of where the strings differ.

**`str.replace()` instead of `str.format()` (OWASP A03 — Injection)**
```python
# If source_system = "{target_system}", then:
# str.format() would raise KeyError or substitute wrongly
# str.replace() treats the replacement literally → safe
result = result.replace("{source_system}", source_system)
```

**Structural output guard (OWASP A03 — LLM Output Injection)**
The requirement that LLM output must start with `# Integration Functional Design` is an application-level contract. It forces the model to commit to the expected document structure, making it harder for a prompt injection attack embedded in a requirement description to redirect the LLM's output into an unexpected format.

**bleach allowlist (OWASP A03 — Stored XSS)**
Markdown rendered in a browser can include HTML. `bleach.clean(strip=True)` removes all HTML tags not in the allowlist. Note: `strip=True` removes the tag wrappers but preserves the text content — `<script>alert('xss')</script>` becomes `alert('xss')` (inert without the `<script>` tag that would trigger browser execution).

**CORS env-var allowlist (OWASP A05 — Security Misconfiguration)**
```python
# config.py
cors_origins: str = "http://localhost:8080,http://localhost:3000"
# Note: with the nginx gateway, browser calls are same-origin (:8080) — CORS headers
# are not required for browser→gateway→backend communication.
# → parsed to list in main.py
# Never: allow_origins=["*"] with allow_credentials=True
```
`*` with credentials is a CORS misconfiguration that allows any origin to make credentialed requests — effectively bypassing same-origin protection.

---

## 11. Running the System

### Prerequisites

1. Docker Desktop (or Docker Engine + Compose plugin)
2. 8+ GB RAM (Ollama needs memory for the model)
3. Pull the LLM model (required once):

```bash
# Start services first
docker compose up -d ollama

# Pull the model (≈2 GB download for llama3.2:3b)
docker exec mate-ollama ollama pull llama3.2:3b

# Or use the larger model (~5 GB, best quality)
docker exec mate-ollama ollama pull llama3.1:8b
```

### Start the Full Stack

```bash
docker compose up -d
```

### Access Points

| Service | URL | Notes |
|---------|-----|-------|
| Web Dashboard | http://localhost:8080 | Via nginx gateway |
| Integration Agent Swagger | http://localhost:8080/agent/docs | Via gateway (also direct: :4003/docs on same network) |
| PLM Mock Swagger | http://localhost:8080/plm/docs | Via gateway (also direct: :4001/docs on same network) |
| PIM Mock Swagger | http://localhost:8080/pim/docs | Via gateway (also direct: :4002/docs on same network) |
| DAM Mock Swagger | http://localhost:4005/docs |  |
| MinIO Console | http://localhost:9001 (admin/minioadmin) |  |
| ChromaDB API | http://localhost:8000/api/v1/heartbeat |  |

### First Run Walkthrough

1. Open **http://localhost:8080** (all API calls are routed through the nginx gateway — no other ports need to be open)
2. Navigate to **Agent Workspace** → upload `sample-requirements.csv`
3. The **Project Modal** opens automatically — fill in Nome Cliente, Dominio, and confirm the auto-generated Prefisso → click **Conferma →** (this creates the project and the catalog entries with `{PREFIX}-{hex}` IDs)
4. Click **Start Agent Processing** to trigger the agentic RAG flow
5. Watch the terminal logs in real time
6. When generation completes, navigate to **HITL Approvals (RAG)**
7. Select the pending document → review + optionally edit → **Approve & Save to RAG**
8. Navigate to **Integration Catalog** to browse with client/domain filters, and **Generated Docs** to view full specs

### Switching the LLM Model

Set `OLLAMA_MODEL` in your `.env` file at the project root:

```bash
# .env
OLLAMA_MODEL=llama3.1:8b        # best quality, slower (5-7 min on CPU)
OLLAMA_TIMEOUT_SECONDS=600      # ensure timeout matches model size
```

Then restart the agent:
```bash
docker compose up -d integration-agent
```

### Running Tests

```bash
cd services/integration-agent
python -m pytest tests/ -v
```

All 247 tests must pass before any commit (per CLAUDE.md Definition of Done).

---

## 12. Admin Tools

The dashboard includes three admin-only tools accessible from the **Admin** section of the sidebar:

### Reset Tools
Performs a full system reset:
- Clears parsed requirements from memory
- Deletes all MongoDB collections (catalog, approvals, documents, KB documents, LLM settings)
- Recreates ChromaDB collections (approved_integrations, knowledge_base)
- Resets LLM parameter overrides to design defaults
- Blocked while the agent is running (returns 409)

### Project Docs
A read-only markdown browser for significant project documentation. Displays 19 curated documents grouped by category (Guides, ADRs, Checklists, Test Plans, Mappings). Content is served from the mounted `docs/` directory — path traversal and non-.md requests are rejected by the backend.

### LLM Settings
An admin page for tuning LLM parameters at runtime without restarting the container:

| Group | Parameters |
|---|---|
| Document Generation | Model name, max tokens, timeout, temperature, RAG context limit |
| Tag Suggestion | Max tokens, timeout, temperature |

Changes are applied **immediately** to the running agent and persisted in MongoDB. The "Reset to Defaults" button restores pydantic-settings values (as defined in `config.py` or overridden by env vars at startup).

**Why this matters:** On slow CPU hardware (e.g., llama3.1:8b at ~3 tokens/s), reducing `num_predict` from 1000 to 200 cuts generation time from ~5 minutes to ~1 minute for testing purposes — without requiring a container rebuild.
