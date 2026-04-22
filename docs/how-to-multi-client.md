# How-To: Working with Multiple Clients (ADR-050)

> **Audience:** Analysts and developers using Integration Mate to manage integration documentation for more than one client in the same deployment.

---

## Overview

From ADR-050, the system supports a true multi-client workflow:

- A **global Project Selector** in the TopBar filters all pages by the active client.
- **Requirements are persisted to MongoDB** and survive container restarts.
- The **Agent trigger** is scoped to the active project, so generating docs for one client does not touch another client's entries.

The Knowledge Base remains **shared across all clients** — best-practice documents and API specs are available for every integration regardless of project.

---

## Step 1 — Create a Project (Client)

A project is created automatically the first time you upload requirements for a new client. You can also pre-create one manually:

**Via UI:**
1. Upload any requirements file.
2. The **Project Modal** opens automatically.
3. Fill in: Client Name, Domain, Prefix (auto-generated, max 3 chars), optional Description and Accenture Reference.
4. Click **Confirm** — the project is created and the TopBar selector switches to it.

**Via API:**
```http
POST /agent/api/v1/projects
Content-Type: application/json

{
  "prefix": "ACM",
  "client_name": "Acme Corp",
  "domain": "Fashion Retail – PLM/PIM",
  "description": "Integration requirements for Acme seasonal collection flow",
  "accenture_ref": "ACC-2026-0042"
}
```

---

## Step 2 — Switch Between Clients

Use the **TopBar project selector dropdown** (top-right of every page):

- **"All Projects"** — unfiltered view; shows every client's catalog entries and documents.
- **"{Client Name} ({PREFIX})"** — filters all pages to that client.

The selection is stored in `localStorage` and restored on browser refresh.

---

## Step 3 — Upload Requirements for a Client

1. Select the client in the TopBar (or let the Project Modal auto-select it after upload).
2. Go to **Requirements** and upload your CSV or Markdown file.
3. The file is parsed and **immediately persisted to MongoDB** (the upload session survives a container restart — you will not need to re-upload).
4. Complete the Project Modal to finalize — `POST /api/v1/requirements/finalize` creates CatalogEntries scoped to that client's prefix.

> **Tip:** If you restart the container before finalizing, the last unfinalized session is automatically restored into memory at startup.

---

## Step 4 — Generate Documents for a Specific Client

1. Select the target client in the TopBar.
2. Go to **Agent Workspace** and click **"Start Agent Processing"**.
3. The trigger sends `project_id` to the backend — only `TAG_CONFIRMED` entries for that client are processed.
4. The PENDING_TAG_REVIEW gate checks only the selected client's entries — pending tags in other clients do not block generation.

> **Without a project selected** (All Projects): the agent processes ALL `TAG_CONFIRMED` entries across all clients (backward-compatible behavior).

---

## Step 5 — View Results per Client

| Page | Behavior with project selected |
|------|-------------------------------|
| **Requirements** | Shows finalized requirements for the active client (`GET /api/v1/requirements?project_id={prefix}`) |
| **Integration Catalog** | Shows only that client's catalog entries (`GET /api/v1/catalog/integrations?project_id={prefix}`) |
| **Generated Docs** | Shows only that client's approved documents |
| **Agent Workspace** | Trigger scoped to active client |
| **Knowledge Base** | Always global — not filtered by client |
| **HITL Approvals** | Always global — reviews all pending approvals |

---

## Fetching Requirements for a Client (API)

After finalization, requirements are persisted with `project_id` and can be retrieved at any time:

```http
GET /agent/api/v1/requirements?project_id=ACM
```

Response:
```json
{
  "status": "success",
  "data": [
    {
      "req_id": "R-001",
      "source_system": "PLM",
      "target_system": "PIM",
      "category": "Product Master",
      "description": "Sync product master data including SKU and EAN codes daily",
      "mandatory": true,
      "upload_id": "a3f9b7c2...",
      "project_id": "ACM"
    }
  ]
}
```

---

## Multi-Client Workflow Summary

```
Client A (prefix: ACM)                    Client B (prefix: GFG)
─────────────────────                    ─────────────────────
1. Upload reqs → persisted (upload_id)   1. Upload reqs → persisted (upload_id)
2. Project Modal → finalize              2. Project Modal → finalize
   project_id="ACM" stamped                project_id="GFG" stamped
3. Confirm tags for ACM entries          3. Confirm tags for GFG entries
4. Select ACM in TopBar                  4. Select GFG in TopBar
5. Start Agent → processes ACM only     5. Start Agent → processes GFG only
6. HITL Approve → ACM docs promoted     6. HITL Approve → GFG docs promoted
```

Both clients share the same Knowledge Base and the same Ollama model.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Catalog shows entries from multiple clients | No project selected in TopBar | Select the specific client in the dropdown |
| Agent processes all clients | No project selected in TopBar | Select the client before triggering |
| Requirements gone after restart | Pre-ADR-050 behavior (server restart) | Upgrade to ADR-050 — requirements now auto-restored from MongoDB |
| Can't find a project in dropdown | Project was never created | Upload requirements and confirm the Project Modal |
| Prefix clash in Project Modal | Another client uses the same prefix | Change 1-3 chars in the Prefix field |

---

## Reference

- **ADR-050**: `docs/adr/ADR-050-multi-client-requirements-persistence.md`
- **ADR-025**: `docs/adr/ADR-025-project-metadata-upload-modal.md` — original project model
- **Backend**: `services/integration-agent/routers/requirements.py`, `routers/agent.py`
- **Frontend**: `services/web-dashboard/src/context/ProjectContext.jsx`, `components/layout/TopBar.jsx`
