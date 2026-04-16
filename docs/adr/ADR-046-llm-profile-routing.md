# ADR-046 — LLM Multi-Profile Routing

**Status:** Accepted
**Date:** 2026-04-16
**Author:** Emiliano Gritti

---

## Context

The deployment environment was upgraded from a t3.2xlarge (8 vCPU, 32 GiB) to an m7i.4xlarge
(16 vCPU, 64 GiB, CPU-only). This opens room for a larger main model and a richer Ollama
options set, but on CPU inference the cost of a wrong sizing decision is paid in latency.
Three distinct call patterns exist in the stack:

| Pattern | Volume | Tokens | Latency budget |
|---|---|---|---|
| Document generation (Integration Spec) | Low — 1 per entry | 1800–2000 | Minutes — acceptable |
| Tag suggestion / query expansion | High — per upload, per trigger | 50–256 | < 60 s |
| Premium / complex sections | Occasional — user-requested | 1800 | Extended — acceptable |

The existing stack always uses a single `OLLAMA_MODEL` and passes only `num_predict` and
`temperature`. `num_ctx`, `top_p`, `top_k`, and `repeat_penalty` are left at Ollama defaults
(undocumented, typically 2048 / 0.9 / 40 / 1.1). Explicit control over these parameters
reduces generation variability on CPU-only hardware.

---

## Decision

Introduce **three named LLM profiles** and extend the Ollama options payload:

### Profiles

| Profile | Model | `num_ctx` | `num_predict` | `temperature` | `top_p` | `top_k` | `repeat_penalty` |
|---|---|---|---|---|---|---|---|
| `default` | `qwen2.5:14b` | 8192 | 2000 | 0.1 | 0.9 | 40 | 1.08 |
| `premium` | `gemma4:26b` | 6144 | 1800 | 0.0 | 0.85 | 30 | 1.1 |
| fast-utility (internal) | `qwen3:8b` | (settings default) | 50–256 | 0.1 | — | — | — |

### Routing rules

1. **Document generation** — uses the profile selected at trigger time (`default` or `premium`).
2. **Tag suggestion and query expansion** — always use the fast-utility model (`settings.tag_model`),
   independent of the document profile. This is not user-selectable.
3. **FactPack extraction / section rendering** — inherits the same profile kwargs as generation
   (passed via `_llm_kw` dict in `agent_service.py`).

### Options payload

`generate_with_ollama()` now sends the full options set to Ollama:

```json
{
  "num_predict":    2000,
  "temperature":    0.1,
  "num_ctx":        8192,
  "top_p":          0.9,
  "top_k":          40,
  "repeat_penalty": 1.08
}
```

### UI

A **Generation Profile** toggle (Default / Premium) is added to `AgentWorkspacePage.jsx`,
visible when the agent is idle. The selected profile is sent in `POST /agent/trigger` as
`llm_profile`. Tagging always uses fast-utility — no UI needed.

---

## Alternatives Considered

### A — Single configurable model via admin PATCH
Existing `PATCH /admin/llm-settings` already allows runtime model switching. Rejected because:
- Requires navigating to the admin panel before each generation.
- No per-trigger granularity — switching affects all concurrent sessions.
- Does not solve the routing issue (tags vs. generation use different optimal models).

### B — Two separate services
Run a dedicated lightweight service for tags/expansion. Rejected because:
- Adds operational complexity (new container, health-check, networking).
- The existing `generate_with_ollama(model=...)` kwarg is sufficient.

### C — Expose all three profiles in the UI
Allow the user to select "fast-utility" for generation. Rejected because:
- qwen3:8b is not suitable for full Integration Spec generation.
- The fast profile is an internal routing concern, not a user choice.

---

## Consequences

**Positive:**
- Explicit `num_ctx=8192` prevents silent 2048-token context truncation on qwen2.5:14b.
- Tags/expansion routed to qwen3:8b are faster and cheaper; main model stays warm.
- Premium profile (gemma4:26b) available on-demand for complex integrations.
- All new params are env-var overridable via `OLLAMA_NUM_CTX`, `PREMIUM_MODEL`, etc.

**Negative / risks:**
- `gemma4:26b` must be pulled on the Ollama instance before use (`ollama pull gemma4:26b`).
- `qwen3:8b` must similarly be pulled (`ollama pull qwen3:8b`).
- If a model is not pulled, the trigger fails with HTTP 404 from Ollama; the error message
  in the agent log is self-explanatory.

**Backward compatibility:**
- `llm_profile` defaults to `"default"` — no change for existing API callers.
- `tag_model` defaults to `"qwen3:8b"` — can be overridden to `"qwen2.5:14b"` via `TAG_MODEL`
  env var to preserve old behaviour.

---

## Validation Plan

1. Unit tests cover: config defaults, Ollama options payload shape, tag model routing,
   premium profile kwarg forwarding in `generate_integration_doc`.
2. Integration smoke test: trigger with `llm_profile="premium"` and verify agent log
   shows `profile='premium' model=gemma4:26b`.
3. Verify tag suggestion log shows the fast-utility model name.

---

## Rollback Strategy

- Set `TAG_MODEL=qwen2.5:14b` in `.env` to restore old tag behaviour.
- The UI toggle defaults to `"default"` — no action needed for rollback on that front.
- Remove the `llm_profile` field from `TriggerRequest` and `generate_integration_doc` if
  the feature needs to be fully reverted; the rest of the options payload is additive
  (Ollama ignores unknown options gracefully).

---

## Traceability

| Artefact | Reference |
|---|---|
| Config extension | `services/integration-agent/config.py` |
| LLM options payload | `services/integration-agent/services/llm_service.py` |
| Profile routing | `services/integration-agent/services/agent_service.py` |
| Tag/expansion routing | `services/integration-agent/services/tag_service.py`, `retriever.py` |
| Admin schema | `services/integration-agent/routers/admin.py` |
| UI selector | `services/web-dashboard/src/components/pages/AgentWorkspacePage.jsx` |
| Tests | `services/integration-agent/tests/test_llm_service.py`, `test_tag_service.py`, `test_agent_service.py`, `test_config.py` |
