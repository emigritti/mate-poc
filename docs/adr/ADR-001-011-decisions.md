# Architecture Decisions — Functional Integration Mate PoC (v3)

## ADR-001: Monorepo con Microservizi Dockerizzati
Monorepo con 11 container Docker orchestrati da Docker Compose.

---

## ADR-002: Stack Tecnologico — Python / FastAPI
Python 3.12 + FastAPI per tutti i servizi. OpenAPI auto-generata, async nativo, Pydantic validation.

---

## ADR-003: Dual Database — MongoDB + PostgreSQL
MongoDB per catalogo integrazioni (schema flessibile), PostgreSQL per audit/policy (integrità referenziale).

---

## ADR-004: Security — JWT + API Gateway Pattern
FastAPI middleware con python-jose (JWT), slowapi (rate limit), policy engine, audit su PostgreSQL.

---

## ADR-005: Mock-First API Design
PLM, PIM e DAM espongono API mockate con OpenAPI auto-generata da FastAPI + Swagger UI.

---

## ADR-006: Document Generation via LLM (Ollama)
Documenti funzionali e tecnici generati da LLM locale (Ollama) con prompt engineering strutturato. Fallback a template base se LLM non disponibile.

---

## ADR-007: Containerizzazione — 11 Container
Immagini python:3.12-slim per i servizi, nginx:alpine per dashboard, immagini ufficiali per DB e infra.

---

## ADR-008: DAM Mock — Adobe AEM Assets-inspired
API strutturate: assets, folders, renditions, metadata, collections. Renditions generate via Pillow.

---

## ADR-009: PIM Mock — Akeneo/Salsify-inspired
Modello dati: families, attributes, categories, channels. API RESTful Akeneo-style.

---

## ADR-010: Requisiti Non-Funzionali nel Catalogo
Sample data con mix funzionali + NFR (CDN, security, RBAC, SLA, GDPR, encryption).

---

## ADR-011: Object Storage — MinIO S3

**Contesto**: Le integrazioni tra PLM, PIM e DAM devono trasferire asset binari (immagini, PDF, video). Il trasferimento diretto via API REST è inefficiente per file grandi e non scala.

**Decisione**: MinIO come object storage S3-compatible on-premise.

**Strategia bucket**:

| Bucket | Sistema | Contenuto |
|---|---|---|
| `plm-assets` | PLM | Immagini prodotto, documenti tecnici |
| `pim-media` | PIM | Media per il catalogo (importati) |
| `dam-originals` | DAM | File originali high-res |
| `dam-renditions` | DAM | Renditions generate (thumb, web, print) |

**Pattern di trasferimento**:
```
PLM → (upload) → plm-assets → (integration engine copy) → dam-originals
DAM → (rendition) → dam-renditions → (integration engine copy) → pim-media
```

**Motivazione**:
- **S3-compatible**: stesso SDK (boto3) usato in produzione con AWS S3
- **Presigned URLs**: download sicuro senza esporre credenziali
- **On-premise**: nessun dato esce dall'infrastruttura nel PoC
- **Console web**: MinIO Console (:9001) per monitoraggio visuale
- **Scalabile**: in produzione basta cambiare endpoint e credenziali per AWS/GCP/Azure
