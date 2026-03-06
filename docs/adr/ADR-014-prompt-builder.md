# ADR-014 — Prompt Builder: External Template File

| Field       | Value                     |
|-------------|---------------------------|
| **Status**  | Accepted                  |
| **Date**    | 2026-03-06                |
| **Author**  | AI-assisted (Claude Code) |
| **Refs**    | CLAUDE.md §11, §13        |

---

## Context

The integration-agent originally hard-coded the LLM prompt as a Python string
inside `main.py`.  This violates the **separation of concerns** principle and
makes prompt iteration slow (requires code changes and container rebuilds).

A `reusable-meta-prompt.md` file already existed in the repository root and
contained a well-structured prompt template with named slots.

---

## Decision

Introduce `prompt_builder.py` as a dedicated module that:

1. **Reads `reusable-meta-prompt.md`** at module import time and extracts the
   content of the first fenced ` ```text ` code block.

2. Exposes a single public function:
   ```python
   def build_prompt(
       source_system: str,
       target_system: str,
       formatted_requirements: str,
       rag_context: str = "",
   ) -> str
   ```

3. Conditionally injects a `PAST APPROVED EXAMPLES` block only when
   `rag_context` is non-empty/non-whitespace (prevents misleading empty sections).

4. Falls back to an **inline `_FALLBACK_TEMPLATE`** if the `.md` file is absent,
   so the service never crashes due to a missing template file.

### Template slots

| Slot                     | Injected value                              |
|--------------------------|---------------------------------------------|
| `{source_system}`        | Source system name (e.g. "PLM")             |
| `{target_system}`        | Target system name (e.g. "PIM")             |
| `{formatted_requirements}` | Requirements text block                   |
| `{rag_context}`          | Past approved examples (empty → omitted)    |

---

## Alternatives Considered

| Option                        | Verdict    | Reason                                      |
|-------------------------------|------------|---------------------------------------------|
| Jinja2 templating             | Deferred   | Extra dependency; Python `.format()` sufficient |
| Hard-coded string in main.py  | Rejected   | Violates SoC; cannot iterate without rebuild |
| Prompt stored in MongoDB      | Rejected   | Operational overhead; file is simpler for PoC |

---

## Consequences

**Positive:**
- Prompt iteration requires only editing `reusable-meta-prompt.md` (no code change)
- Fallback template prevents runtime crashes in CI/CD environments
- Explicit RAG context injection gate prevents LLM confusion from empty examples

**Negative / Trade-offs:**
- Template file must define all four slots or `str.format()` raises `KeyError`
  (caught by unit test `test_fallback_template_has_required_slots`)
- Module-level file read means a corrupt template file prevents app startup

---

## Validation Plan

`tests/test_prompt_builder.py` covers:
- All four slots appear in the rendered prompt
- RAG context section conditionally present/absent
- Hyphenated system names (`Azure-AD`, `SAP-ERP`) do not raise errors
- Fallback template contains all required slots

---

## Rollback Strategy

Revert `main.py` to inline prompt string and remove `prompt_builder.py`.
No data migration required.
