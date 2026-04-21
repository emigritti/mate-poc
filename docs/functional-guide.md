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
13. [Phase 4 Polish — What Changed for End Users](#13-phase-4-polish--what-changed-for-end-users)
14. [Phase 5 — Multi-Source Ingestion Platform](#14-phase-5--multi-source-ingestion-platform)
15. [Pixel UI Mode (ADR-047)](#15-pixel-ui-mode-adr-047)
16. [Document Quality Improvements (#1–#4)](#16-document-quality-improvements-14)

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

1. Ingesting raw requirements from a CSV or Markdown file (the analyst's starting point).
2. Automatically retrieving past, human-approved integration patterns from a vector database.
3. Using a locally-hosted LLM to draft a structured Functional Design document.
4. Enforcing a human review gate before the document is persisted — preserving quality and governance.
5. Learning from each approved document, so future generations improve over time.

---

## 3. How It Works — End to End

### Step 1 — Upload Requirements

The analyst uploads a **CSV** (multi-integration) or **Markdown** (single integration) file via the Web Dashboard.

**CSV format:**
```csv
ReqID,Source,Target,Category,Description,Mandatory
REQ-001,PLM,PIM,Product Master,Sync product master data including SKU and EAN codes daily,true
REQ-002,PLM,PIM,Pricing,Transfer net price lists to PIM upon approval in PLM,false
```

**Markdown format** (one file = one integration):
```markdown
---
source: ERP
target: Salsify
---

## Mandatory Requirements
- REQ-M01 | Product Collection | Sync daily articles from ERP to PLM

## Non-Mandatory Requirements
- REQ-O01 | Reporting | Generate weekly sync report
```

The Integration Agent:
- Detects file type by extension (`.md` → Markdown parser; otherwise → CSV parser).
- Validates the file (max 1 MB, UTF-8 encoding).
- Parses each item into a `Requirement` object with a `mandatory: bool` field.
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

3. **Batch File Upload** — Upload up to 10 documents in a single `POST /api/v1/kb/batch-upload` request (multipart form, same supported file types). Results are returned per file with partial success: a failure on one file does not abort the others.

4. **Automated Multi-Source Ingestion** (Ingestion Platform — port 4006) — The dedicated Ingestion Platform service continuously populates the KB from three additional source types:
   - **OpenAPI/Swagger** — fetches specs with ETag caching; normalizes endpoints, schemas, and auth into `CanonicalCapability` chunks; detects breaking changes by comparing operation_id sets.
   - **HTML Documentation** — Playwright-based crawler + BS4 cleaning + Claude Haiku relevance filter + Claude Sonnet schema-constrained extraction + cross-page reconciliation.
   - **MCP Servers** — introspects tools, resources, and prompts via the Python MCP SDK; normalizes each into KB chunks.
   All ingested chunks land in the shared `kb_collection` ChromaDB (same collection used by file uploads) with a `src_*` chunk ID prefix and enriched `source_type` metadata. The RAG retriever needs zero modifications to benefit from this content.

When the agent generates a new integration document, it queries the knowledge base alongside the approved-examples RAG store — injecting the most relevant best-practice content into the prompt as a `BEST PRACTICES REFERENCE` section.

**Tag matching controls injection**: only KB entries (file or URL) whose tags overlap with the integration's confirmed tags are retrieved. This ensures that a Salsify URL is only injected when generating a Salsify integration, not for unrelated integrations. Tag matching uses whole-token comparison (comma-split, case-insensitive) to eliminate substring false positives — `"PL"` no longer incorrectly matches `"PLM,SAP"` (ADR-043).

This step is optional: if the Knowledge Base is empty, the agent relies solely on past approved documents from the `approved_integrations` ChromaDB collection.

### Step 2 — Trigger the Agent

The analyst clicks **"Start Agent Processing"** on the Agent Workspace page. This calls `POST /api/v1/agent/trigger`, which:
- Checks that requirements have been uploaded.
- Acquires an `asyncio.Lock` to prevent concurrent runs.
- Starts `run_agentic_rag_flow()` as a background async task.

The dashboard polls `/api/v1/agent/logs` via TanStack Query (ADR-033) with adaptive interval: every 3 seconds while the agent is running, slowing to 15 seconds when idle.

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
    + integration design template (injected as structure)
    + past approved examples (if found)       → "PAST APPROVED EXAMPLES"
    + KB file chunks + URL content (if found) → "BEST PRACTICES REFERENCE"
    + current requirements
6. Call Ollama → generate Markdown document
7. Validate output (structural guard `# Integration Design` prefix + XSS sanitization)
7a. Assess quality → `QualityReport` (configurable gate — warn or block)
7b. Append traceability appendix (Evidence & Sources section)
8. Store document as PENDING in MongoDB → awaits human review
```

After sanitization, `assess_quality()` evaluates the document against **9 signals** grouped in two layers:

**Volume signals (6):**
- Section count ≥ 10 (`## ` headings)
- n/a ratio < 50% of sections
- Word count ≥ 300
- Mermaid diagram present (`\`\`\`mermaid`)
- Mapping table present (pipe-table separator row)
- Placeholder count (unfilled template tokens)

**Structural validators (3):**
- Mermaid block validation — recognized diagram type, minimum content, no stub nodes, edges/interactions present
- Mapping table validation — complete header + separator + data rows with non-empty source/target columns
- Section-artifact coverage — required artifacts per template section (flowchart in Architecture, sequenceDiagram in Detailed Flow, pipe table in Data Mapping)

The result is a `QualityReport` logged as `[QUALITY] score X.XX` in the agent log stream. The **gate mode** is configurable via the Agent Settings page:
- **warn** (default) — documents proceed to HITL regardless of score; issues logged as warnings
- **block** — documents scoring below `quality_gate_min_score` raise `QualityGateError` and are **not** queued for review; the agent logs the failure and continues with the next integration pair

### Step 4 — Human Review (HITL)

The analyst navigates to **"HITL Approvals (RAG)"** and sees the generated document in a side-by-side editor. They can:
- Read and edit the document directly in the Markdown textarea.
- Click **"Approve & Save to RAG"** → document is persisted to MongoDB and fed into ChromaDB.
- Click **"Reject (Retry)"** → provide feedback; the document is marked REJECTED. Use **"Regenerate with Feedback"** (see §5 below) to create a new generation attempt with the feedback injected into the prompt.

> **Next step after functional approval:** Once the functional spec is approved, a **Genera Technical Design** button appears in the Catalog. See [HOW-TO/07 — Generate Technical Design](../HOW-TO/07-generate-technical-design.md) for the full technical design generation flow.

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

#### Regenerate with Feedback

When a reviewer rejects a document and provides written feedback, the feedback is persisted in `Approval.feedback`. Clicking **Regenerate with Feedback** in the UI calls `POST /api/v1/approvals/{id}/regenerate`, which:

1. Injects the rejection feedback into the prompt as a `## PREVIOUS REJECTION FEEDBACK` block (prepended before RAG examples)
2. Runs the full RAG + LLM pipeline again for the same integration
3. Creates a new `PENDING` approval with the regenerated content

The original rejected approval remains unchanged. The new approval ID is returned so the reviewer can navigate directly to it.

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
1. Multi-query expansion (R8, extended ADR-043)
      Original query → 4 variants:
        - 2 deterministic templates ("technical: ...", "business: ...")
        - 2 LLM-generated rephrasings using intent-selectable perspectives
          (intent="" falls back to "technical systems integration" + "business process")
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

4. TF-IDF re-rank (R9, extended ADR-043)
      Surviving chunks are re-ranked by TF-IDF cosine similarity
      (scikit-learn TfidfVectorizer) against the original query, optionally
      augmented with intent-specific vocabulary keywords (e.g., "retry
      dead-letter fallback" for intent="errors").
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
# prompt_builder.py (ADR-042: centralised prompt construction)

# All prompt builders for the pipeline live here.
# build_prompt_for_mode() is the unified entry point.

def build_prompt(source_system, target_system, formatted_requirements,
                 rag_context="", kb_context="", reviewer_feedback="") -> str:
    """Single-pass full-document prompt (fallback path)."""
    # Sequential str.replace() — not str.format() (prevents KeyError if
    # user-supplied system names contain brace patterns like '{PLM}')
    ...

def build_fact_extraction_prompt(source, target, requirements_text,
                                 rag_context_annotated) -> str:
    """FactPack JSON extraction prompt (ADR-041/042).
    Explicitly labels context sections with evidence weight:
      - PAST APPROVED EXAMPLES → highest (confirmed claims)
      - KNOWLEDGE BASE          → secondary (inferred claims)
      - DOCUMENT SUMMARIES      → overview only
    """
    ...

def build_section_render_prompt(fact_pack_json, source, target,
                                requirements_text, document_template,
                                reviewer_feedback="") -> str:
    """FactPack rendering prompt with per-section guidance (ADR-042).
    Injects _SECTION_INSTRUCTIONS so the LLM knows which FactPack fields
    to prioritise for each of the 16 template sections.
    Forwards reviewer_feedback — previously lost in the FactPack path (bug fix).
    """
    ...

def build_prompt_for_mode(mode: Literal["full_doc","fact_extraction","section_render"],
                          **kwargs) -> str:
    """Unified mode dispatcher — forwards to the appropriate builder."""
    ...
```

### Per-Section Rendering Guidance (`_SECTION_INSTRUCTIONS`)

`prompt_builder.py` contains a module-level dictionary mapping each of the 16
template section titles to focused guidance telling the LLM which FactPack fields
to use for that section:

| Section | FactPack fields prioritised |
|---------|---------------------------|
| Data Mapping & Transformation | `entities`, `validations` — table only, no narrative |
| Error Scenarios (Functional) | `errors`, `validations` — HTTP codes, retry, fallback |
| High-Level Architecture | `systems`, `flows`, `integration_scope` — Mermaid flowchart |
| Detailed Flow | `flows.steps` — Mermaid sequenceDiagram |
| Security | `business_rules`, `assumptions` with auth/security context |
| … (16 entries total) | … |

This guidance is injected as a `SECTION GUIDANCE` block in `build_section_render_prompt()`
and reduces cross-section "blending" (facts intended for one section leaking into
unrelated sections) without requiring 16 separate LLM calls.

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
| `agent_service.py` | `generate_integration_doc()` — shared by agent flow and regenerate endpoint |

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

**Multi-query expansion (R8, extended ADR-043)**
Instead of one query string, `services/retriever.py` generates 4 variants: two deterministic rephrases (technical focus, business focus) plus two LLM-generated rephrasings. Running all variants against ChromaDB and BM25 widens recall — surface-form variations of the same concept are more likely to match relevant chunks. When `intent` is provided, the LLM perspective pair is selected from `_INTENT_PERSPECTIVES` (e.g., `intent="data_mapping"` → "field-level data transformation" + "data domain model"); unknown/empty intent falls back to the default pair.

**BM25 + dense hybrid retrieval (ADR-027)**
A `BM25Plus` index (`rank_bm25`) runs in memory alongside ChromaDB's dense embeddings. Results from both are merged with a 0.6 / 0.4 (dense/BM25) ensemble weight. BM25 is particularly effective for short, keyword-rich requirement descriptions where exact-term matches matter more than semantic proximity.

**Relevance threshold + TF-IDF re-rank (R9, extended ADR-043)**
Chunks below the distance threshold (`rag_distance_threshold = 0.8`, using `score = 1 / (1 + distance)`) are discarded before ranking. The survivors are re-ranked by TF-IDF cosine similarity (scikit-learn) against the query, optionally augmented with `_INTENT_VOCABULARY[intent]` domain keywords (e.g., "retry dead-letter fallback" for `intent="errors"`). Only the top `rag_top_k_chunks` (default 5) are passed forward. This combination raises precision without sacrificing recall.

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

### 9.2 Generation Quality Pipeline (Phase 3 — R16–R18, ADR-031..033)

Phase 3 (Generation Quality) is now complete. It adds output quality assessment, a HITL feedback-loop regenerate endpoint, and a frontend server-state pilot.

**Output quality assessment (R16, ADR-031)**
After LLM output is sanitized, `assess_quality()` evaluates **6 volume signals** (section count ≥ 10, n/a ratio < 50%, word count ≥ 300, mermaid diagram present, mapping table present, placeholder count) plus **3 structural validators** (Mermaid syntax, mapping table completeness, section-artifact coverage) and emits a `QualityReport` logged as `[QUALITY] score X.XX`. The gate mode is admin-configurable: **warn** (default) lets all documents proceed to HITL; **block** rejects documents scoring below `quality_gate_min_score` with a `QualityGateError`.

**Feedback loop regenerate (R17, ADR-032)**
`POST /api/v1/approvals/{id}/regenerate` allows reviewers to inject rejection feedback directly back into the generation pipeline via a `## PREVIOUS REJECTION FEEDBACK` block. The original rejected approval is preserved; a new PENDING approval is created.

**TanStack Query frontend pilot (R18, ADR-033)**
React Query (TanStack Query) is piloted for the approvals page to replace manual polling with declarative server-state management, improving UI consistency and reducing boilerplate.

Test count: **263 tests** (247 baseline + 7 quality + 3 prompt feedback + 6 regenerate). The quality suite was subsequently extended in document-quality improvements #1 and #2 (see §16).

### 9.3 Advanced RAG Pipeline — Docling + LLaVA + RAPTOR-lite (Phase 4 — ADR-034..035)

Phase 4 closes two structural gaps in the Phase 2 RAG pipeline:

**Visual content gap — Docling + LLaVA vision (ADR-034)**
The legacy parser silently discarded charts, architecture diagrams, and data-flow figures. Integration documents use diagrams to convey field mappings and data flows; losing them degraded generated document quality.

`parse_with_docling()` replaces per-format text extractors:
- **Text items** → `DoclingChunk(chunk_type="text")` with `section_header` and `page_num`
- **Table items** → `DoclingChunk(chunk_type="table")`, text is the markdown table export
- **Figure items** → `DoclingChunk(chunk_type="figure")`, text is a LLaVA caption

LLaVA captioning (`vision_service.caption_figure()`) calls `llava:7b` via the local Ollama daemon with base64-encoded image bytes. It is controlled by `vision_captioning_enabled` (default `True`) and returns a placeholder on error. Figure captions are included in the BM25 index so keyword queries (e.g., "field mapping REST endpoint") can match diagram labels. Legacy `parse_document()` and `semantic_chunk()` are preserved unchanged for backward compatibility; Docling falls back to them if the package is not installed.

**Retrieval granularity gap — RAPTOR-lite summaries (ADR-035)**
Chunk-level retrieval loses section-level context. When the same concept spans many chunks, no single chunk explains the overall picture.

After parsing, chunks are grouped by `section_header`. Sections with ≥ 3 chunks are summarised by `summarize_section()` (llama3.1:8b), producing a `SummaryChunk` upserted to the `kb_summaries` ChromaDB collection. At retrieval time, `HybridRetriever.retrieve_summaries()` performs dense-only search (summaries benefit more from semantic similarity than keyword matching) and returns the top-3 summary chunks. These are injected by `ContextAssembler` as a new **first section** in the prompt:

```
## DOCUMENT SUMMARIES (overview context):   ← 500-char budget
## PAST APPROVED EXAMPLES                   ← unchanged
## BEST PRACTICE PATTERNS                   ← unchanged
```

Total context budget raised from 1500 → **3000 chars** (`ollama_rag_max_chars`).

Both features are independently disableable via config flags:

| Flag | Default | Effect when disabled |
|------|---------|---------------------|
| `vision_captioning_enabled` | `True` | Figure chunks get placeholder caption |
| `raptor_summarization_enabled` | `True` | Section summaries silently skipped |

New dependencies: `docling>=2.0`, `numpy<2.0` (pin for chromadb 0.5.x compatibility).

Test count: **338 tests** (263 + 35 Phase 4 + 13 ADR-043 retriever intent/tag tests + 16 ADR-044 semantic enrichment + 11 other ADR tests).

### 9.3.3 KB Semantic Metadata Enrichment and Upload Pipeline Deduplication (ADR-044)

#### Problem addressed

The KB upload pipeline had two independent weaknesses identified in SME review:

1. **Semantically thin metadata** — ChromaDB stored positional fields only (`document_id`, `filename`, `chunk_index`, `chunk_type`, `page_num`, `section_header`, `tags_csv`). The retriever could not distinguish a business-rule chunk from a field-mapping table or an error-handling pattern without reading the full text.

2. **Duplicated upload pipeline** — `kb_upload()` and `kb_batch_upload()` contained ~60 lines of identical logic (parse → auto-tag → ChromaDB upsert → state update). Any future enrichment added to one endpoint had to be manually mirrored to the other.

#### `enrich_chunk_metadata()` — deterministic semantic enrichment

A pure function in `document_parser.py` that takes a `DoclingChunk` and the `source_modality` (file extension) and returns 6 new metadata fields stored in ChromaDB alongside the existing structural fields:

| Field | Type | Description |
|-------|------|-------------|
| `semantic_type` | `str` | One of 8 fixed values classifying the chunk's functional role |
| `entity_names` | `str` (CSV) | PascalCase/CamelCase entity names found in the text (max 10) |
| `field_names` | `str` (CSV) | snake_case field names found in the text (max 15) |
| `rule_markers` | `str` (CSV) | Normative language: "mandatory", "must", "required", … |
| `integration_keywords` | `str` (CSV) | Domain terms: "api", "webhook", "oauth", "retry", … |
| `source_modality` | `str` | File extension: "pdf", "docx", "md", "xlsx", … |

**`semantic_type` classification** is deterministic — no LLM call, zero latency:

| Value | Condition |
|-------|-----------|
| `"data_mapping_candidate"` | `chunk_type == "table"` |
| `"diagram_or_visual"` | `chunk_type == "figure"` |
| `"business_rule"` | ≥ 2 rule markers in text |
| `"error_handling"` | ≥ 2 error keywords in text |
| `"security_requirement"` | ≥ 2 security keywords in text |
| `"architecture"` | ≥ 2 architecture keywords in text |
| `"data_definition"` | ≥ 3 snake_case field names detected |
| `"general_text"` | fallback |

All values are plain strings (ChromaDB metadata constraint: no list types). List-typed fields use comma-separated encoding, consistent with the existing `tags_csv` convention. `enrich_chunk_metadata()` guarantees all returned values are strings — empty extraction produces `""` not `None`.

**Seven constants** added to `document_parser.py` for keyword detection: `_RULE_MARKERS`, `_INTEGRATION_KEYWORDS`, `_ARCHITECTURE_KEYWORDS`, `_ERROR_KEYWORDS`, `_SECURITY_KEYWORDS`, `_FIELD_PATTERN` (snake_case regex), `_ENTITY_PATTERN` (PascalCase/CamelCase regex).

#### `_process_kb_file()` — shared upload pipeline

A new private async function in `routers/kb.py` that consolidates the shared steps:

```
_process_kb_file(content, filename, file_type)
  → (doc_id, docling_chunks, auto_tags, tags_csv)

Steps:
  1. parse_with_docling()
  2. suggest_kb_tags_via_llm()
  3. generate doc_id
  4. ChromaDB upsert — with **enrich_chunk_metadata() spread into every chunk metadata
  5. state.kb_docs / state.kb_chunks update
```

Raises `RuntimeError` on failure; the caller maps it to the appropriate HTTP response:
- `kb_upload()` → `HTTPException(422)`
- `kb_batch_upload()` → append error result, continue

Steps that remain in each endpoint (intentional divergence):
- BM25 index rebuild — called after each file
- MongoDB store
- RAPTOR timing — **background** (`background_tasks.add_task()`) in single upload; **inline** (`await`) in batch upload

#### Security properties

- All extraction is deterministic — no external calls, no user-supplied code execution.
- `source_modality` is derived from the server-side `detect_file_type()` result, never from user-supplied metadata (no injection vector).
- The 6 new fields are stored in ChromaDB metadata only. They do not affect prompt construction and are not currently surfaced in LLM context — no prompt-injection risk.

#### Rollback

Remove the `**enrich_chunk_metadata(c, file_type)` spread from the metadata dict in `_process_kb_file()`. ChromaDB will stop receiving the 6 new fields. Documents already stored retain the fields (harmless extra metadata). No schema migration required.

### 9.4 FactPack Intermediate Layer (ADR-041)

ADR-041 introduces a **two-step LLM pipeline** with a structured JSON `FactPack` as
intermediate representation between retrieval and document rendering.

#### What changed in the pipeline

Previously, `generate_integration_doc()` performed one LLM synthesis act: RAG context →
Ollama → 16-section markdown. Residual `n/a` sections were filled by `_enrich_with_claude()`
using generic industry patterns, with no distinction between real project facts and
plausible defaults.

Now the pipeline has two steps when `FACT_PACK_ENABLED=true` (default):

1. **`extract_fact_pack()`** — LLM extracts structured facts from the assembled RAG context
   into a JSON `FactPack`. Claude API (`claude-sonnet-4-6`) is preferred when
   `ANTHROPIC_API_KEY` is set; Ollama fallback uses `temperature=0.0` for determinism.
   Returns `None` on any failure → automatic graceful degradation to the single-pass pipeline.

2. **`render_document_sections()`** — Ollama renders all 16 template sections from the
   FactPack JSON. Sections with no evidence are rendered as explicit evidence gap markers
   rather than `n/a`.

Between the two steps, **`validate_fact_pack()`** performs pure-Python validation
(scope correctness, claim ID uniqueness, confidence literal validity) and appends
advisory issues to the FactPack — never blocking generation.

#### Four confidence states

| State | Meaning | How it appears in the document |
|-------|---------|-------------------------------|
| `confirmed` | Directly stated in retrieved context chunks | Written as fact |
| `inferred` | Logically derived, not explicitly stated | Written as fact (implied) |
| `missing_evidence` | Required but absent from retrieved context | `> Evidence gap: [what is missing]` |
| `to_validate` | In requirements but needs human confirmation | Content + `> Requires validation: [...]` |

#### What reviewers see in the GenerationReport

The `generation_report` field on each `Approval` now includes:

| Field | Description |
|-------|-------------|
| `fact_pack_used` | `true` when the two-step path was used; `false` for single-pass fallback |
| `fact_pack_extraction_model` | `"claude-sonnet-4-6"` or `"ollama/{model}"` |
| `section_reports` | Per-section: heading, confidence score (0.0–1.0), cited chunk IDs, issues |
| `claim_reports` | All extracted claims with `claim_id`, `statement`, `confidence`, `source_chunk_count` |
| `confirmed_claim_count` | Number of claims directly supported by retrieved evidence |
| `missing_evidence_count` | Number of claims with no supporting context — high values signal thin KB coverage |
| `generation_path` | `"fact_pack"` \| `"single_pass_fallback"` \| `"single_pass_disabled"` — tracks which pipeline branch was taken |
| `fallback_reason` | Human-readable reason why the FactPack path was not used (empty when `generation_path == "fact_pack"`) |

**`generation_path` values:**

| Value | Meaning |
|-------|---------|
| `"fact_pack"` | Two-step pipeline completed successfully |
| `"single_pass_fallback"` | FactPack enabled but `extract_fact_pack()` returned `None` (LLM failure/JSON error/timeout); logs `[FactPack][WARN]` |
| `"single_pass_disabled"` | `FACT_PACK_ENABLED=false` kill-switch active |

#### Traceability Appendix (document-quality improvement #3)

Every generated document ends with a `## Appendix — Evidence & Generation Traceability` section automatically appended by `_build_traceability_appendix()`. It includes:

- **Generation Metadata** table (model, `generation_path`, quality score, Claude enrichment flag, character count)
- **Retrieved Sources** — up to 10 KB chunks with source label and a 120-character preview
- **Section Confidence** table (FactPack path only) — per-section score and issues
- **Evidence Claims** list (FactPack path only) — each claim with `claim_id`, statement, and source chunk count

The appendix is appended after `assess_quality()` so it does not affect the quality score.

#### Graceful degradation and kill-switch

If `extract_fact_pack()` returns `None` (LLM failure, JSON parse error, timeout),
`generate_integration_doc()` silently falls back to the original single-pass pipeline.
`fact_pack_used=false` in the report; `_enrich_with_claude()` is invoked as before.

To **disable** the FactPack pipeline entirely (revert to pre-ADR-041 behavior):

```bash
FACT_PACK_ENABLED=false   # environment variable
```

Or in `config.py`: `fact_pack_enabled: bool = False`.

No migration or data changes are required — all new `GenerationReport` fields have safe
defaults and existing MongoDB documents remain readable.

Test count: **365 tests** (309 + 56 ADR-041 tests: 7 JSON extraction, 10 validate, 9 extract Claude/Ollama, 5 render, 6 section reports, 14 generate integration doc pipeline, 2 backward compat, 3 schemas).

### 9.5 Prompt Builder Centralization (ADR-042)

ADR-042 addresses three structural issues that remained after ADR-041:

#### Centralized prompt construction

All prompt builders now live exclusively in `prompt_builder.py`. The private
`_build_extraction_prompt()` and `_build_rendering_prompt()` functions that
previously existed in `fact_pack_service.py` have been promoted to public
functions:

| Function | Pipeline step |
|----------|--------------|
| `build_prompt()` | Single-pass fallback (unchanged) |
| `build_fact_extraction_prompt()` | FactPack JSON extraction (ADR-041 step 1) |
| `build_section_render_prompt()` | FactPack rendering with section guidance |
| `build_prompt_for_mode()` | Unified mode dispatcher |

#### Section-aware rendering (`_SECTION_INSTRUCTIONS`)

The rendering prompt now includes a `SECTION GUIDANCE` block that maps each of
the 16 template sections to the specific FactPack fields the LLM should use:

- `Data Mapping & Transformation` → `entities`, `validations` (field-level table only)
- `Error Scenarios (Functional)` → `errors`, `validations` (HTTP codes, retry, fallback)
- `High-Level Architecture` → `systems`, `flows`, `integration_scope` (Mermaid diagram)
- `Security` → `business_rules`, `assumptions` with auth/security context

This reduces cross-section "blending" (architecture content appearing in data
mapping sections, etc.) without requiring 16 separate LLM calls.

#### Bugfix: `reviewer_feedback` in the FactPack path

In ADR-041, HITL reviewer rejection feedback was silently lost when
`fact_pack_used=True` because `reviewer_feedback` was not forwarded to
`render_document_sections()`. This is now fixed: the feedback is forwarded and
injected as a `PREVIOUS REJECTION FEEDBACK` block in the rendering prompt.

**Impact:** regeneration after a rejection now correctly incorporates the
reviewer's feedback even when the FactPack pipeline is active.

#### Context evidence weight guidance

The extraction prompt now explicitly explains the evidence weight of each
ContextAssembler output section to the LLM:

| Context section | Evidence weight |
|----------------|----------------|
| `PAST APPROVED EXAMPLES` | Highest — cite for `confirmed` claims |
| `KNOWLEDGE BASE` | Secondary — cite for `inferred` claims |
| `DOCUMENT SUMMARIES` | Overview only — not for specific claim citations |

Test count: **396 tests** (365 + 31 ADR-042 tests in `test_prompt_builder.py`:
9 extraction prompt, 12 rendering prompt, 5 dispatcher, 5 section instructions completeness). Further extended in document-quality improvements #1 and #2 (see §16).

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
The requirement that LLM output must start with `# Integration Design` is an application-level contract. It forces the model to commit to the expected document structure, making it harder for a prompt injection attack embedded in a requirement description to redirect the LLM's output into an unexpected format.

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

All integration-agent tests must pass before any commit (per CLAUDE.md Definition of Done). The current baseline is **420+ tests** (396 through ADR-042 + 25+ document-quality improvement tests added by improvements #1 and #2).

For the Ingestion Platform service:
```bash
cd services/ingestion-platform
python -m pytest tests/ -v
```

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
A read-only markdown browser for significant project documentation. Displays curated documents grouped by category (Guides, ADRs, Checklists, Test Plans, Mappings). Content is served from the mounted `docs/` directory — path traversal and non-.md requests are rejected by the backend.

### LLM Settings
An admin page for tuning LLM parameters at runtime without restarting the container. All three model profiles expose the **same set of parameters** plus a **Provider** selector (ADR-049):

| Parameter | Description | Notes |
|---|---|---|
| `provider` | LLM backend: `ollama` (local) or `gemini` (Google Gemini API) | Default: `ollama` |
| `model` | Model name — Ollama: `qwen2.5:14b` · Gemini: `gemini-2.0-flash` | Required for both providers |
| `num_predict` | Token cap for generation | Gemini: `max_output_tokens` |
| `timeout_seconds` | HTTP timeout for LLM calls | Applies to both providers |
| `temperature` | Sampling temperature (0 = deterministic) | Applies to both providers |
| `rag_max_chars` | Max characters of retrieved context injected into prompt | — |
| `num_ctx` | Context window size (Ollama only — ignored by Gemini) | — |
| `top_p` | Nucleus sampling threshold (Ollama only) | — |
| `top_k` | Top-K sampling tokens (Ollama only) | — |
| `repeat_penalty` | Penalizes token repetition (Ollama only) | — |

The three profile sections are:

| Profile | Group key | Default model | Default provider | Purpose |
|---|---|---|---|---|
| **Standard** | `doc_llm` | `qwen2.5:14b` | `ollama` | Standard document generation |
| **High Quality** | `premium_llm` | `gemma4:26b` | `ollama` | High-quality complex integrations |
| **Fast-Utility** | `tag_llm` | `qwen3:8b` | `ollama` | Tag suggestion & query expansion |

**Enabling Gemini:** Set `GEMINI_API_KEY=sk-...` in `.env`, recreate the container (`docker compose rm -f integration-agent && docker compose up -d integration-agent`), then switch any profile to `provider = gemini` in the UI. Gemini delivers 5–10× faster generation compared to CPU-bound Ollama.

Changes are applied **immediately** to the running agent and persisted in MongoDB. The "Reset to Defaults" button restores pydantic-settings values (as defined in `config.py` or overridden by env vars at startup).

**Why this matters:** Per-profile provider granularity lets you e.g. use Gemini for generation (Standard + High Quality) while keeping Fast-Utility on local Ollama for cheap, offline tagging — minimizing API cost while maximizing speed where it counts.

### Agent Settings
An admin page for tuning quality gate, RAG, FactPack, vision, and KB chunking parameters at runtime. All 15 parameters are configurable without container restarts and persisted to MongoDB:

| Group | Key parameters |
|---|---|
| **Quality Gate** | `quality_gate_mode` (warn/block), `quality_gate_min_score` (0–1) |
| **RAG & Retrieval** | `rag_distance_threshold`, `rag_bm25_weight`, `rag_n_results_per_query`, `rag_top_k_chunks`, `kb_max_rag_chars` |
| **Document Generation** | `fact_pack_enabled`, `fact_pack_max_tokens`, `llm_max_output_chars` |
| **Vision & Summarization** | `vision_captioning_enabled`, `raptor_summarization_enabled`, `kb_max_summarize_sections` |
| **KB Chunking** | `kb_chunk_size`, `kb_chunk_overlap` |

Fields show a yellow **MODIFIED** badge when their current value differs from the design default. The **Reset to Defaults** button restores all parameters to the values from `config.py` / env vars at startup.

### LLM Multi-Profile Routing (ADR-046)

The **Agent Workspace** page includes a **Generation Profile** selector visible when the agent is idle:

| Profile | Model | Use case |
|---|---|---|
| **Default** | `qwen2.5:14b` (`num_ctx=8192`, `temperature=0.1`) | Most integrations — balanced quality and latency |
| **High Quality** | `gemma4:26b` (`num_ctx=6144`, `temperature=0.0`) | Complex integrations with high ambiguity or reasoning demands |

The fast-utility profile (`qwen3:8b`) is used internally for tag suggestion and query expansion regardless of the selected generation profile.

**Model prerequisites:** pull models on the Ollama instance before use:
```bash
ollama pull qwen3:8b      # fast-utility (tags/expansion)
ollama pull gemma4:26b    # premium (on-demand)
```
If a model is not pulled, Ollama returns HTTP 404 and the agent logs a clear error message.

---

## 13. Phase 4 Polish — What Changed for End Users

Phase 4 introduced five targeted improvements to UX quality, observability, and code maintainability:

### Real-Time Progress Bar (R18)
The **Agent Workspace** page now shows a step-by-step progress bar during agent execution. Each major step (requirements load, RAG retrieval, LLM generation, HITL queuing) advances the bar in real time. Progress state is tracked in `state.agent_progress` on the backend and exposed via the `/agent/logs` response `"progress"` field.

### Toast Notifications for KB Actions (R6)
Adding or removing URLs from the Knowledge Base now triggers **toast notifications** (success/error) via the `sonner` library instead of inline error banners. Notifications appear in the top-right corner and dismiss automatically, keeping the KB page uncluttered.

### Fully English UI (R7)
All remaining Italian-language strings in the dashboard (`UnifiedDocumentsPanel`, `ProjectModal`) have been translated to English. The UI is now fully localized for English-speaking teams.

### Component Decomposition — KB and Requirements Pages (R4)
`KnowledgeBasePage.jsx` was a 700+ line monolith. It has been decomposed into focused sub-components under `src/components/kb/`: `SearchPanel`, `UnifiedDocumentsPanel`, `AddUrlForm`, `TagEditModal`, `PreviewModal`, and a shared `kbHelpers.js` utility module. Similarly, `TagConfirmPanel` was extracted from `RequirementsPage.jsx` into `src/components/requirements/`. This makes each component independently testable and easier to maintain.

### Audit Event Log — MongoDB (R19-MVP)
Every significant state-changing action (catalog entry creation, document approval/promotion, KB document upload/delete) is now recorded as an immutable audit event in a dedicated MongoDB `events` collection. Events are retained for 90 days via a TTL index. This provides a lightweight but persistent audit trail for compliance and debugging without requiring a separate logging infrastructure.

---

## 14. Phase 5 — Multi-Source Ingestion Platform

Phase 5 introduces a new independent service (`services/ingestion-platform/`, port 4006) and n8n workflow orchestrator (port 5678) that continuously populate the KB from four new source types without any changes to the existing RAG pipeline.

### Batch File Upload

The existing KB upload endpoint now has a companion: `POST /api/v1/kb/batch-upload` accepts up to 10 files in a single multipart request. Processing is sequential per file (to avoid BM25 index rebuild race conditions), and results are returned per file with **partial success**: if one file fails to parse, the others still succeed. Each result entry contains `filename`, `status` (`"success"` or `"error"`), `chunks_created`, and an optional `error` message.

### Ingestion Platform Architecture

```
services/ingestion-platform/
├── api/
│   ├── main.py                  ← FastAPI app, lifespan, MongoDB init
│   ├── config.py                ← pydantic-settings (ANTHROPIC_API_KEY optional)
│   └── routers/
│       ├── sources.py           ← CRUD source registry (MongoDB `sources` collection)
│       └── ingest.py            ← POST /api/v1/ingest/{openapi|html|mcp}/{source_id}
├── collectors/
│   ├── openapi/                 ← fetcher (ETag) · parser · normalizer · chunker · differ
│   ├── html/                    ← crawler (Playwright) · cleaner (BS4) · extractor (Claude Haiku) ·
│   │                               agent_extractor (Claude Sonnet) · normalizer
│   └── mcp/                     ← inspector (Python MCP SDK) · normalizer
├── services/
│   ├── indexing_service.py      ← ChromaDB writer — only DB writer in the service
│   ├── diff_service.py          ← hash comparison + Claude-powered diff summary
│   └── claude_service.py        ← Anthropic SDK wrapper (filter/extract/summarize)
└── models/
    ├── source.py                ← Source, SourceRun, SourceSnapshot (Pydantic)
    └── capability.py            ← CanonicalCapability, CanonicalChunk, CapabilityKind
```

### n8n Workflow Orchestration

Six n8n workflows (importable JSON in `workflows/n8n/`) drive all scheduled and manual ingestion:

| Workflow | Trigger | Action |
|---|---|---|
| WF-01 | Cron (every 1h) | Lists stale sources → dispatches WF-02/03/04 per source type |
| WF-02 | HTTP or WF-01 | OpenAPI: `POST /api/v1/ingest/openapi/{source_id}` |
| WF-03 | HTTP or WF-01 | HTML: `POST /api/v1/ingest/html/{source_id}` |
| WF-04 | HTTP or WF-01 | MCP: `POST /api/v1/ingest/mcp/{source_id}` → poll run status |
| WF-05 | Webhook (React UI) | Validates payload → dispatches typed refresh |
| WF-06 | Cron (daily) | Queries `changed=true&severity=breaking` runs → logs breaking_change_detected event |

### ChromaDB Integration — Zero Retriever Changes

Ingestion Platform chunks land in the **same `kb_collection`** as file uploads. The only differences are:

| Aspect | File Upload (`routers/kb.py`) | Ingestion Platform |
|--------|------------------------------|---------------------|
| Chunk ID prefix | `{doc_id}-chunk-{n}` (e.g., `KB-A1B2-chunk-0`) | `src_{source_code}-chunk-{n}` |
| Required metadata fields | `document_id`, `filename`, `chunk_index`, `tags_csv`, `section_header`, `chunk_type`, `page_num` | Same fields + `source_type`, `source_code`, `snapshot_id`, `capability_kind`, `low_confidence` |
| Retriever (`retriever.py`) | Unchanged | Unchanged — new metadata fields are ignored by existing queries |

### Claude API Usage (ADR-037)

The Ingestion Platform is the only component that calls the Anthropic Claude API. It is **not** used for the main RAG generation loop (which remains fully local via Ollama).

| Component | Model | Purpose |
|---|---|---|
| `HTMLRelevanceFilter` | claude-haiku-4-5-20251001 | Binary: is this page technically relevant? |
| `HTMLAgentExtractor` | claude-sonnet-4-6 | UI semantic extraction: screens, roles, fields, validations, state transitions as structured JSON (ADR-045) |
| `DiffService.summarize()` | claude-haiku-4-5-20251001 | Human-readable change summary (max 200 tokens) |

**Graceful degradation:** if `ANTHROPIC_API_KEY` is not set, `ClaudeService` returns `None`; the HTML filter defaults to `True` (include all pages conservatively) and the extractor returns `[]` (no capabilities extracted). The service runs fully without a Claude API key, just with reduced HTML extraction quality.

### UI Semantic Extraction (ADR-045)

The HTML collector is designed as **UI semantic extraction**, not text scraping. When Claude identifies an application screen or backoffice page in the documentation, it extracts a structured `ui_context` block:

```json
{
  "page": "Product Publish",
  "role": "Merchandiser",
  "fields": [{"name": "status", "type": "dropdown", "values": ["Draft", "Published"]}],
  "actions": ["Save", "Publish"],
  "validations": ["SKU mandatory before publish"],
  "messages": ["Product published successfully"],
  "state_transitions": ["Draft -> Published"]
}
```

This `ui_context` is stored in `CanonicalCapability.metadata` and drives the `HTMLChunker` to generate typed chunks instead of a single generic text block:

| Chunk type | Content | Retrieval benefit |
|---|---|---|
| `ui_flow_chunk` | Full screen: name, role, fields, actions | "What does the Publish screen look like?" |
| `validation_rule_chunk` | One rule per chunk | "What validates SKU before publish?" |
| `state_transition_chunk` | One transition per chunk | "What states does a product go through?" |

Non-UI capabilities (API endpoints, auth, schemas) are unaffected — they still produce a single `text` chunk. The `CanonicalChunk.chunk_type` field carries the chunk type into ChromaDB metadata, enabling future retriever-side filtering by chunk type.

### Data Governance

- All 3 collector types share the same `CanonicalCapability` model with a `CapabilityKind` enum (ENDPOINT, TOOL, RESOURCE, SCHEMA, AUTH, INTEGRATION_FLOW, GUIDE_STEP, EVENT, OVERVIEW, UI_SCREEN).
- Capabilities with confidence < 0.7 (from Claude extraction) are **kept** in the KB but tagged `low_confidence=True` in metadata — not silently discarded, to allow human review.
- Claude output is always validated against Pydantic models before any DB write. Claude never writes to the DB directly — `IndexingService` is the sole ChromaDB writer in the service.

---

## 15. Pixel UI Mode (ADR-047)

The dashboard supports a **dual UI system**: Classic mode (default) and Pixel mode — an 8-bit RPG aesthetic that gamifies the agentic pipeline for demos and internal presentations.

### Toggling Modes

A **Pixel** button appears in the top-right navigation bar (TopBar). Clicking it switches to pixel mode. The mode persists across page refreshes via `localStorage` (`ui_mode` key). A "Classic Mode" button in the pixel sidebar switches back.

### What Changes in Pixel Mode

| Element | Classic | Pixel |
|---|---|---|
| Background | Slate-50 light | `#0d0d0d` dark |
| Font | Outfit / Jakarta Sans | Press Start 2P (Google Fonts) |
| Sidebar | `Sidebar.jsx` (Tailwind) | `PixelSidebar.jsx` (pixel CSS) |
| Agent Workspace | `AgentWorkspacePage` | `PixelAgentWorkspace` |
| All other pages | Tailwind prose | Inherit `.pixel-mode` root class |

### Agent Personas

Each pipeline stage is mapped to an RPG character that narrates the agent's progress:

| Stage | Persona | Role |
|---|---|---|
| Ingestion | **Archivist** 📜 | Reads requirements and prepares catalog entries |
| Retrieval | **Librarian** 🔍 | Searches the knowledge vault for matching scrolls |
| Generation | **Writer** ✍️ | Inscribes the integration scroll |
| QA | **Guardian** 🛡️ | Inspects output for quality and threats |
| Enrichment | **Mage** 🔮 | Invokes the Ancient API (Claude) for enrichment |

Sprite states (idle / working / success / error) are rendered as emoji with CSS keyframe animations (`pixel-blink`, `pixel-glow`, `pixel-shake`).

### Quest Log

Agent log messages are transformed by `PersonaNarrator.js` from technical strings (e.g. `[RAG] hybrid retrieval completed`) into RPG narration lines (e.g. `📚 Librarian assembled the context grimoire!`). The stage is inferred from message content via `inferStageFromLog()`.

### Architecture Isolation

All pixel components live in `src/components/pixel/`. Classic mode code is completely unchanged — the `UiModeProvider` wraps the app root and applies `.pixel-mode` to the wrapper div, but has no effect on Classic mode rendering. The pixel workspace reuses all existing React hooks (`useAgentLogs`, `useAgentStatus`) — no backend API changes.

---

## 16. Document Quality Improvements (#1–#4)

Four incremental improvements to the generated document quality pipeline, implemented after ADR-042.

### Improvement #1 — Presence Signals (6 volume checks)

Extended `assess_quality()` in `output_guard.py` from 3 to 6 signals:

| Signal | Threshold | Notes |
|--------|-----------|-------|
| Section count | ≥ 10 `## ` headings | Template has 16 sections |
| n/a ratio | < 50% | Sections containing only `n/a` |
| Word count | ≥ 300 | Total words in document |
| Mermaid diagram | Present | At least one ` ```mermaid ` block |
| Mapping table | Present | At least one pipe-table separator row |
| Placeholder count | 0 | Unfilled `{...}` template tokens |

The `quality_score` formula was updated to weight all 6 signals equally. The `QualityReport` dataclass gained `has_mermaid_diagram`, `mapping_table_count`, and `placeholder_count` fields.

### Improvement #2 — Structural Validators (3 validators)

Added `_validate_mermaid_blocks()`, `_validate_mapping_tables()`, and `_validate_section_artifacts()` to `output_guard.py`. Issues raised by these validators populate `report.issues` and influence `report.passed` but do **not** change `quality_score` (which measures content density, not structure).

The `QualityReport` dataclass gained three sub-report lists: `mermaid_syntax_issues`, `table_structure_issues`, `section_artifact_issues`.

### Improvement #3 — Traceability Appendix

`_build_traceability_appendix(report, source, target) -> str` appended to every generated document after quality assessment. See §9.4 for full field description.

### Improvement #4 — Generation Path Tracking + FactPack Warning Escalation

`GenerationReport` gained `generation_path` and `fallback_reason` fields. The single-pass fallback log level was upgraded from `logger.info` to `logger.warning` — making FactPack degradation visible in monitoring without changing behavior.

The **Agent Settings** page (§12) exposes `quality_gate_mode` and `quality_gate_min_score` to toggle the gate between warn and block modes without a container restart.
