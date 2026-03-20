"""
Logging Helpers — structured agent logging and log pruning.

Extracted from main.py (R15).
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from config import settings
from schemas import LogEntry, LogLevel
import state

logger = logging.getLogger(__name__)


def _detect_level(msg: str) -> LogLevel:
    """Infer LogLevel from message prefix/content (single responsibility)."""
    if "[LLM]"    in msg: return LogLevel.LLM
    if "[RAG]"    in msg: return LogLevel.RAG
    if "[KB-RAG]" in msg: return LogLevel.RAG
    if "[ERROR]"  in msg: return LogLevel.ERROR
    if "[GUARD]"  in msg: return LogLevel.WARN
    if "⛔"       in msg or "cancelled" in msg: return LogLevel.CANCEL
    if "completed" in msg or "Approved" in msg or "✓" in msg: return LogLevel.SUCCESS
    return LogLevel.INFO


# Regex pattern to strip leading bracket prefix from stored messages.
_LOG_PREFIX_RE = re.compile(r"^\[(?:[A-Z][A-Z0-9\-]*(?:\s+\d+/\d+)?)\]\s*")


def log_agent(msg: str) -> None:
    """Append a structured LogEntry and emit as INFO log.

    The stored message strips the leading bracket prefix (e.g. '[ERROR] ')
    since `level` is the structured field. The Python logger still receives
    the full original message for traceability.
    """
    level = _detect_level(msg)
    clean_msg = _LOG_PREFIX_RE.sub("", msg, count=1)
    entry = LogEntry(
        ts=datetime.now(timezone.utc),
        level=level,
        message=clean_msg,
    )
    state.agent_logs.append(entry)
    logger.info("[%s] %s", level, msg)


def prune_logs() -> None:
    """Remove LogEntry objects older than settings.log_ttl_hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.log_ttl_hours)
    state.agent_logs[:] = [e for e in state.agent_logs if e.ts > cutoff]
