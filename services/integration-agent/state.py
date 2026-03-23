"""
Shared In-Memory State — centralized application state.

Extracted from main.py (R15).
All in-memory data structures that were module-level globals in main.py
are now consolidated here, imported by routers and services.

Write-through to MongoDB is handled by the callers (routers).
"""

import asyncio

from schemas import (
    Approval,
    CatalogEntry,
    Document,
    KBDocument,
    LogEntry,
    Project,
    Requirement,
)

# ── In-memory state (write-through to MongoDB) ────────────────────────────────
parsed_requirements: list[Requirement] = []
catalog:   dict[str, CatalogEntry] = {}
documents: dict[str, Document]     = {}
approvals: dict[str, Approval]     = {}
agent_logs: list[LogEntry]         = []
kb_docs:   dict[str, KBDocument]   = {}
projects:  dict[str, Project]      = {}

# ── BM25 chunk corpus (in-memory, populated from ChromaDB at startup) ─────────
# key: doc_id (matches kb_docs key), value: list of chunk texts
kb_chunks: dict[str, list[str]] = {}

# ── Agent progress tracking (R18) ─────────────────────────────────────────────
# Reset to {} at the start of each run; updated throughout run_agentic_rag_flow.
# Keys: descriptive step key (e.g. "overall")
# Value: { "step": str, "done": int, "total": int }
agent_progress: dict = {}

# ── Task registry — prevents concurrent agent runs (F-09) ─────────────────────
agent_lock = asyncio.Lock()
running_tasks: dict[str, asyncio.Task] = {}

# ── ChromaDB — initialized with retry in lifespan ─────────────────────────────
chroma_client  = None
collection     = None
kb_collection  = None
summaries_col  = None  # RAPTOR-lite summaries collection (ADR-032)
