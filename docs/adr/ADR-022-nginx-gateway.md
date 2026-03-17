# ADR-022 — Nginx Reverse-Proxy Gateway — Centralised Port Routing

| Field          | Value                                                                       |
|----------------|-----------------------------------------------------------------------------|
| **Status**     | Accepted                                                                    |
| **Date**       | 2026-03-17                                                                  |
| **Author**     | AI-assisted (Claude Code)                                                   |
| **Supersedes** | —                                                                           |
| **OWASP**      | A05:2021 — Security Misconfiguration, A01:2021 — Broken Access Control     |
| **CLAUDE.md**  | §10 (Security & Secure Coding), §11 (AI/Agentic Security), §12 (DevSecOps) |

---

## Context

The web dashboard (port 8080) made direct browser `fetch` calls to three separate backend
services on non-standard ports:

| Service           | Direct port |
|-------------------|-------------|
| Integration Agent | 4003        |
| PLM Mock API      | 4001        |
| PIM Mock API      | 4002        |

Corporate and restricted networks routinely block outbound connections to non-standard ports
(anything other than 80 / 443).  In those environments every API call failed with
**"Failed to fetch"**, making the PoC entirely unusable without network-level exceptions.

Secondary problems introduced by the multi-port topology:

- Each backend was required to maintain its own CORS middleware to allow cross-origin requests
  from the dashboard origin (ADR-018).  Any misconfiguration reopened CORS vulnerabilities.
- Security response headers (e.g., `X-Content-Type-Options`, `X-Frame-Options`) had to be
  applied independently in every service with no single enforcement point.
- The Integration Agent executes Ollama CPU inference that can take 60–120 s per request.
  Default proxy and browser timeouts silently dropped these long-running requests.

---

## Decision

Introduce a dedicated `mate-gateway` nginx container as the **single public entry point** for
the PoC stack.

### Routing rules

| Path prefix | Upstream                       | Notes                                         |
|-------------|--------------------------------|-----------------------------------------------|
| `/agent/`   | `mate-integration-agent:3003`  | `proxy_read_timeout 600s` for Ollama inference |
| `/plm/`     | `mate-plm-mock:3001`           | Standard proxy pass                           |
| `/pim/`     | `mate-pim-mock:3002`           | Standard proxy pass                           |
| `/`         | `mate-web-dashboard:80`        | Static SPA assets                             |

### Security headers applied by the gateway (all responses)

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
```

### nginx configuration highlights

```nginx
proxy_buffering    off;      # future-proofs for LLM token streaming
proxy_http_version 1.1;     # required for keep-alive / SSE
proxy_read_timeout 600s;    # agent location only — Ollama CPU inference
```

### Frontend changes

`src/api.js` and `js/api.js` are updated to use **gateway-relative paths** instead of
absolute `http://hostname:PORT` URLs:

| Before                          | After          |
|---------------------------------|----------------|
| `http://${host}:4003/api/...`   | `/agent/api/...` |
| `http://${host}:4001/...`       | `/plm/...`       |
| `http://${host}:4002/...`       | `/pim/...`       |

All `fetch` calls become same-origin.  CORS headers are therefore **not required** on any
backend service for browser-initiated requests.

### Docker Compose changes

The `web-dashboard` service is changed from `ports: - "8080:80"` to `expose: - "80"`
(internal only).  The `gateway` service is the sole container that publishes host port 8080.

---

## Alternatives Considered

| Alternative | Reason Rejected |
|-------------|-----------------|
| **Open ports 4001/4002/4003 on the AWS Security Group** | Increases attack surface; requires network configuration on every deployment; does not help for corporate networks where outbound traffic to non-standard ports is also filtered |
| **SSH tunnel / VPN** | Requires per-user setup; not suitable for a PoC demo environment accessible to non-technical stakeholders without client-side configuration |
| **Proxy through the web-dashboard nginx container** | Mixes static-file serving with API proxying in one container; harder to scale, replace, or audit independently; violates the single-responsibility principle |
| **Port 443 / TLS termination at nginx** | Deferred — requires SSL certificate management; acceptable limitation for an internal PoC; noted as a future improvement |

---

## Consequences

### Positive

- Single public port (8080); no firewall exceptions required for the PoC to function.
- All browser `fetch` calls are same-origin — CORS configuration on backend services is no
  longer needed for normal dashboard traffic.
- Centralised, auditable enforcement point for security response headers.
- `proxy_buffering off` + `proxy_http_version 1.1` future-proofs the gateway for streaming
  LLM output (SSE / chunked transfer encoding) without further nginx changes.
- Long-running Ollama inference requests survive with `proxy_read_timeout 600s` instead of
  being silently dropped.
- Backend services are no longer directly reachable from the host network, reducing the
  external attack surface.

### Negative

- Adds one container to the stack (minimal CPU/memory overhead; nginx idle footprint is
  negligible).
- The gateway is a single point of failure.  Mitigation: nginx is a mature, highly stable
  reverse proxy; in a production environment a load balancer or redundant gateway would be
  added (out of scope for PoC).
- Path-prefix routing requires careful `proxy_pass` slash handling to avoid double-prefix
  issues; this is a known nginx pattern and is covered by the validation plan below.

---

## Validation Plan

| Test ID | Scenario | Expected |
|---------|----------|----------|
| GW-001 | `curl http://localhost:8080/` | Returns dashboard `index.html` with HTTP 200 |
| GW-002 | `curl http://localhost:8080/agent/health` | Returns `{"status":"ok"}` from Integration Agent |
| GW-003 | `curl http://localhost:8080/plm/health` | Returns `{"status":"ok"}` from PLM Mock |
| GW-004 | `curl http://localhost:8080/pim/health` | Returns `{"status":"ok"}` from PIM Mock |
| GW-005 | Browser network tab during a full analysis run | All `fetch` calls target `http://host:8080/agent/...` — no cross-origin requests visible |
| GW-006 | `curl -I http://localhost:8080/` | Response headers include `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY` |
| GW-007 | Submit a long analysis request (Ollama CPU, ~90 s) | Request completes; no 504 Gateway Timeout |
| GW-008 | Attempt direct access to `http://localhost:4003` from the host | Connection refused — port not published on host |

Manual verification via browser DevTools Network tab and `curl`.

---

## Rollback Strategy

1. Remove the `gateway` service block from `docker-compose.yml`.
2. Restore `ports: - "8080:80"` on the `web-dashboard` service (remove `expose: - "80"`).
3. Revert `src/api.js` and `js/api.js` to use `http://${hostname}:PORT` absolute URLs.
4. Re-enable CORS middleware on PLM, PIM, and Integration Agent if required (see ADR-018).
5. Run `docker compose up -d web-dashboard`.

Estimated rollback time: < 5 minutes.  Risk: **LOW** — all changes are configuration and
frontend URL constants; no data migrations or schema changes are involved.

---

## OWASP Mapping

| Risk | Mitigation |
|------|-----------|
| A05 — Security Misconfiguration | Centralised security headers (`X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`) enforced at the gateway for every response |
| A01 — Broken Access Control | Backend services no longer exposed on host-level ports; all external access is mediated through the gateway's path-prefix routing rules |
| A03 — Injection (abuse of long-timeout route) | `proxy_read_timeout 600s` applied to `/agent/` only; all other routes use the nginx default (60 s), limiting the blast radius |

---

## Related ADRs

- **ADR-017** — Frontend XSS Mitigation: the gateway's `X-XSS-Protection` and
  `X-Content-Type-Options` headers provide a complementary defence-in-depth layer alongside
  the `escapeHtml` controls introduced in ADR-017.
- **ADR-018** — CORS Standardisation: same-origin fetch calls via the gateway make CORS
  headers unnecessary for browser traffic, simplifying the CORS policy applied in ADR-018.
