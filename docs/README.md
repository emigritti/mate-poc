# Architecture, Quality & Compliance Documentation

> **Root:** `docs/`
> This index covers every document in this folder. Each entry links to the file and summarises its purpose in one line.

---

## Core Guides

| Document | Purpose |
|---|---|
| [functional-guide.md](functional-guide.md) | How the system works end-to-end; technology choices; AI governance model |
| [architecture_specification.md](architecture_specification.md) | Full architecture spec: services, data flows, deployment topology |
| [DOCUMENT-GENERATION-PIPELINE.md](DOCUMENT-GENERATION-PIPELINE.md) | Step-by-step walkthrough of the document generation pipeline |
| [different-LLMs-and-their-usage.md](different-LLMs-and-their-usage.md) | Which LLM is used for each task, why, and what alternatives exist |
| [how-to-graph-rag.md](how-to-graph-rag.md) | How the LLM Wiki and Graph RAG work; KB migration guide |
| [AWS-DEPLOYMENT-GUIDE.md](AWS-DEPLOYMENT-GUIDE.md) | EC2 deployment, Docker Compose startup, environment configuration |

---

## Architecture Decision Records (ADRs)

> `docs/adr/` — one file per significant decision. Use [ADR-000-template.md](adr/ADR-000-template.md) for new records.

### Foundation (ADR-001 – ADR-016)

| ADR | Decision |
|---|---|
| [ADR-001–011](adr/ADR-001-011-decisions.md) | Consolidated early decisions (async, MongoDB, prompt builder, output guard, secrets) |
| [ADR-012](adr/ADR-012-async-llm-client.md) | Async-first LLM client (httpx) |
| [ADR-013](adr/ADR-013-mongodb-persistence.md) | MongoDB for catalog and approval persistence |
| [ADR-014](adr/ADR-014-prompt-builder.md) | Prompt builder centralisation |
| [ADR-015](adr/ADR-015-llm-output-guard.md) | LLM output guard and XSS sanitisation |
| [ADR-016](adr/ADR-016-secret-management.md) | Secret management via Pydantic Settings and environment variables |

### Security & Infrastructure (ADR-017 – ADR-022)

| ADR | Decision |
|---|---|
| [ADR-017](adr/ADR-017-frontend-xss-mitigation.md) | Frontend XSS mitigation (`escapeHtml`) |
| [ADR-018](adr/ADR-018-cors-standardization.md) | CORS standardisation (env-var allowlist, no wildcard) |
| [ADR-019](adr/ADR-019-rag-tag-filtering.md) | RAG tag-based filtering for context retrieval |
| [ADR-020](adr/ADR-020-tag-llm-tuning.md) | Tag LLM tuning (qwen3:8b, temperature 0.0, thinking disabled) |
| [ADR-021](adr/ADR-021-best-practice-flow.md) | Best-practice flow and HITL approval loop |
| [ADR-022](adr/ADR-022-nginx-gateway.md) | Nginx gateway — single port 8080, reverse proxy |

### Document Lifecycle & KB (ADR-023 – ADR-030)

| ADR | Decision |
|---|---|
| [ADR-023](adr/ADR-023-document-lifecycle-staged-promotion.md) | Staged document promotion: HITL → MongoDB → explicit promote → ChromaDB |
| [ADR-024](adr/ADR-024-kb-url-links.md) | KB URL links: live content fetch at generation time |
| [ADR-025](adr/ADR-025-project-metadata-upload-modal.md) | Project metadata upload modal |
| [ADR-026](adr/ADR-026-backend-decomposition-r15.md) | Backend decomposition R15: modular routers / services / state |
| [ADR-027](adr/ADR-027-bm25-hybrid-retrieval.md) | BM25Plus + ChromaDB hybrid retrieval ensemble |
| [ADR-028](adr/ADR-028-multi-query-expansion.md) | Multi-query expansion 2+2 (template + LLM variants) |
| [ADR-029](adr/ADR-029-context-assembler.md) | ContextAssembler: unified context fusion with token budget |
| [ADR-030](adr/ADR-030-semantic-chunking-langchain.md) | Semantic chunking with LangChain RecursiveCharacterTextSplitter |

### Quality, UI & Advanced RAG (ADR-031 – ADR-040)

| ADR | Decision |
|---|---|
| [ADR-031](adr/ADR-031-output-quality-checker.md) | LLM output quality checker and quality gate |
| [ADR-032](adr/ADR-032-feedback-loop-regenerate.md) | Feedback loop: reject → regenerate with feedback |
| [ADR-033](adr/ADR-033-tanstack-query-frontend.md) | TanStack Query for frontend state management |
| [ADR-034](adr/ADR-034-docling-vision-parser.md) | Docling + LLaVA/Granite vision parser for PDFs |
| [ADR-035](adr/ADR-035-raptor-lite-summaries.md) | RAPTOR-lite section summaries stored in ChromaDB |
| [ADR-036](adr/ADR-036-ingestion-platform-architecture.md) | Ingestion platform architecture (port 4006, multi-source collectors) |
| [ADR-037](adr/ADR-037-claude-api-semantic-extraction.md) | Claude API semantic extraction for HTML ingestion |
| [ADR-038](adr/ADR-038-technical-design-generation.md) | Two-phase functional→technical doc generation (superseded — merged into single Integration Spec) |
| [ADR-039](adr/ADR-039-ingestion-sources-ui.md) | Ingestion sources UI (source management, run history) |
| [ADR-040](adr/ADR-040-ai-assisted-section-improvement.md) | AI-assisted section improvement (build + run improvement prompt) |

### Agent Intelligence (ADR-041 – ADR-056)

| ADR | Decision |
|---|---|
| [ADR-041](adr/ADR-041-fact-pack-intermediate-layer.md) | Fact-pack intermediate layer: structured JSON extraction before generation |
| [ADR-042](adr/ADR-042-prompt-builder-centralization.md) | Prompt builder centralisation v2 |
| [ADR-043](adr/ADR-043-intent-aware-retrieval.md) | Intent-aware retrieval: source/target/category signals |
| [ADR-044](adr/ADR-044-kb-semantic-enrichment.md) | KB semantic enrichment at upload time |
| [ADR-045](adr/ADR-045-ui-semantic-chunking.md) | UI semantic chunking controls |
| [ADR-046](adr/ADR-046-llm-profile-routing.md) | LLM profile routing: default / high_quality / premium |
| [ADR-047](adr/ADR-047-pixel-ui-mode.md) | Pixel UI mode (retro aesthetic toggle) |
| [ADR-048](adr/ADR-048-kb-metadata-v2-enrichment.md) | KB metadata v2 enrichment |
| [ADR-049](adr/ADR-049-gemini-provider.md) | Gemini API provider as cloud LLM alternative |
| [ADR-050](adr/ADR-050-multi-client-requirements-persistence.md) | Multi-client requirements persistence (per-project isolation) |
| [ADR-051](adr/ADR-051-kb-export-import.md) | KB export / import (bundle format with ChromaDB + MongoDB) |
| [ADR-052](adr/ADR-052-llm-wiki-graph-rag.md) | LLM Wiki and Graph RAG: entity graph traversal in retrieval |
| [ADR-053](adr/ADR-053-parser-vlm-upgrade.md) | VLM upgrade: Granite-Vision-3.2-2B replaces LLaVA as primary |
| [ADR-054](adr/ADR-054-embedder-nomic.md) | Embedder upgrade to nomic-embed-text:v1.5 with task prefixes |
| [ADR-055](adr/ADR-055-reranker-rrf.md) | Cross-encoder reranker + Reciprocal Rank Fusion replacing TF-IDF |
| [ADR-056](adr/ADR-056-contextual-retrieval.md) | Contextual retrieval: situating annotations per chunk before embedding |

---

## Test & Quality Checklists

| Document | Purpose |
|---|---|
| [test-plan/TEST-PLAN-000-template.md](test-plan/TEST-PLAN-000-template.md) | Template for test plans |
| [test-plan/TEST-PLAN-001-remediation.md](test-plan/TEST-PLAN-001-remediation.md) | Test plan v2.0 — security remediation (314 unit tests) |
| [unit-test-review/UNIT-TEST-REVIEW-CHECKLIST.md](unit-test-review/UNIT-TEST-REVIEW-CHECKLIST.md) | Unit test review checklist (mandatory per CLAUDE.md §7.3) |
| [code-review/CODE-REVIEW-CHECKLIST.md](code-review/CODE-REVIEW-CHECKLIST.md) | Code review checklist |
| [security-review/SECURITY-REVIEW-CHECKLIST.md](security-review/SECURITY-REVIEW-CHECKLIST.md) | Security review checklist (OWASP-aligned) |
| [mappings/UNIT-SECURITY-OWASP-MAPPING.md](mappings/UNIT-SECURITY-OWASP-MAPPING.md) | Traceability: unit tests → security findings → OWASP Top 10 |

---

## Compliance & Governance

| Document | Purpose |
|---|---|
| [why-compliant/WHY-COMPLIANT.md](why-compliant/WHY-COMPLIANT.md) | How the project meets Accenture AI governance requirements |
| [runbooks/RUNBOOK-000-template.md](runbooks/RUNBOOK-000-template.md) | Template for operational runbooks |

---

## Implementation Plans

> `docs/plans/` — design and implementation plans by date.

| Date | Plan |
|---|---|
| 2026-03-12 | [Structured agent logs — design](plans/2026-03-12-structured-agent-logs-design.md) / [impl](plans/2026-03-12-structured-agent-logs-impl.md) |
| 2026-03-13 | [RAG tag filtering — design](plans/2026-03-13-rag-tag-filtering-design.md) / [plan](plans/2026-03-13-rag-tag-filtering-plan.md) |
| 2026-03-16 | [Tag LLM tuning](plans/2026-03-16-tag-llm-tuning-plan.md) / [LLM settings + KB nav update](plans/2026-03-16-llm-settings-kb-nav-docs-update.md) / [Project docs page](plans/2026-03-16-project-docs-page-plan.md) |
| 2026-03-17 | [Nginx gateway](plans/2026-03-17-nginx-gateway.md) |
| 2026-03-18 | [KB unified document list](plans/2026-03-18-kb-unified-document-list.md) |
| 2026-03-19 | [Project metadata upload modal](plans/2026-03-19-project-metadata-upload-modal.md) |
| 2026-03-20 | [Phase 2 RAG quality](plans/2026-03-20-phase2-rag-quality-plan.md) / [Phase 3 generation quality](plans/2026-03-20-phase3-generation-quality.md) |
| 2026-03-21 | [Phase 4 polish](plans/2026-03-21-phase4-polish.md) |
| 2026-03-23 | [Advanced RAG — Docling + RAPTOR design](plans/2026-03-23-advanced-rag-docling-raptor-design.md) |
| 2026-03-30 | [Technical design generation](plans/2026-03-30-technical-design-generation.md) |
| 2026-04-16 | [LLM profiles](plans/2026-04-16-llm-profiles.md) / [Pixel UI mode](plans/2026-04-16-pixel-ui-mode.md) / [UI semantic chunking](plans/2026-04-16-ui-semantic-chunking.md) |
| 2026-04-30 | [RAG pipeline modernisation — design](plans/2026-04-30-rag-pipeline-modernization-design.md) / [plan](plans/2026-04-30-rag-pipeline-modernization-plan.md) |

---

## Archive

| Document | Notes |
|---|---|
| [architecture-specification-old.md](architecture-specification-old.md) | Previous architecture spec (superseded by `architecture_specification.md`) |
