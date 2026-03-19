"""
Integration Agent — MongoDB Persistence Layer
ADR-013: motor async driver, write-through cache pattern.

Collections:
  catalog_entries  — CatalogEntry documents
  approvals        — Approval documents (status: PENDING / APPROVED / REJECTED)
  documents        — Final approved Document records (also stored in ChromaDB)

Indexes ensure fast lookup by 'id' and allow filtering approvals by status.
Collections are exposed as module-level vars so main.py can import them
directly: `if db.catalog_col is not None: await db.catalog_col.replace_one(...)`

If MongoDB is unavailable after all retries, collections remain None and the
app continues in degraded mode (in-memory only, no persistence across restarts).
"""

import asyncio
import logging

import motor.motor_asyncio

from config import settings

logger = logging.getLogger(__name__)

# ── Module-level state ────────────────────────────────────────────────────────
_client: motor.motor_asyncio.AsyncIOMotorClient | None = None
_db: motor.motor_asyncio.AsyncIOMotorDatabase | None = None

catalog_col:      motor.motor_asyncio.AsyncIOMotorCollection | None = None
approvals_col:    motor.motor_asyncio.AsyncIOMotorCollection | None = None
documents_col:    motor.motor_asyncio.AsyncIOMotorCollection | None = None
kb_documents_col: motor.motor_asyncio.AsyncIOMotorCollection | None = None
llm_settings_col: motor.motor_asyncio.AsyncIOMotorCollection | None = None
projects_col:     motor.motor_asyncio.AsyncIOMotorCollection | None = None


async def init_db(retries: int = 20, delay: float = 3.0) -> None:
    """
    Connect to MongoDB and initialise collections + indexes.

    Retries up to `retries` times with `delay` seconds between attempts.
    On failure, collections remain None (degraded mode — no crash).
    """
    global _client, _db, catalog_col, approvals_col, documents_col, kb_documents_col, llm_settings_col, projects_col

    for attempt in range(1, retries + 1):
        try:
            _client = motor.motor_asyncio.AsyncIOMotorClient(
                settings.mongo_uri,
                serverSelectionTimeoutMS=10_000,  # 10 s per attempt
            )
            _db = _client[settings.mongo_db]

            # Ping to verify the connection is alive
            await _db.command("ping")

            catalog_col      = _db["catalog_entries"]
            approvals_col    = _db["approvals"]
            documents_col    = _db["documents"]
            kb_documents_col = _db["kb_documents"]
            llm_settings_col = _db["llm_settings"]
            projects_col     = _db["projects"]

            # Idempotent index creation
            await catalog_col.create_index("id", unique=True)
            await approvals_col.create_index("id", unique=True)
            await approvals_col.create_index("status")
            await documents_col.create_index("id", unique=True)
            await kb_documents_col.create_index("id", unique=True)
            await kb_documents_col.create_index("tags")
            await projects_col.create_index("prefix", unique=True)

            logger.info("[DB] MongoDB connected (attempt %d/%d).", attempt, retries)
            return

        except Exception as exc:
            logger.warning("[DB] Attempt %d/%d failed: %s", attempt, retries, exc)
            if attempt < retries:
                await asyncio.sleep(delay)

    logger.warning(
        "[DB] MongoDB unavailable after %d attempts — persistence disabled.", retries
    )


async def close_db() -> None:
    """Close the motor client on app shutdown."""
    global _client
    if _client is not None:
        _client.close()
        logger.info("[DB] MongoDB connection closed.")
        _client = None
