# Functional Integration Mate — Architecture Specification

> **Version:** 2.0 — Updated to reflect current codebase state (11 services, template injection, HITL lifecycle, full security model)
> **Governance:** Accenture Responsible AI — Human-in-the-Loop required for all AI-generated artifacts.

---

## 1. System Context

### 1.1 Purpose

The **Functional Integration Mate** is an AI-powered PoC platform designed to automate the initial documentation phases of enterprise integration design. Instead of manually authoring Functional and Technical Specifications from Jira/Excel requirements, Integration Mate ingests raw requirements (CSV), applies an **Agentic RAG** approach to generate high-quality structured Markdown specifications, and enforces a mandatory **Human-in-the-Loop (HITL)** approval gate before any document is persisted.

The platform focuses strictly on the **Documentation and Cataloging** layer of the integration lifecycle — not on runtime execution (ESB, iPaaS, or middleware role).

### 1.2 Primary Use Case

```
Business Analyst or Integration Architect
  → uploads CSV of integration requirements
  → triggers AI agent
  → reviews AI-generated Functional Design document
  → approves or rejects with feedback
  → approved document is stored and feeds the RAG learning loop
```

---

## 2. C4 Model — Level 1: System Context

```mermaid
graph TB
    analyst["👤 Integration Analyst<br/>(Business Analyst / Architect)<br/><i>Uploads requirements, reviews<br/>and approves AI-generated docs</i>"]

    subgraph mate["🧠 Functional Integration Mate"]
        core["Integration Mate Platform<br/><i>Agentic RAG · HITL · Catalog</i>"]
    end

    subgraph external["External / Simulated Systems"]
        plm_sys["PLM System<br/><i>Product Lifecycle Mgmt</i>"]
        pim_sys["PIM System<br/><i>Product Information Mgmt</i>"]
        dam_sys["DAM System<br/><i>Digital Asset Mgmt</i>"]
    end

    analyst -- "Upload CSV, trigger agent,<br/>review & approve docs" --> core
    core -- "Reads OpenAPI specs<br/>(mock, future live)" --> plm_sys
    core -- "Reads OpenAPI specs<br/>(mock, future live)" --> pim_sys
    core -- "Reads OpenAPI specs<br/>(mock, future live)" --> dam_sys
```

**System boundaries:**
- The platform is a **PoC** running entirely on a single host via Docker Compose.
- All external systems (PLM, PIM, DAM) are currently simulated by mock FastAPI services.
- The LLM runs **locally** (Ollama) — no data leaves the host.

---

## 3. C4 Model — Level 2: Container Diagram

The platform is composed of **11 Docker containers** grouped in three logical tiers.

```mermaid
graph TB
    analyst["👤 Integration Analyst"]

    subgraph frontend["Frontend Layer"]
        dashboard["Web Dashboard<br/><b>HTML / JS / Nginx</b><br/>:8080<br/><i>SPA: CSV upload, agent control,<br/>real-time logs, HITL review, catalog</i>"]
    end

    subgraph agent_layer["Agent Layer"]
        agent["Integration Agent<br/><b>Python 3.12 / FastAPI</b><br/>:4003<br/><i>Core brain: Agentic RAG loop,<br/>prompt building, HITL lifecycle,<br/>output sanitization, catalog mgmt</i>"]
        catalog_gen["Catalog Generator<br/><b>FastAPI / Node.js</b><br/>:4004<br/><i>Catalog composition<br/>and enrichment</i>"]
        security_mw["Security Middleware<br/><b>FastAPI / JWT</b><br/>:4000<br/><i>API gateway · RBAC<br/>(PoC: passthrough)</i>"]
    end

    subgraph data_layer["Data & AI Layer"]
        mongo["MongoDB 7<br/>:27017<br/><i>Catalog entries · Approvals<br/>· Final documents</i>"]
        chroma["ChromaDB 0.5.3<br/>:8000<br/><i>Vector store — approved<br/>integration examples (RAG)</i>"]
        ollama["Ollama<br/>llama3.2:3b / llama3.1:8b<br/>:11434<br/><i>Local LLM inference</i>"]
        minio["MinIO (S3-compatible)<br/>:9000 / :9001<br/><i>Object storage for<br/>mock system files</i>"]
    end

    subgraph mock_layer["Mock Systems Layer"]
        plm["PLM Mock API<br/><b>FastAPI</b><br/>:4001<br/><i>Simulated source system</i>"]
        pim["PIM Mock API<br/><b>FastAPI</b><br/>:4002<br/><i>Simulated target system</i>"]
        dam["DAM Mock API<br/><b>FastAPI</b><br/>:4005<br/><i>Simulated asset system</i>"]
    end

    analyst --> dashboard
    dashboard -- "REST API :4003" --> agent
    agent -- "TCP :27017" --> mongo
    agent -- "HTTP :8000" --> chroma
    agent -- "HTTP :11434" --> ollama
    dashboard -- "Swagger :4001" --> plm
    dashboard -- "Swagger :4002" --> pim
    dashboard -- "Swagger :4005" --> dam
    plm -- "S3 :9000" --> minio
    pim -- "S3 :9000" --> minio
    dam -- "S3 :9000" --> minio
    catalog_gen -- "HTTP :4003" --> agent
```

### Container Details

| Container | Image / Stack | Port (ext → int) | Key Responsibility |
|-----------|--------------|-------------------|--------------------|
| `mate-web-dashboard` | Nginx + Vanilla JS | `8080 → 80` | SPA: upload, agent control, logs, HITL, catalog |
| `mate-integration-agent` | Python 3.12 / FastAPI + Motor | `4003 → 3003` | Agentic RAG loop, all business logic, 15 REST endpoints |
| `mate-catalog-generator` | FastAPI | `4004 → 3004` | Catalog composition from agent output |
| `mate-security-middleware` | FastAPI + JWT | `4000 → 3000` | Auth gateway (passthrough in PoC dev mode) |
| `mate-mongodb` | MongoDB 7 | `27017 → 27017` | Persistent store: catalog, approvals, documents |
| `mate-chromadb` | ChromaDB 0.5.3 | `8000 → 8000` | Vector store: RAG retrieval of approved examples |
| `mate-ollama` | Ollama | `11434 → 11434` | Local LLM inference (llama3.2:3b or llama3.1:8b) |
| `mate-minio` | MinIO | `9000/9001` | S3-compatible object storage for mock systems |
| `mate-plm-mock` | FastAPI | `4001 → 3001` | Simulated PLM system with OpenAPI spec |
| `mate-pim-mock` | FastAPI | `4002 → 3002` | Simulated PIM system with OpenAPI spec |
| `mate-dam-mock` | FastAPI | `4005 → 3005` | Simulated DAM system with OpenAPI spec |

---

## 4. C4 Model — Level 2 (zoom): Integration Agent Components

The Integration Agent is the core service. Its internal components are:

```mermaid
graph TB
    subgraph agent_container["Integration Agent Container (mate-integration-agent)"]

        subgraph api["API Layer (FastAPI)"]
            ep_req["Requirements Endpoints<br/><i>/upload · /requirements</i>"]
            ep_agent["Agent Control Endpoints<br/><i>/trigger · /cancel · /logs</i>"]
            ep_catalog["Catalog Endpoints<br/><i>/catalog · /functional-spec</i>"]
            ep_hitl["HITL Endpoints<br/><i>/approvals · /approve · /reject</i>"]
            ep_admin["Admin Endpoints<br/><i>/reset/requirements · /mongodb · /chromadb · /all</i>"]
        end

        subgraph core_components["Core Components"]
            csv_parser["CSV Parser<br/><i>Validates MIME · size · UTF-8<br/>Groups by source→target pair</i>"]
            rag_query["RAG Query Engine<br/><i>Queries ChromaDB<br/>n_results=2 similar examples</i>"]
            prompt_builder["Prompt Builder<br/><i>Loads reusable-meta-prompt.md<br/>Injects functional template<br/>Safe str.replace() substitution</i>"]
            llm_client["LLM Client<br/><i>httpx.AsyncClient → Ollama<br/>Timeout: 600s · Async stream=false</i>"]
            output_guard["Output Guard<br/><i>Structural check (heading)<br/>bleach allowlist · Truncate 50k</i>"]
            hitl_manager["HITL Manager<br/><i>Status machine: PENDING→APPROVED/REJECTED<br/>sanitize_human_content()</i>"]
            catalog_mgr["Catalog Manager<br/><i>Groups reqs by source|||target<br/>Write-through to MongoDB</i>"]
        end

        subgraph infra_components["Infrastructure Components"]
            config["Config (Pydantic Settings)<br/><i>Env vars: OLLAMA_HOST, MONGO_URI<br/>CHROMA_HOST, API_KEY, CORS</i>"]
            db["DB Layer (Motor async)<br/><i>catalog_col · approvals_col<br/>documents_col · write-through cache</i>"]
            lock["Concurrency Guard<br/><i>asyncio.Lock — prevents<br/>concurrent LLM calls</i>"]
            logger["Agent Logger<br/><i>In-memory ring buffer<br/>Last 50 lines · real-time poll</i>"]
        end

    end

    ep_agent --> csv_parser
    ep_agent --> lock
    lock --> rag_query
    rag_query --> prompt_builder
    prompt_builder --> llm_client
    llm_client --> output_guard
    output_guard --> hitl_manager
    hitl_manager --> db
    hitl_manager --> ep_hitl
    ep_req --> csv_parser
    ep_catalog --> catalog_mgr
    catalog_mgr --> db
    db --> config
```

### Component Responsibilities

| Component | File | Key Behaviour |
|-----------|------|---------------|
| **CSV Parser** | `main.py` | MIME/size/encoding guards; groups rows by `source|||target` key |
| **RAG Query Engine** | `main.py` | `collection.query(n_results=2)` against `approved_integrations` collection |
| **Prompt Builder** | `prompt_builder.py` | Loads meta-prompt + functional template from mounted volumes; `str.replace()` injection |
| **LLM Client** | `main.py` | `httpx.AsyncClient.post()` to Ollama `/api/generate`; logs token metrics |
| **Output Guard** | `output_guard.py` | Checks `# Integration Functional Design` heading; bleach strip; 50k truncation |
| **HITL Manager** | `main.py` | Status state machine (`PENDING → APPROVED/REJECTED`); sanitizes reviewer edits |
| **Catalog Manager** | `main.py` | Write-through: in-memory dict + MongoDB upsert on every mutation |
| **Config** | `config.py` | `pydantic-settings` — fails fast on startup if required env vars absent |
| **DB Layer** | `db.py` | `motor.AsyncIOMotorClient`; init with retry (10×3s); seeds in-memory on startup |
| **Concurrency Guard** | `main.py` | `asyncio.Lock` — one LLM flow at a time; task cancellable via `/agent/cancel` |
| **Agent Logger** | `main.py` | Module-level `list[str]`; last 50 entries; polled by dashboard every 2s |

---

## 5. Agentic RAG Workflow — Detailed Flow

The end-to-end flow from CSV upload to approved document:

```mermaid
sequenceDiagram
    actor Analyst
    participant Dashboard as Web Dashboard
    participant Agent as Integration Agent
    participant Chroma as ChromaDB
    participant Ollama as Ollama LLM
    participant Mongo as MongoDB

    Analyst->>Dashboard: Upload requirements.csv
    Dashboard->>Agent: POST /api/v1/requirements/upload
    Agent-->>Dashboard: { total_parsed: N }

    Analyst->>Dashboard: Click "Start Agent Processing"
    Dashboard->>Agent: POST /api/v1/agent/trigger
    Agent-->>Dashboard: { status: "started", task_id: "..." }

    loop For each (source, target) pair
        Agent->>Agent: Group requirements by source|||target
        Agent->>Mongo: Upsert CatalogEntry (status=generated)
        Agent->>Chroma: query(similar past examples, n=2)
        Chroma-->>Agent: rag_context (or empty)
        Agent->>Agent: build_prompt(src, tgt, reqs, rag_context, template)
        Agent->>Ollama: POST /api/generate {model, prompt}
        Ollama-->>Agent: raw markdown
        Agent->>Agent: sanitize_llm_output(raw)
        Agent->>Mongo: Upsert Approval (status=PENDING)
    end

    Dashboard->>Agent: GET /api/v1/approvals/pending (poll)
    Agent-->>Dashboard: [{ id, content, status=PENDING }]

    Analyst->>Dashboard: Review & edit markdown in HITL editor
    Analyst->>Dashboard: Click "Approve & Save to RAG"
    Dashboard->>Agent: POST /api/v1/approvals/{id}/approve { final_markdown }
    Agent->>Agent: sanitize_human_content(final_markdown)
    Agent->>Mongo: Upsert Document (status=APPROVED)
    Agent->>Chroma: upsert(document, metadata) → feeds RAG loop
    Agent-->>Dashboard: { status: "approved" }
```

### Workflow Steps Summary

| Step | Actor | Action | Guard / Security |
|------|-------|--------|-----------------|
| 1. Upload | Analyst | POST CSV file | MIME check, 1 MB limit, UTF-8 guard |
| 2. Trigger | Analyst | POST /agent/trigger | `asyncio.Lock` prevents concurrent runs |
| 3. Group | Agent | Cluster reqs by source+target | `|||` separator (not hyphen — avoids system name collision) |
| 4. RAG Query | Agent | Semantic search ChromaDB | n_results=2; falls back to zero-shot if no match |
| 5. Build Prompt | Agent | Inject meta-prompt + template + RAG | `str.replace()` — no `format()` (prevents KeyError) |
| 6. LLM Call | Agent | POST to Ollama | 600s timeout; async; error caught → log + skip |
| 7. Output Guard | Agent | Structural + XSS check | Must start with `# Integration Functional Design` |
| 8. HITL Queue | Agent | Store as PENDING | No automatic write to final store without human |
| 9. Human Review | Analyst | Edit + Approve/Reject in UI | `sanitize_human_content()` on submit |
| 10. RAG Learn | Agent | Upsert approved doc → ChromaDB | Feeds future generations with approved patterns |

---

## 6. Data Architecture

### 6.1 MongoDB Collections

```
mongodb://mate-mongodb:27017/integration_mate
  ├── catalog_entries       { id, name, type, source, target, status, requirements[] }
  ├── approvals             { id, integration_id, doc_type, content, status, generated_at, feedback? }
  └── documents             { id, integration_id, doc_type, content, generated_at }
```

**Indexing strategy:**
- `catalog_entries`: unique index on `id`
- `approvals`: unique index on `id` + secondary index on `status` (fast PENDING filter)
- `documents`: unique index on `id`

**Persistence pattern — Write-Through Cache:**
Every mutation writes simultaneously to the in-memory Python dict AND to MongoDB. On container startup, `lifespan()` seeds all three dicts from MongoDB — surviving container restarts without data loss.

### 6.2 ChromaDB Collection

```
approved_integrations collection
  documents: [approved markdown content]
  metadatas: [{ integration_id, type: "functional" }]
  ids:        ["{integration_id}-functional"]
```

Used exclusively for **RAG retrieval**: when a new integration requires documentation, past approved examples are retrieved via semantic similarity search and injected into the LLM prompt as few-shot examples.

### 6.3 In-Memory State

| Variable | Type | Purpose | Persisted? |
|----------|------|---------|------------|
| `parsed_requirements` | `list[Requirement]` | Current CSV upload | No (transient) |
| `catalog` | `dict[str, CatalogEntry]` | Integration entries | Yes (MongoDB) |
| `documents` | `dict[str, Document]` | Approved final docs | Yes (MongoDB + ChromaDB) |
| `approvals` | `dict[str, Approval]` | HITL queue items | Yes (MongoDB) |
| `agent_logs` | `list[str]` | Real-time execution log | No (last 50 entries) |
| `_agent_lock` | `asyncio.Lock` | Concurrency guard | No |
| `_running_tasks` | `dict[str, asyncio.Task]` | Cancellable tasks | No |

---

## 7. API Surface — Integration Agent

All endpoints are served by `mate-integration-agent` on port `4003`.

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | — | Service + ChromaDB + MongoDB health |
| `/api/v1/requirements/upload` | POST | — | Parse CSV; validate MIME/size/encoding |
| `/api/v1/requirements` | GET | — | List all parsed requirements |
| `/api/v1/agent/trigger` | POST | Token | Start agentic RAG flow (async) |
| `/api/v1/agent/cancel` | POST | Token | Cancel running agent task |
| `/api/v1/agent/logs` | GET | — | Stream last 50 log lines |
| `/api/v1/catalog/integrations` | GET | — | List all catalog entries |
| `/api/v1/catalog/integrations/{id}/functional-spec` | GET | — | Get approved functional spec |
| `/api/v1/catalog/integrations/{id}/technical-spec` | GET | — | *Not yet implemented* |
| `/api/v1/approvals/pending` | GET | — | List PENDING approvals |
| `/api/v1/approvals/{id}/approve` | POST | Token | Approve + persist + feed RAG |
| `/api/v1/approvals/{id}/reject` | POST | Token | Reject with feedback |
| `/api/v1/admin/reset/requirements` | DELETE | Token | Clear parsed reqs + logs |
| `/api/v1/admin/reset/mongodb` | DELETE | Token | Wipe all MongoDB collections |
| `/api/v1/admin/reset/chromadb` | DELETE | Token | Wipe ChromaDB RAG collection |
| `/api/v1/admin/reset/all` | DELETE | Token | Full system reset |

**Auth model:** Optional Bearer token. If `API_KEY` env var is set, mutating endpoints (`trigger`, `cancel`, `approve`, `reject`, `reset/*`) require `Authorization: Bearer <key>`. If unset, endpoints log a warning and allow through (dev/PoC mode).

---

## 8. Security Architecture

Security controls applied at each layer (OWASP ASVS aligned):

| Layer | Control | Implementation | OWASP |
|-------|---------|----------------|-------|
| API Auth | Bearer token (optional) | `hmac.compare_digest()` — constant-time | A07 |
| CORS | Allowlist from env var | No `*` with credentials | A05 |
| Input | CSV guards | MIME type, 1 MB size, UTF-8 encoding | A03 |
| Input | Request bodies | Pydantic `Field(min_length, max_length)` | A03 |
| LLM Output | Structural guard | Must start `# Integration Functional Design` | A03 |
| LLM Output | HTML sanitization | `bleach.clean(strip=True, tags=allowlist)` | A03 |
| LLM Output | Truncation | Max 50,000 characters | A03 |
| Frontend | XSS prevention | `escapeHtml()` on all server-sourced innerHTML | A03 |
| Frontend | Textarea injection | Content set via `.value`, not `innerHTML` | A03 |
| Secrets | No hardcoded values | `pydantic-settings` from env vars / `.env` | A02 |
| Prompt | Injection prevention | `str.replace()` — not `str.format()` | A03 |

**Responsible AI controls (Accenture standard):**
- Human-in-the-Loop gate: no AI-generated document reaches the final store without human approval.
- LLM output is always treated as untrusted input (structural guard + bleach).
- All AI usage is transparent and logged (agent_logs).

---

## 9. Deployment Architecture

```mermaid
graph TB
    subgraph host["Docker Host (single machine)"]
        subgraph net["integration-mate-net (bridge network)"]
            dashboard["mate-web-dashboard<br/>Nginx :80"]
            agent["mate-integration-agent<br/>FastAPI :3003"]
            catalog["mate-catalog-generator<br/>FastAPI :3004"]
            security["mate-security-middleware<br/>FastAPI :3000"]
            mongo["mate-mongodb<br/>MongoDB :27017"]
            chroma["mate-chromadb<br/>ChromaDB :8000"]
            ollama["mate-ollama<br/>Ollama :11434"]
            minio["mate-minio<br/>MinIO :9000"]
            plm["mate-plm-mock :3001"]
            pim["mate-pim-mock :3002"]
            dam["mate-dam-mock :3005"]
        end

        subgraph vols["Named Volumes"]
            mongo_vol["mongo-data"]
            chroma_vol["chroma-data"]
            ollama_vol["ollama-data"]
            minio_vol["minio-data"]
        end

        subgraph mounts["Read-Only Volume Mounts on Integration Agent"]
            prompt_mount["./reusable-meta-prompt.md → /reusable-meta-prompt.md"]
            template_mount["./template/ → /template/"]
        end
    end

    user["Browser"] -- ":8080" --> dashboard
```

**Port mapping (host → container):**

| Host Port | Container | Service |
|-----------|-----------|---------|
| 8080 | 80 | Web Dashboard |
| 4000 | 3000 | Security Middleware |
| 4001 | 3001 | PLM Mock |
| 4002 | 3002 | PIM Mock |
| 4003 | 3003 | Integration Agent |
| 4004 | 3004 | Catalog Generator |
| 4005 | 3005 | DAM Mock |
| 8000 | 8000 | ChromaDB |
| 9000/9001 | 9000/9001 | MinIO |
| 11434 | 11434 | Ollama |
| 27017 | 27017 | MongoDB |

**Notable deployment detail:** `reusable-meta-prompt.md` and `template/` live at the project root, outside the Docker build context of the integration-agent service. They are exposed inside the container via read-only volume mounts at `/reusable-meta-prompt.md` and `/template/` respectively — matching the path resolution of `Path(__file__).parent.parent.parent` from within `/app/`.

---

## 10. ADR Index

| ADR | Decision | Status |
|-----|----------|--------|
| ADR-001–011 | Early foundational decisions (tooling, patterns) | Accepted |
| ADR-012 | Async LLM client via `httpx.AsyncClient` | Accepted |
| ADR-013 | MongoDB persistence + Motor async driver | Accepted |
| ADR-014 | External prompt template (`reusable-meta-prompt.md`) | Accepted |
| ADR-015 | LLM output guard (structural + bleach) | Accepted |
| ADR-016 | Secret management via Pydantic Settings | Accepted |
| ADR-017 | Frontend XSS mitigation (`escapeHtml()`) | Accepted |
| ADR-018 | CORS standardization (env-var allowlist) | Accepted |

---

## 11. Known Limitations & Future Work

| Item | Current State | Planned |
|------|--------------|---------|
| Technical spec generation | Endpoint returns 501 stub | Implement `template/technical/` flow |
| Security middleware | Passthrough in PoC | Full JWT/RBAC integration |
| OpenAPI spec reading | Mock Swaggers only | Live spec ingestion for data mapping |
| Model quality | llama3.2:3b (fast, PoC) | Configurable via `OLLAMA_MODEL` env var |
| RAG grading | Basic similarity (n=2) | Re-ranking and relevance scoring |
| Embedding model | Default ChromaDB embeddings | Switch to `nomic-embed-text` for richer semantics |
