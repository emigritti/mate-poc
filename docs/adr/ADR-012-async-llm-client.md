# ADR-012 — Async HTTP Client for LLM and Upstream Calls

| Field       | Value                     |
|-------------|---------------------------|
| **Status**  | Accepted                  |
| **Date**    | 2026-03-06                |
| **Author**  | AI-assisted (Claude Code) |
| **Refs**    | CLAUDE.md §10, §12        |

---

## Context

The integration-agent service originally used the synchronous `requests` library
to call the Ollama LLM endpoint.  FastAPI is an async framework built on `asyncio`.
Calling a synchronous blocking HTTP client from an async route handler stalls the
entire event loop for the duration of the LLM call (often 30–120 seconds), making
the service unresponsive to all other requests during generation.

The PLM and PIM mock-API services have a similar problem with synchronous `boto3`
S3 calls made from async route handlers.

---

## Decision

1. **integration-agent**: Replace `requests` with `httpx.AsyncClient` for all
   calls to Ollama.  Use `async with httpx.AsyncClient(timeout=...)` scoped per
   request to avoid shared state.

2. **PLM / PIM / DAM mock APIs**: Wrap all `boto3` calls in
   `asyncio.get_event_loop().run_in_executor(None, functools.partial(...))` so
   blocking I/O is offloaded to the default thread-pool executor, keeping the
   event loop free.

3. **catalog-generator**: Use `httpx.AsyncClient` for all upstream calls to the
   integration-agent.

---

## Alternatives Considered

| Option                              | Verdict    | Reason                                       |
|-------------------------------------|------------|----------------------------------------------|
| Keep `requests` + `asyncio.to_thread` | Rejected  | More verbose; no connection pooling          |
| `aiohttp`                           | Rejected   | Additional dependency; `httpx` API is cleaner|
| `aiobotocore` for S3                | Deferred   | Heavy dependency; `run_in_executor` sufficient for PoC |

---

## Consequences

**Positive:**
- Event loop never blocked during LLM calls → service remains responsive
- Concurrent health-check probes work even during active generation
- `httpx` supports HTTP/2 and connection pooling by default

**Negative / Trade-offs:**
- `run_in_executor` creates thread-pool pressure under high S3 concurrency
  (acceptable for PoC; replace with `aiobotocore` in production)
- `httpx.AsyncClient` must be closed properly; using `async with` ensures this

---

## Validation Plan

- Unit tests mock `httpx.AsyncClient` via `unittest.mock.AsyncMock` / `respx`
- Integration test: trigger generation and confirm health endpoint responds
  concurrently (no 5xx while LLM is running)

---

## Rollback Strategy

Revert `requirements.txt` to `requests==2.32.3` and restore synchronous
`generate_with_ollama`.  Regression: event loop blocking returns.
