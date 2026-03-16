# ADR-020 — Tag LLM Tuning: Dedicated Lightweight Parameters

| Field        | Value                          |
|--------------|-------------------------------|
| **Status**   | Accepted                      |
| **Date**     | 2026-03-16                    |
| **Deciders** | Integration Mate PoC team     |
| **Tags**     | performance, llm, configuration |

## Context

`_suggest_tags_via_llm()` in `main.py` called `generate_with_ollama()` using the
same parameters as the main document-generation flow:

- `num_predict = 1000` tokens
- `timeout = 120 s` (default; docker-compose uses 600 s)
- `temperature = 0.3`

Generating `["Data Sync", "Real-time"]` requires ≈15 tokens. On a CPU instance
running llama3.1:8b at ~3 tok/s, the model generates padding until it hits
`num_predict`, making the tag call take 30–60 s unnecessarily.

## Decision

Add three dedicated settings following the ADR-016 env-var pattern:

| Setting               | Env var               | Default | Rationale                                       |
|-----------------------|-----------------------|---------|-------------------------------------------------|
| `tag_num_predict`     | `TAG_NUM_PREDICT`     | `20`    | 2 tags × ~7 tokens = 14; 20 gives headroom      |
| `tag_timeout_seconds` | `TAG_TIMEOUT_SECONDS` | `15`    | 20 tokens at 3 tok/s ≈ 7 s; 15 s for cold-start |
| `tag_temperature`     | `TAG_TEMPERATURE`     | `0.0`   | Tags must be deterministic/reproducible          |

`generate_with_ollama()` gains three optional keyword-only arguments
(`num_predict`, `timeout`, `temperature`). When `None` (default), global settings
apply — all existing callers (main doc generation) are unaffected.

## Alternatives Considered

| Option                                         | Rejected because                                           |
|------------------------------------------------|------------------------------------------------------------|
| Hardcode values inline in `_suggest_tags_via_llm` | Violates ADR-016; not tunable without code change       |
| Replace with external LLM API (Claude, OpenAI) | External dependency + API key; out of scope for self-hosted PoC |
| Remove LLM entirely from tag suggestion        | Loses semantic enrichment; category-only tags remain as fallback |

## Consequences

- Tag suggestion latency drops from ~30–60 s → ~2–5 s on CPU (warm model).
- `generate_with_ollama()` signature change is fully backwards-compatible
  (new params default to `None`; existing callers require no modification).
- **Rollback:** set env vars `TAG_NUM_PREDICT=1000`, `TAG_TIMEOUT_SECONDS=120`,
  `TAG_TEMPERATURE=0.3` — no rebuild required.

## Validation

- `test_config.py`: 3 tests verify default values of the new settings.
- `test_tag_suggestion.py`: 1 test verifies `_suggest_tags_via_llm()` forwards
  the tag settings as explicit kwargs to `generate_with_ollama()`.
- Full suite (113 tests) must remain green.

## References

- ADR-016: Secret Management via Pydantic Settings (env-var pattern)
- ADR-019: RAG Tag-Filtering with HITL Tag Confirmation Gate
