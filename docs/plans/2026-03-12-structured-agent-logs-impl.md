# Structured Agent Logs Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace `agent_logs: list[str]` with `list[LogEntry]` carrying explicit `LogLevel`, structured timestamp, and TTL pruning; update frontend to color by level.

**Architecture:** New `LogLevel` enum + `LogEntry` Pydantic model in `schemas.py`. `log_agent()` auto-detects level via `_detect_level()`. A background asyncio task prunes entries older than `LOG_TTL_HOURS` (default 4h) every 30 min. Frontend receives `{ts, level, message}` objects and maps level → color constant.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, asyncio, vanilla JS

---

## Task 1: Add LogLevel + LogEntry to schemas.py

**Files:**
- Modify: `services/integration-agent/schemas.py`
- Test: `services/integration-agent/tests/test_log_schemas.py` (new file)

**Step 1: Write the failing test**

Create `services/integration-agent/tests/test_log_schemas.py`:

```python
"""Unit tests — LogLevel enum and LogEntry schema."""
from datetime import datetime, timezone
import pytest
from schemas import LogLevel, LogEntry


class TestLogLevel:
    def test_all_expected_levels_exist(self):
        expected = {"INFO", "LLM", "RAG", "SUCCESS", "WARN", "ERROR", "CANCEL"}
        assert {l.value for l in LogLevel} == expected

    def test_log_level_is_str(self):
        assert isinstance(LogLevel.INFO, str)
        assert LogLevel.LLM == "LLM"


class TestLogEntry:
    def test_log_entry_creation(self):
        entry = LogEntry(
            ts=datetime.now(timezone.utc),
            level=LogLevel.INFO,
            message="Test message",
        )
        assert entry.level == LogLevel.INFO
        assert entry.message == "Test message"
        assert entry.ts.tzinfo is not None  # must be UTC-aware

    def test_log_entry_model_dump_contains_expected_keys(self):
        entry = LogEntry(
            ts=datetime.now(timezone.utc),
            level=LogLevel.LLM,
            message="LLM call",
        )
        d = entry.model_dump()
        assert set(d.keys()) == {"ts", "level", "message"}
```

**Step 2: Run test to verify it fails**

```bash
cd services/integration-agent
python -m pytest tests/test_log_schemas.py -v
```
Expected: `ImportError: cannot import name 'LogLevel' from 'schemas'`

**Step 3: Add LogLevel and LogEntry to schemas.py**

Add at the top of `services/integration-agent/schemas.py`, after the existing imports:

```python
from datetime import datetime
from enum import Enum
```

Add before the existing `Requirement` class:

```python
class LogLevel(str, Enum):
    INFO    = "INFO"
    LLM     = "LLM"
    RAG     = "RAG"
    SUCCESS = "SUCCESS"
    WARN    = "WARN"
    ERROR   = "ERROR"
    CANCEL  = "CANCEL"


class LogEntry(BaseModel):
    ts:      datetime
    level:   LogLevel
    message: str
```

**Step 4: Run test to verify it passes**

```bash
cd services/integration-agent
python -m pytest tests/test_log_schemas.py -v
```
Expected: 5 PASSED

**Step 5: Commit**

```bash
git add services/integration-agent/schemas.py \
        services/integration-agent/tests/test_log_schemas.py
git commit -m "feat(logs): add LogLevel enum and LogEntry schema"
```

---

## Task 2: Add log_ttl_hours to config.py

**Files:**
- Modify: `services/integration-agent/config.py`
- Test: `services/integration-agent/tests/test_config.py` (existing — add one test)

**Step 1: Write the failing test**

Add to the end of `services/integration-agent/tests/test_config.py`:

```python
def test_log_ttl_hours_default():
    """LOG_TTL_HOURS defaults to 4 when not set."""
    from config import Settings
    s = Settings()
    assert s.log_ttl_hours == 4

def test_log_ttl_hours_env_override(monkeypatch):
    """LOG_TTL_HOURS can be overridden via environment variable."""
    monkeypatch.setenv("LOG_TTL_HOURS", "8")
    from config import Settings
    s = Settings()
    assert s.log_ttl_hours == 8
```

**Step 2: Run test to verify it fails**

```bash
cd services/integration-agent
python -m pytest tests/test_config.py::test_log_ttl_hours_default -v
```
Expected: `AttributeError: 'Settings' object has no attribute 'log_ttl_hours'`

**Step 3: Add field to config.py**

In `services/integration-agent/config.py`, add after `cors_origins`:

```python
# ── Log TTL ──────────────────────────────────────────────────────────
log_ttl_hours: int = 4   # env: LOG_TTL_HOURS — prune entries older than N hours
```

**Step 4: Run all config tests**

```bash
cd services/integration-agent
python -m pytest tests/test_config.py -v
```
Expected: all PASSED (existing 5 + new 2 = 7)

**Step 5: Commit**

```bash
git add services/integration-agent/config.py \
        services/integration-agent/tests/test_config.py
git commit -m "feat(logs): add log_ttl_hours config field (default 4h)"
```

---

## Task 3: Add _detect_level() and rewrite log_agent()

**Files:**
- Modify: `services/integration-agent/main.py`
- Test: `services/integration-agent/tests/test_log_agent.py` (new file)

**Step 1: Write the failing tests**

Create `services/integration-agent/tests/test_log_agent.py`:

```python
"""Unit tests — _detect_level() and log_agent()."""
import os
os.environ.setdefault("OLLAMA_HOST",  "http://fake-ollama:11434")
os.environ.setdefault("MONGO_URI",    "mongodb://fake-mongo:27017")
os.environ.setdefault("CHROMA_HOST",  "fake-chroma")

from main import _detect_level
from schemas import LogLevel


class TestDetectLevel:
    def test_llm_prefix(self):
        assert _detect_level("[LLM] Calling model") == LogLevel.LLM

    def test_rag_prefix(self):
        assert _detect_level("[RAG] Querying ChromaDB") == LogLevel.RAG

    def test_error_prefix(self):
        assert _detect_level("[ERROR] Connection failed") == LogLevel.ERROR

    def test_guard_prefix(self):
        assert _detect_level("[GUARD] Output rejected") == LogLevel.WARN

    def test_cancel_stop_symbol(self):
        assert _detect_level("⛔ Agent execution cancelled") == LogLevel.CANCEL

    def test_cancel_keyword(self):
        assert _detect_level("Task cancelled by user") == LogLevel.CANCEL

    def test_success_completed(self):
        assert _detect_level("Generation completed. Pending documents...") == LogLevel.SUCCESS

    def test_success_approved(self):
        assert _detect_level("Approved and saved to RAG.") == LogLevel.SUCCESS

    def test_default_info(self):
        assert _detect_level("Started Agent Processing Task") == LogLevel.INFO

    def test_case_sensitivity(self):
        # [llm] lowercase should NOT match — prefixes are uppercase in log_agent calls
        assert _detect_level("[llm] something") == LogLevel.INFO
```

**Step 2: Run test to verify it fails**

```bash
cd services/integration-agent
python -m pytest tests/test_log_agent.py -v
```
Expected: `ImportError: cannot import name '_detect_level' from 'main'`

**Step 3: Add _detect_level() and rewrite log_agent() in main.py**

In `services/integration-agent/main.py`:

a) Update imports at top — add to existing `from schemas import (...)`:
```python
from schemas import (
    Approval,
    ApproveRequest,
    CatalogEntry,
    Document,
    LogEntry,       # add
    LogLevel,       # add
    Requirement,
    RejectRequest,
)
```

b) Change `agent_logs` declaration (line ~64):
```python
# Before:
agent_logs: list[str] = []

# After:
agent_logs: list[LogEntry] = []
```

c) Replace `log_agent()` function and add `_detect_level()` before it:

```python
def _detect_level(msg: str) -> LogLevel:
    """Infer LogLevel from message prefix/content (single responsibility)."""
    if "[LLM]"   in msg: return LogLevel.LLM
    if "[RAG]"   in msg: return LogLevel.RAG
    if "[ERROR]" in msg: return LogLevel.ERROR
    if "[GUARD]" in msg: return LogLevel.WARN
    if "⛔"      in msg or "cancelled" in msg: return LogLevel.CANCEL
    if "completed" in msg or "Approved" in msg or "✓" in msg: return LogLevel.SUCCESS
    return LogLevel.INFO


def log_agent(msg: str) -> None:
    """Append a structured LogEntry and emit as INFO log."""
    entry = LogEntry(
        ts=datetime.now(timezone.utc),
        level=_detect_level(msg),
        message=msg,
    )
    agent_logs.append(entry)
    logger.info("[%s] %s", entry.level, msg)
```

**Step 4: Run tests**

```bash
cd services/integration-agent
python -m pytest tests/test_log_agent.py -v
```
Expected: 10 PASSED

Run full suite to check regressions:
```bash
python -m pytest tests/ -v
```
Expected: all existing tests still PASS (log_agent signature unchanged).

**Step 5: Commit**

```bash
git add services/integration-agent/main.py \
        services/integration-agent/tests/test_log_agent.py
git commit -m "feat(logs): add _detect_level() and structured log_agent()"
```

---

## Task 4: Add TTL prune background task

**Files:**
- Modify: `services/integration-agent/main.py`

**Step 1: Write the failing test**

Add to `services/integration-agent/tests/test_log_agent.py`:

```python
import asyncio
from datetime import timedelta
from unittest.mock import patch

def test_prune_removes_old_entries():
    """_prune_logs() must remove LogEntry objects older than ttl_hours."""
    import main as agent_main
    from schemas import LogEntry, LogLevel

    old_ts = datetime.now(timezone.utc) - timedelta(hours=5)
    new_ts = datetime.now(timezone.utc)

    old_entry = LogEntry(ts=old_ts, level=LogLevel.INFO, message="old")
    new_entry = LogEntry(ts=new_ts, level=LogLevel.INFO, message="new")

    agent_main.agent_logs[:] = [old_entry, new_entry]

    # Patch settings to use 4h TTL
    with patch.object(agent_main.settings, "log_ttl_hours", 4):
        agent_main._prune_logs()

    assert len(agent_main.agent_logs) == 1
    assert agent_main.agent_logs[0].message == "new"
```

**Step 2: Run test to verify it fails**

```bash
cd services/integration-agent
python -m pytest tests/test_log_agent.py::test_prune_removes_old_entries -v
```
Expected: `AttributeError: module 'main' has no attribute '_prune_logs'`

**Step 3: Add _prune_logs() and async background task to main.py**

Add after `log_agent()`:

```python
def _prune_logs() -> None:
    """Remove LogEntry objects older than settings.log_ttl_hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.log_ttl_hours)
    agent_logs[:] = [e for e in agent_logs if e.ts > cutoff]


async def _prune_logs_loop() -> None:
    """Background task: prune agent_logs every 30 minutes."""
    while True:
        await asyncio.sleep(1800)
        _prune_logs()
        logger.debug("[Logs] TTL prune complete. Entries remaining: %d", len(agent_logs))
```

Add `timedelta` to the existing `from datetime import datetime, timezone` import:
```python
from datetime import datetime, timedelta, timezone
```

Update the `lifespan` context manager to start the prune task:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await _init_chromadb()
    await db.init_db()

    # seed in-memory cache from MongoDB ...
    # (existing seeding code unchanged)

    prune_task = asyncio.create_task(_prune_logs_loop(), name="log-pruner")

    yield

    prune_task.cancel()
    await db.close_db()
```

**Step 4: Run tests**

```bash
cd services/integration-agent
python -m pytest tests/test_log_agent.py -v
```
Expected: all PASSED

```bash
python -m pytest tests/ -v
```
Expected: all 50+ tests PASSED

**Step 5: Commit**

```bash
git add services/integration-agent/main.py
git commit -m "feat(logs): add TTL prune task (default 4h, runs every 30min)"
```

---

## Task 5: Update /api/v1/agent/logs endpoint response

**Files:**
- Modify: `services/integration-agent/main.py`

**Step 1: Write the failing test**

Add to `services/integration-agent/tests/test_log_agent.py`
(needs the `client` fixture — import from conftest or add inline):

```python
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

@pytest.fixture(scope="module")
def logs_client():
    with (
        patch("db.init_db",          new_callable=AsyncMock),
        patch("db.close_db",         new_callable=AsyncMock),
        patch("main._init_chromadb", new_callable=AsyncMock),
        patch("main._prune_logs_loop", new_callable=AsyncMock),
    ):
        from main import app
        with TestClient(app) as c:
            yield c


def test_logs_endpoint_returns_structured_entries(logs_client):
    """GET /api/v1/agent/logs must return list of {ts, level, message} dicts."""
    import main as agent_main

    agent_main.agent_logs[:] = [
        LogEntry(ts=datetime.now(timezone.utc), level=LogLevel.LLM, message="LLM call"),
        LogEntry(ts=datetime.now(timezone.utc), level=LogLevel.ERROR, message="Oops"),
    ]
    try:
        response = logs_client.get("/api/v1/agent/logs")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        logs = data["logs"]
        assert len(logs) == 2
        assert logs[0]["level"] == "LLM"
        assert logs[1]["level"] == "ERROR"
        assert "ts" in logs[0]
        assert "message" in logs[0]
    finally:
        agent_main.agent_logs.clear()
```

**Step 2: Run test to verify it fails**

```bash
cd services/integration-agent
python -m pytest tests/test_log_agent.py::test_logs_endpoint_returns_structured_entries -v
```
Expected: FAIL — response logs are strings, not dicts with `level` key.

**Step 3: Update GET /api/v1/agent/logs in main.py**

```python
# Before:
@app.get("/api/v1/agent/logs", tags=["agent"])
async def get_logs() -> dict:
    return {"status": "success", "logs": agent_logs[-50:]}

# After:
@app.get("/api/v1/agent/logs", tags=["agent"])
async def get_logs() -> dict:
    return {
        "status": "success",
        "logs": [e.model_dump(mode="json") for e in agent_logs[-100:]],
    }
```

**Step 4: Run full test suite**

```bash
cd services/integration-agent
python -m pytest tests/ -v
```
Expected: all PASSED

**Step 5: Commit**

```bash
git add services/integration-agent/main.py \
        services/integration-agent/tests/test_log_agent.py
git commit -m "feat(logs): structured LogEntry response on /api/v1/agent/logs"
```

---

## Task 6: Update frontend _renderLogLines() and startAgentPolling()

**Files:**
- Modify: `services/web-dashboard/js/app.js`

No automated tests for vanilla JS — verify manually in browser after docker compose up.

**Step 1: Replace _renderLogLines() in app.js**

Find and replace the entire `_renderLogLines` function (lines ~194-206):

```javascript
/**
 * Render the visible slice of LogEntry objects into #agentLogs.
 * Colors are driven by the `level` field from the backend — no keyword scanning.
 * F-04: all values HTML-escaped (ADR-017 / OWASP A03).
 */
function _renderLogLines(logs) {
    const logsEl = document.getElementById('agentLogs');
    if (!logsEl || !logs || logs.length === 0) return;
    const COLORS = {
        INFO:    '#00ff00',
        LLM:     '#ffeb3b',
        RAG:     '#00bcd4',
        SUCCESS: '#69f0ae',
        WARN:    '#ff9800',
        ERROR:   '#f44336',
        CANCEL:  '#e65100',
    };
    logsEl.innerHTML = logs.map(e => {
        const color = COLORS[e.level] ?? '#00ff00';
        const ts    = new Date(e.ts).toLocaleTimeString();
        return `<div style="color:${color}">` +
            `<span style="opacity:0.5">[${escapeHtml(ts)}]</span> ` +
            `<span style="opacity:0.6;font-size:0.85em">[${escapeHtml(e.level)}]</span> ` +
            `${escapeHtml(e.message)}</div>`;
    }).join('');
    logsEl.scrollTop = logsEl.scrollHeight;
}
```

**Step 2: Update isDone check in startAgentPolling()**

Find the `isDone` block inside `startAgentPolling()` (~line 253-257):

```javascript
// Before:
const last = logs.at(-1) ?? '';
const isDone = last.includes('Generation completed')
    || last.includes('All tasks finished')
    || last.includes('cancelled');
if (logs.length > 0 && isDone) {

// After:
const isDone = logs.length > 0 && logs.some(e =>
    (e.level === 'SUCCESS' && e.message.includes('completed'))
    || e.level === 'CANCEL'
);
if (isDone) {
```

**Step 3: Rebuild and verify manually**

```bash
docker compose up -d --build web-dashboard integration-agent
```

Open `http://<host>:8080` → Agent Workspace → trigger agent.
Expected:
- LLM lines: yellow
- RAG lines: cyan
- ERROR lines: red
- CANCEL lines: dark orange
- SUCCESS lines: bright green
- Timestamp and level badge visible and dimmed

**Step 4: Commit**

```bash
git add services/web-dashboard/js/app.js
git commit -m "feat(logs): color-coded LogEntry rendering in dashboard terminal"
```

---

## Final Verification

```bash
cd services/integration-agent
python -m pytest tests/ -v --tb=short
```
Expected: all tests PASS.

Check log level distribution is visible in the dashboard after a full agent run.
