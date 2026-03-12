# Design: Structured Agent Logs with TTL

**Date:** 2026-03-12
**Status:** Approved
**Scope:** Agent-flow logs only (not Python stdlib logging)

---

## Problem

`agent_logs` is a `list[str]` of raw timestamped strings. The frontend
detects log levels by keyword-matching on those strings, which is fragile
and tightly couples display logic to message wording. Logs accumulate
indefinitely in memory with no cleanup.

---

## Decision

Approach A: replace `list[str]` with `list[LogEntry]` — structured entries
carrying an explicit `LogLevel`, a UTC `datetime` for TTL, and the clean
message text. The frontend colors by `level` field, not by string scanning.

---

## Data Model (`schemas.py`)

```python
class LogLevel(str, Enum):
    INFO    = "INFO"      # normal flow
    LLM     = "LLM"       # Ollama calls
    RAG     = "RAG"       # ChromaDB queries
    SUCCESS = "SUCCESS"   # completion, approvals
    WARN    = "WARN"      # guard rejections
    ERROR   = "ERROR"     # failures
    CANCEL  = "CANCEL"    # agent stop

class LogEntry(BaseModel):
    ts:      datetime   # UTC — used for TTL pruning
    level:   LogLevel
    message: str        # clean text, no [HH:MM:SS] prefix
```

---

## Backend Changes (`main.py`, `config.py`)

### config.py
```python
log_ttl_hours: int = 4   # env: LOG_TTL_HOURS
```

### log_agent()
Creates a `LogEntry` instead of a string. Calls `_detect_level(msg)` to
map message prefixes to `LogLevel`:

| Prefix / pattern            | Level   |
|-----------------------------|---------|
| `[LLM]`                     | LLM     |
| `[RAG]`                     | RAG     |
| `[ERROR]`                   | ERROR   |
| `[GUARD]`                   | WARN    |
| `⛔` / `cancelled`          | CANCEL  |
| `✓` / `completed` / `Approved` | SUCCESS |
| everything else             | INFO    |

Python `logger.info()` call is preserved for stdout/Docker logs.

### TTL background task
Started in `lifespan`, runs every 30 minutes:
```python
async def _prune_logs_task():
    while True:
        await asyncio.sleep(1800)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.log_ttl_hours)
        agent_logs[:] = [e for e in agent_logs if e.ts > cutoff]
```

### GET /api/v1/agent/logs
Returns last 100 `LogEntry` objects (up from 50 strings):
```json
{"status": "success", "logs": [{"ts": "...", "level": "LLM", "message": "..."}]}
```

`reset_requirements` and `reset_all` continue to use `agent_logs = []`
unchanged.

---

## Frontend Changes (`app.js`)

### Color palette
| Level   | Color     | Hex       |
|---------|-----------|-----------|
| INFO    | terminal green | `#00ff00` |
| LLM     | yellow    | `#ffeb3b` |
| RAG     | cyan      | `#00bcd4` |
| SUCCESS | bright green | `#69f0ae` |
| WARN    | orange    | `#ff9800` |
| ERROR   | red       | `#f44336` |
| CANCEL  | dark orange | `#e65100` |

### _renderLogLines()
Receives `LogEntry[]`. Renders `[timestamp]` (dimmed) + `[LEVEL]` (smaller,
dimmed) + message colored by level. No keyword scanning.

### startAgentPolling() isDone check
```javascript
const isDone = logs.some(e =>
    (e.level === 'SUCCESS' && e.message.includes('completed'))
    || e.level === 'CANCEL'
);
```

`clearAgentLogs()`, `_logsOffset`, `_cachedLogs` unchanged.

---

## Tests Impacted

`test_agent_flow.py` — assertions on `/api/v1/agent/logs` response updated
to expect `{ts, level, message}` objects instead of plain strings.

---

## Files Changed

| File | Change |
|------|--------|
| `services/integration-agent/schemas.py` | Add `LogLevel`, `LogEntry` |
| `services/integration-agent/config.py` | Add `log_ttl_hours` |
| `services/integration-agent/main.py` | `log_agent()`, `_detect_level()`, TTL task, API response |
| `services/web-dashboard/js/app.js` | `_renderLogLines()`, `startAgentPolling()` |
| `services/integration-agent/tests/test_agent_flow.py` | Update log assertions |

---

## Trade-offs

- **No persistence**: logs are in-memory only — a container restart wipes them.
  Acceptable for PoC; a future ADR could add file-based rotation.
- **Auto-detect level**: fragile if message wording changes. Mitigated by
  having `_detect_level()` as a single testable function.
- **TTL granularity**: 30-minute prune interval means entries can live up to
  `log_ttl_hours + 0.5h` in the worst case. Acceptable.
