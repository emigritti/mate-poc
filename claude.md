# claude.md — FINAL Accenture‑Compliant AI‑Assisted Development Guide

This file is the **single authoritative contract** governing how Claude Code is used in this repository.
It consolidates **all architecture, quality, testing, security, AI‑governance, and compliance rules**.

Claude is used strictly as an **AI assistant**, never as an autonomous actor.

---

## 0. Mission & Priorities

Claude supports:
- architecture & design
- feature planning
- code quality improvement
- testing (especially unit tests)
- security & OWASP‑aligned reviews

**Priority order (non‑negotiable):**
Security & Compliance > Architecture > Testability > Maintainability > Speed

---

## 1. Data Usage Boundary (Accenture Compliance)

Claude MUST be used ONLY with:
- synthetic data
- anonymized data
- public / open data
- internally generated examples

Claude MUST NOT be used with:
- client data
- confidential Accenture data
- PII or sensitive personal data
- data classified above "Internal"

If real data is required, STOP and use an approved alternative.

---

## 2. Responsible AI (Accenture Principles)

When AI is involved:
- Be transparent about AI usage
- Avoid hidden automation
- Keep a human‑in‑the‑loop for decisions
- Validate outputs for correctness and bias
- Prefer explainable and controllable behavior
- Document limitations explicitly

---

## 3. Default Working Method (Mandatory)

For any non‑trivial task:

A) Observe — inspect repo, context, constraints
B) Plan — decompose feature (Feature Dev plugin if available)
C) Decide — create/update ADR if needed
D) Validate — define tests and security checks
E) Implement — minimal, incremental change
F) Review — quality + security gates
G) Document — traceability

Skipping steps is NOT allowed.

---

## 4. Architecture Decision Records (ADR)

ADR is mandatory when a change:
- affects architecture or integration patterns
- introduces AI / agentic behavior
- impacts security, data, or compliance
- is risky or hard to rollback

Use: `docs/adr/ADR-000-template.md`

ADRs MUST include:
- alternatives & trade‑offs
- validation plan
- rollback strategy

---

## 5. Feature Planning (Feature Dev Plugin)

For any non‑trivial feature:
- Use Feature Dev plugin during planning (if available)
- Define:
  - scope
  - acceptance criteria
  - risks (technical, security, operational)
  - testability (especially unit tests)
  - rollback implications

Mandatory disclosure:
- ✅ Feature Dev plugin used (summary)
OR
- ❌ Plugin not available (manual plan provided)

---

## 6. Testing Strategy (Mandatory)

Testing is required for behavior, architecture, security, and AI logic.

Test layers:
- Unit (primary quality signal)
- Component / contract
- Integration
- Non‑functional (when relevant)
- Security‑focused tests

Use: `docs/test-plan/TEST-PLAN-000-template.md`

---

## 7. Unit Testing — First‑Class Quality Gate

Unit tests are NOT optional.

### 7.1 What MUST be unit tested
- business logic
- decision rules
- edge cases & error paths
- validation & authorization logic
- AI orchestration logic (routing, fallback, guards)

### 7.2 Unit test quality rules
Unit tests MUST be:
- deterministic
- fast
- isolated
- readable (tests are documentation)

Avoid:
- external dependencies
- over‑mocking that hides behavior

If code is hard to unit test, reconsider the design.

### 7.3 Unit Test Review
All reviews MUST use:
`docs/unit-test-review/UNIT-TEST-REVIEW-CHECKLIST.md`

---

## 8. Code Quality Rules (Strict)

- clarity over cleverness
- small, composable units
- explicit error handling
- no hidden side effects
- consistent naming and structure

If a rule is violated, explain WHY and document the trade‑off.

---

## 9. Superpowers Plugin Usage (Mandatory)

Superpowers MUST be used for:
- architecture analysis
- refactoring
- code review
- smell & complexity detection

Mandatory disclosure:
**Superpowers Check**
- complexity
- duplication
- maintainability
- test gaps
- rollback risks

---

## 10. Security & Secure Coding (Mandatory)

Security is first‑class.

Rules:
- secure‑by‑default coding
- no hardcoded secrets
- least privilege everywhere
- explicit input validation
- meaningful security logging

Use:
- Anthropic Security Guidance plugin (if available)
- OWASP ASVS / Top 10 checklist

LLM output is ALWAYS treated as untrusted input.

---

## 11. AI / Agentic Security

When AI or agents are involved:
- protect against prompt injection
- restrict tool access (allow‑list)
- define kill‑switch & fallback
- avoid autonomous actions without guards

Aligned with Accenture Agentic AI Security Standard.

---

## 12. DevSecOps Mindset

Security and quality are continuous:
- during planning
- during coding
- during review

Late security fixes are design failures.

---

## 13. Traceability (Mandatory)

Traceability MUST exist:
- Code → ADR
- ADR → Test Plan
- Test Plan → Unit Tests
- Security Review → OWASP mapping

Missing traceability = NOT DONE.

---

## 14. Definition of Done (Strict)

A task is DONE only if:
- Feature plan completed
- ADR created/updated (if required)
- Unit tests written and reviewed
- Code review checklist passed
- Security review completed (OWASP aligned)
- No restricted data used
- Update architecture_specification.md document
- Update functional-guide.md document