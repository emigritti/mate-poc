# Unit Test ↔ Security ↔ OWASP Mapping

| Area | Unit Test Focus | Security Focus | OWASP |
|------|----------------|----------------|-------|
| Input Validation | Boundary tests | Injection | A03 / ASVS 5 |
| Authorization | Role tests | Access control | A01 / ASVS 4 |
| Error Handling | Exception tests | Info leakage | A09 / ASVS 7 |
| Business Logic | Rule tests | Abuse prevention | A04 / ASVS 11 |
| AI Logic | Routing & fallback | Prompt injection | Agentic |