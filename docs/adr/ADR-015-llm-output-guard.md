# ADR-015 — LLM Output Guard: Structural Validation + XSS Sanitization

| Field       | Value                        |
|-------------|------------------------------|
| **Status**  | Accepted                     |
| **Date**    | 2026-03-06                   |
| **Author**  | AI-assisted (Claude Code)    |
| **Refs**    | CLAUDE.md §10, §11; OWASP A03, A05 |

---

## Context

LLM output is **untrusted input** (CLAUDE.md §10 — "LLM output is ALWAYS treated
as untrusted input").  Two threat classes exist:

1. **Structural drift**: The LLM may return text that does not match the expected
   format (e.g. a preamble like "Sure! Here is your spec:" before the required
   `# Functional Specification` heading), making downstream parsing unreliable.

2. **Stored XSS (OWASP A03)**: The LLM output is stored in MongoDB and later
   rendered in the web dashboard.  If the LLM includes `<script>` tags or event
   attributes (possible via prompt injection), they could execute in a reviewer's
   browser.

The approval endpoint also accepts `final_markdown` from a human reviewer whose
clipboard may contain malicious content (same XSS risk).

---

## Decision

Introduce `output_guard.py` with two public functions:

### `sanitize_llm_output(raw: str) -> str`

**Strict mode** — enforces:
1. **Structural guard**: Input must start exactly with `# Functional Specification`
   (after stripping leading whitespace).  If not, raises `LLMOutputValidationError`.
2. **HTML sanitization**: `bleach.clean()` with an explicit allowlist of safe tags
   (`p`, `br`, `strong`, `em`, `code`, `pre`, `ul`, `ol`, `li`, `h1`–`h6`, `a`)
   and no dangerous attributes.  Removes `<script>`, `<iframe>`, `onclick=`, etc.
3. **Truncation**: Output capped at 50,000 characters to prevent storage exhaustion.

### `sanitize_human_content(raw: str) -> str`

**Lenient mode** — no structural guard (reviewer edits don't need the heading),
but same bleach sanitization + truncation.

### `LLMOutputValidationError`

Custom exception raised by `sanitize_llm_output` when the structural guard fails.
The caller logs the raw output and returns HTTP 500 to the client — the raw
output is **never stored or forwarded**.

---

## Alternatives Considered

| Option                           | Verdict    | Reason                                         |
|----------------------------------|------------|------------------------------------------------|
| No sanitization                  | Rejected   | OWASP A03 / stored XSS risk                   |
| Regex-based HTML stripping       | Rejected   | Incomplete; regex cannot parse nested HTML     |
| `markupsafe.escape` only         | Rejected   | Escapes all HTML; breaks intentional formatting|
| `bleach` allowlist               | **Accepted** | Industry-standard; explicit safe-tag model   |

---

## Consequences

**Positive:**
- XSS is eliminated at the storage boundary (defense in depth)
- Structural drift detected before persisting to MongoDB
- Unit-testable in isolation (no LLM / network required)

**Negative / Trade-offs:**
- `bleach` is deprecated upstream (maintenance mode); monitor for replacement
- Structural guard requires LLM to comply with the meta-prompt format;
  fine-tuned or different models may need the guard updated
- 50,000-char truncation silently shortens very long outputs

---

## OWASP Mapping

| Control            | OWASP Reference |
|--------------------|-----------------|
| XSS prevention     | A03:2021 – Injection |
| Output encoding    | A05:2021 – Security Misconfiguration (no CSP bypass) |
| Structural guard   | A08:2021 – Software and Data Integrity |

---

## Validation Plan

`tests/test_output_guard.py` covers all threat scenarios:
- Valid output passes through unchanged (structure + content)
- Missing heading raises `LLMOutputValidationError`
- `<script>`, `<iframe>`, `onclick` stripped
- Output truncated at 50,000 chars
- Human content: no structural guard; XSS still stripped

---

## Rollback Strategy

Remove `sanitize_llm_output` / `sanitize_human_content` calls from `main.py`
and delete `output_guard.py`.  LLM output stored raw.  XSS risk reintroduced.
