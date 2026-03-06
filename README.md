# Functional Integration Mate — PoC

> AI-powered platform for automating enterprise integration analysis, cataloging, and documentation.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Web Dashboard (:8080)                     │
├─────────────────────────────────────────────────────────────┤
│               Security Middleware (:3000)                    │
│           JWT · RBAC · Rate Limiting · Audit                │
├──────────────┬──────────────────────┬───────────────────────┤
│  Integration │  Catalog Generator   │      Mock APIs        │
│  Engine      │  (:3004)             │                       │
│  (:3003)     │  CSV → Catalog → LLM │  PLM (:3001)         │
│              │                      │  PIM (:3002)         │
│  Agent Loop  │  Req Parser          │  DAM (:3005)         │
│  Transformer │  OpenAPI Parser      │                       │
│  S3 Transfer │  LLM Generator       │  S3 upload/download   │
├──────────────┴──────────────────────┴───────────────────────┤
│  MongoDB (:27017)  │  PostgreSQL (:5432)  │  MinIO (:9000)  │
│  Catalog + Docs    │  Audit + Thoughts    │  Assets (4 bkt) │
├────────────────────┴──────────────────────┴─────────────────┤
│                     Ollama (:11434)                          │
│                    LLM Local Inference                      │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Start all 11 services
docker-compose up --build

# 2. Wait for all health checks, then open:
#    Dashboard:   http://localhost:8080
#    PLM Swagger: http://localhost:3001/docs
#    PIM Swagger: http://localhost:3002/docs
#    DAM Swagger: http://localhost:3005/docs
#    MinIO:       http://localhost:9001 (minioadmin/minioadmin)
#    Gateway:     http://localhost:3000/docs

# 3. Get a JWT token:
curl -X POST "http://localhost:3000/auth/token?username=admin"

# 4. Execute an agentic integration:
curl -X POST "http://localhost:3003/api/v1/execute" \
  -H "Content-Type: application/json" \
  -d '{"goal": "Sync all PUBLISHED products from PLM to PIM"}'

# 5. Upload requirements & generate catalog:
curl -X POST "http://localhost:3004/api/v1/catalog/generate" \
  -F "file=@data/sample-requirements.csv"
```

## Services

| Service | Port | Description |
|---|---|---|
| Security Middleware | 3000 | API Gateway, JWT, RBAC, rate limiting, audit |
| PLM Mock | 3001 | Product Lifecycle Management API |
| PIM Mock | 3002 | Akeneo-style Product Information API |
| Integration Engine | 3003 | Agentic orchestrator (PLAN→EXECUTE→SYNTHESIZE) |
| Catalog Generator | 3004 | CSV → catalog → LLM-generated documents |
| DAM Mock | 3005 | Adobe AEM-style Digital Asset Management |
| Web Dashboard | 8080 | SPA with catalog, executions, thoughts, approvals |
| MongoDB | 27017 | Catalog and document storage |
| PostgreSQL | 5432 | Audit logs, agent thoughts, HITL approvals |
| MinIO | 9000/9001 | S3-compatible object storage (4 buckets) |
| Ollama | 11434 | Local LLM inference (llama3.1:8b) |

## Tech Stack

- **Backend:** Python 3.12 + FastAPI + Pydantic v2
- **Frontend:** Vanilla HTML/CSS/JS SPA
- **Data:** MongoDB + PostgreSQL + MinIO S3
- **AI:** Ollama (llama3.1:8b) with template fallback
- **Security:** JWT + RBAC + slowapi rate limiting
- **Containers:** Docker Compose (11 services)

## Project Structure

```
├── .env                      # Environment configuration
├── docker-compose.yml        # 11-service orchestration
├── data/
│   └── sample-requirements.csv
├── scripts/
│   ├── init-db.sql           # PostgreSQL schema (5 tables)
│   └── init-s3.sh            # MinIO bucket creation
└── services/
    ├── plm-mock-api/         # PLM Mock (:3001)
    ├── pim-mock-api/         # PIM Mock (:3002)
    ├── dam-mock-api/         # DAM Mock (:3005)
    ├── security-middleware/   # Gateway (:3000)
    ├── integration-engine/   # Agent Engine (:3003)
    ├── catalog-generator/    # Catalog + LLM (:3004)
    └── web-dashboard/        # SPA (:8080)
```
