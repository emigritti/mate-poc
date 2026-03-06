# Functional Integration Mate — Architecture Specification

## 1. System Context
The Functional Integration Mate is an AI-powered platform designed to automate the initial phases of enterprise integration design. Instead of manually writing Functional and Technical Specifications based on Jira/Excel requirements, Integration Mate ingests raw requirements (CSV), analyzes source/target systems via OpenAPI specs, and employs an **Agentic RAG** approach to generate high-quality Markdown specifications.

It strictly focuses on the **Documentation and Cataloging** aspect of integration streams, rather than acting as a runtime execution middleware (like an ESB or iPaaS).

## 2. Component Architecture

### 2.1 Web Dashboard (Frontend)
- **Tech Stack:** Vanilla HTML/JS/CSS (SPA), Nginx.
- **Responsibility:** Provides the UI for users to upload requirements (CSV), view mocked API Swaggers, trigger the AI Agent, monitor generation logs in real-time, view the resulting Integration Catalog, and perform Human-in-the-Loop (HITL) reviews.

### 2.2 Integration Agent (Backend)
- **Tech Stack:** Python 3.12, FastAPI, Pydantic, Requests.
- **Responsibility:** The core brain of the PoC.
  - **Parser:** Reads and groups CSV requirements by Source-Target pairs into "Catalog Entries".
  - **Agentic Loop:** Formulates queries based on requirements, fetches context from Vector DB, constructs LLM prompts, and coordinates generation with Ollama.
  - **HITL Manager:** Exposes endpoints to suspend documents in a `PENDING` state until human review is complete, then persists the final artifact.

### 2.3 Local LLM Inference
- **Tech Stack:** Ollama, `llama3.1:8b`, `nomic-embed-text`.
- **Responsibility:** Generates human-readable Markdown specifications based on the structured requirements and the provided Agent RAG context.

### 2.4 Vector Database (RAG Store)
- **Tech Stack:** ChromaDB.
- **Responsibility:** Stores historical `Requirement -> Human-Approved Document` pairs. Provides semantic search capabilities so the Agent can retrieve past similar integration patterns as few-shot examples.

### 2.5 Catalog Store
- **Tech Stack:** MongoDB.
- **Responsibility:** Stores the structured Integration Catalog metadata (id, source, target, status) and tracks the lifecycle of generated documents.

### 2.6 Mock APIs
- **Tech Stack:** FastAPI, local Swagger UI.
- **Responsibility:** `plm-mock` and `pim-mock` serve as simulated source and target systems, providing realistic OpenAPI schemas that the Agent will eventually read to understand data structures.

## 3. The Agentic RAG Workflow

1. **Upload:** User uploads `sample-requirements.csv`.
2. **Cluster:** The Backend groups requirements (e.g., all PLM -> PIM requirements form one `IntegrationEntry`).
3. **Retrieval (Agentic steps):**
   - The Agent extracts keywords from the requirement descriptions.
   - It queries ChromaDB against the `approved_integrations` collection.
   - It "grades" the returned vectors. If they match the current context, it uses them. Otherwise, it falls back to zero-shot generation.
4. **Generation:** The Agent sends a prompt via `requests` to Ollama. The prompt includes: The Persona, the newly uploaded Requirements, and the RAG-retrieved examples.
5. **Review (HITL):** The LLM generates the Markdown. It is stored as `PENDING`.
6. **Approval:** A Human Reviewer opens the Dashboard, edits any hallucinations or stylistic issues in the Markdown, and clicks "Approve."
7. **Embed & Learn:** Upon approval, the final Markdown is pushed to ChromaDB, essentially teaching the local model the exact desired format for the next run.

## 4. Deployment Model
The entire PoC runs locally via `docker-compose`. 
It utilizes 6 containers: `mongodb`, `chromadb`, `ollama` (requires pre-pulled models), `plm-mock`, `pim-mock`, `integration-agent`, and `web-dashboard`.
