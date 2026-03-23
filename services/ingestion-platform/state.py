"""
Ingestion Platform — In-Memory State

Holds references to MongoDB collections (set during app lifespan).
Mutable at module level so tests can replace them with AsyncMock instances.
"""
from motor.motor_asyncio import AsyncIOMotorCollection
from typing import Optional

# MongoDB collections — populated in main.py lifespan
sources_col: Optional[AsyncIOMotorCollection] = None
runs_col: Optional[AsyncIOMotorCollection] = None
snapshots_col: Optional[AsyncIOMotorCollection] = None
